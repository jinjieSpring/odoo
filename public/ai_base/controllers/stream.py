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

        payload = request.env['ai.base.service'].stream_chat(
            content, session, options)
        events = payload.get('events') or []
        loop_error = payload.get('error')

        def generate():
            if loop_error:
                yield _sse('error', {
                    'error': loop_error.get('message') or _(
                        'The model could not be reached.'),
                    'code': loop_error.get('code') or 'model_call_failed',
                })
                yield _sse('done', {})
                return
            for event in events:
                event_type = event.get('type')
                if event_type == 'delta':
                    yield _sse('delta', {'delta': event['delta']})
                elif event_type == 'reasoning_delta':
                    yield _sse('reasoning_delta', {'delta': event['delta']})
                elif event_type == 'tool_call':
                    yield _sse('tool_call', {
                        'name': event.get('name'),
                        'card': event.get('card'),
                    })
                elif event_type == 'tool_card':
                    yield _sse('tool_card', {'card': event.get('card')})
                elif event_type == 'limit':
                    yield _sse('limit', {'message': event.get('message')})
                elif event_type == 'usage':
                    yield _sse('usage', {'usage': event.get('usage')})
            yield _sse('done', {})

        return werkzeug.wrappers.Response(
            generate(),
            headers={
                'Content-Type': 'text/event-stream; charset=utf-8',
                'Cache-Control': 'no-cache',
                'X-Accel-Buffering': 'no',
            },
        )
