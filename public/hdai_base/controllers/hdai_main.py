# -*- coding: utf-8 -*-
"""Streaming HTTP controller for HD AI chat."""

import json
import logging

import werkzeug.wrappers

from odoo import _, api, http
from odoo.http import request
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)


class HdaiChatController(http.Controller):

    @http.route('/hdai_base/chat/stream', type='http', auth='user',
                methods=['POST'], csrf=False)
    def hdai_chat_stream(self, **kwargs):
        """Stream a chat completion as NDJSON lines.

        Prep (user message, history, options) runs on the request cursor.
        The response generator opens a dedicated cursor and runs
        ``_live_stream_tool_loop`` so first-round tokens are flushed to the
        client as they arrive (error_reference 2.3/2.4/2.6).
        """
        raw = request.httprequest.get_data(as_text=True) or '{}'
        try:
            data = json.loads(raw)
        except ValueError:
            return werkzeug.wrappers.Response(
                '{"error":"Invalid JSON payload"}\n', status=400,
                content_type='application/x-ndjson; charset=utf-8')
        session_id = data.get('session_id')
        content = (data.get('content') or '').strip()
        options = data.get('options') or {}
        if not session_id or not content:
            return werkzeug.wrappers.Response(
                '{"error":"Missing session_id or content"}\n', status=400,
                content_type='application/x-ndjson; charset=utf-8')
        session = request.env['hdai.session'].browse(
            int(session_id)).exists()
        if not session or session.user_id.id != request.env.user.id:
            return werkzeug.wrappers.Response(
                '{"error":"Forbidden"}\n', status=403,
                content_type='application/x-ndjson; charset=utf-8')

        session.write({'state': 'open'})
        request.env['hdai.message'].create({
            'session_id': session.id,
            'role': 'user',
            'content': content,
        })
        session._mirror_to_channel('user', content)
        if session.name == _('New Session'):
            session.name = content[:30]
        model = session.model_id or session._get_default_model()
        if model and not session.model_id:
            session.write({
                'model_id': model.id,
                'provider_id': model.provider_id.id,
            })
        if not model:
            return werkzeug.wrappers.Response(
                json.dumps({
                    'error': _('No default model is configured. Configure a '
                               'model provider and test the connection to '
                               'fill its model list before chatting.'),
                    'code': 'no_model',
                }) + '\n',
                content_type='application/x-ndjson; charset=utf-8')
        allowed = model._allowed_options()
        if not allowed['streaming']:
            return werkzeug.wrappers.Response(
                json.dumps({
                    'error': _('Streaming is disabled for this model.'),
                    'code': 'streaming_disabled',
                }) + '\n',
                content_type='application/x-ndjson; charset=utf-8')

        history = session._build_history()
        call_options = session._call_options(history)
        reasoning_strength = options.get(
            'reasoning_strength', session.reasoning_strength)
        web_search = options.get('web_search', session.web_search_enabled)
        if not allowed['reasoning']:
            reasoning_strength = 'none'
        if not allowed['web_search']:
            web_search = False
        stream_options = {
            'reasoning_strength': reasoning_strength,
            'web_search': web_search,
            'language_mode': call_options.get('language_mode'),
            'lang': call_options.get('lang'),
            'system_prompt': call_options.get('system_prompt'),
            'context_text': call_options.get('context_text'),
            'language_instruction': call_options.get('language_instruction'),
        }
        dbname = request.env.cr.dbname
        uid = request.env.uid
        context = dict(request.env.context)
        model_id = model.id
        session_id = session.id
        # Plain history snapshot (no ORM records).
        history_snapshot = [dict(msg) for msg in history]

        def generate():
            registry = Registry(dbname)
            with registry.cursor() as cr:
                env = api.Environment(cr, uid, context)
                live_session = env['hdai.session'].browse(session_id)
                live_model = env['hdai.model'].browse(model_id)
                if not live_session.exists() or not live_model.exists():
                    yield json.dumps({
                        'error': _('Session or model is no longer available.'),
                        'code': 'missing',
                    }) + '\n'
                    yield json.dumps({'done': True}) + '\n'
                    return
                result = None
                try:
                    for event in live_session._live_stream_tool_loop(
                            live_model, history_snapshot, stream_options):
                        event_type = event.get('type')
                        if event_type == 'result':
                            result = event.get('result') or {}
                            continue
                        if event_type == 'delta':
                            yield json.dumps(
                                {'delta': event['delta']}) + '\n'
                        elif event_type == 'reasoning_delta':
                            yield json.dumps(
                                {'reasoning_delta': event['delta']}) + '\n'
                        elif event_type == 'tool_call':
                            yield json.dumps({
                                'tool_call': {
                                    'name': event.get('name'),
                                    'card': event.get('card'),
                                },
                            }) + '\n'
                        elif event_type == 'action':
                            yield json.dumps({
                                'action': event.get('action'),
                            }) + '\n'
                        elif event_type == 'tool_card':
                            yield json.dumps(
                                {'tool_card': event.get('card')}) + '\n'
                        elif event_type == 'limit':
                            yield json.dumps(
                                {'limit': event.get('message')}) + '\n'
                        elif event_type == 'usage':
                            yield json.dumps(
                                {'usage': event.get('usage')}) + '\n'
                    loop_error = (result or {}).get('error')
                    if loop_error:
                        yield json.dumps({
                            'error': loop_error.get('message') or _(
                                'The model could not be reached.'),
                            'code': loop_error.get('code')
                            or 'model_call_failed',
                        }) + '\n'
                    elif result:
                        live_session._persist_rounds(result)
                        reply = result.get('reply') or ''
                        if reply:
                            live_session._mirror_to_channel(
                                'assistant', reply)
                    cr.commit()
                except Exception:  # noqa: BLE001
                    _logger.exception('hdai live stream failed')
                    cr.rollback()
                    yield json.dumps({
                        'error': _('Unexpected streaming error.'),
                        'code': 'unexpected',
                    }) + '\n'
                yield json.dumps({'done': True}) + '\n'

        return werkzeug.wrappers.Response(
            generate(),
            headers={
                'Content-Type': 'application/x-ndjson; charset=utf-8',
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
            },
        )


def _save_stream_result(dbname, uid, context, session_id, reply, reasoning,
                        usage=None):
    """Persist the streamed assistant reply with a dedicated cursor."""
    if not reply and not reasoning:
        return
    usage = usage or {}
    registry = Registry(dbname)
    with registry.cursor() as cr:
        env = api.Environment(cr, uid, context)
        env['hdai.message'].create({
            'session_id': session_id,
            'role': 'assistant',
            'content': reply,
            'reasoning_content': reasoning,
            'prompt_tokens': usage.get('prompt_tokens') or 0,
            'completion_tokens': usage.get('completion_tokens') or 0,
            'total_tokens': usage.get('total_tokens') or 0,
        })
        env['hdai.session'].browse(session_id)._mirror_to_channel(
            'assistant', reply)
