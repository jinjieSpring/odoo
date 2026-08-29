# -*- coding: utf-8 -*-
"""SSE streaming controller for AI chat."""

import json
import logging

import werkzeug.wrappers

from odoo import _, http
from odoo.http import request

_logger = logging.getLogger(__name__)


def _sse(event, data):
    return 'event: %s\ndata: %s\n\n' % (event, json.dumps(data, ensure_ascii=False))


class AiBaseStreamController(http.Controller):

    @http.route('/ai_base/chat/stream', type='http', auth='user',
                methods=['POST'], csrf=False)
    def chat_stream(self, **kwargs):
        raw = request.httprequest.get_data(as_text=True) or '{}'
        try:
            data = json.loads(raw)
        except ValueError:
            return werkzeug.wrappers.Response(
                _sse('error', {'error': 'Invalid JSON payload'}),
                status=400,
                content_type='text/event-stream; charset=utf-8')
        session_id = data.get('session_id')
        content = (data.get('content') or '').strip()
        options = data.get('options') or {}
        if not session_id or not content:
            return werkzeug.wrappers.Response(
                _sse('error', {'error': 'Missing session_id or content'}),
                status=400,
                content_type='text/event-stream; charset=utf-8')
        session = request.env['ai.chat.session'].browse(
            int(session_id)).exists()
        if not session or session.user_id.id != request.env.user.id:
            return werkzeug.wrappers.Response(
                _sse('error', {'error': 'Forbidden'}),
                status=403,
                content_type='text/event-stream; charset=utf-8')

        payload = session._ai_service().stream_chat(
            content, session, options)
        events = payload.get('events') or []
        loop_error = payload.get('error')

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
                    yield json.dumps({'reasoning_delta': event['delta']}) + '\n'
                elif event_type == 'tool_call':
                    yield json.dumps({
                        'tool_call': {
                            'name': event.get('name'),
                            'card': event.get('card'),
                        },
                    }) + '\n'
                elif event_type == 'tool_card':
                    yield json.dumps({'tool_card': event.get('card')}) + '\n'
                elif event_type == 'limit':
                    yield json.dumps({'limit': event.get('message')}) + '\n'
                elif event_type == 'usage':
                    yield json.dumps({'usage': event.get('usage')}) + '\n'
                elif event_type == 'action':
                    yield json.dumps({'action': event.get('action')}) + '\n'
            yield json.dumps({'done': True}) + '\n'

        return werkzeug.wrappers.Response(
            generate(),
            headers={
                'Content-Type': 'application/x-ndjson; charset=utf-8',
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
            },
        )
