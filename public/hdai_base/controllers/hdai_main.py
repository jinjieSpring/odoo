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

        Body: JSON object with ``session_id``, ``content`` and ``options``.
        Lines: ``delta`` / ``reasoning_delta`` per loop round, ``tool_call``
        for automatically executed read-only tools, ``tool_card`` when a
        suggestion/blocked card pauses the loop, ``limit``, ``usage`` and a
        final ``done`` line. The whole tool loop runs synchronously in the
        request phase; the generator only replays the collected plain-data
        events (error_reference 2.3/2.4/2.6: no ORM in stream generators).
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

        # All ORM work must happen before the response starts streaming: Odoo
        # closes the request cursor once the controller returns while the
        # generator is consumed later by the WSGI server.
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
        stream_options = dict(call_options)
        stream_options.update({
            'reasoning_strength': reasoning_strength,
            'web_search': web_search,
        })

        # Run the server-side tool loop while the request cursor is still
        # valid: the loop calls the model (optionally multiple rounds),
        # executes read-only tools as the calling user and persists the
        # assistant messages. Only plain-data events are collected here and
        # replayed by the response generator below.
        events = []
        result = session._run_tool_loop(
            model, history, stream_options,
            emit=lambda event: events.append(event))
        session._persist_rounds(result)
        reply = result.get('reply') or ''
        if reply:
            session._mirror_to_channel('assistant', reply)
        loop_error = result.get('error')

        def generate():
            if loop_error:
                yield json.dumps({
                    'error': loop_error.get('message') or _(
                        'The model could not be reached.'),
                    'code': loop_error.get('code') or 'model_call_failed',
                }) + '\n'
                yield json.dumps({'done': True}) + '\n'
                return
            for event in events:
                event_type = event.get('type')
                if event_type == 'delta':
                    yield json.dumps({'delta': event['delta']}) + '\n'
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
                    yield json.dumps({'usage': event.get('usage')}) + '\n'
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
