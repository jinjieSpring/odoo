# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.addons.ai_base.controllers.stream import _sse
from odoo.addons.ai_base.tests.common import AiBaseCase


class TestStream(AiBaseCase):
    def test_sse_format(self):
        line = _sse('delta', {'delta': 'hi'})
        self.assertIn('event: delta', line)
        self.assertIn('"delta": "hi"', line)
        self.assertTrue(line.endswith('\n'))

    def test_stream_chat_collects_plain_events(self):
        session = self.env['ai.chat.session'].create({'name': 'S'})
        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                return_value={
                    'content': 'chunk',
                    'reasoning': 'why',
                    'tool_calls': [],
                    'usage': {
                        'prompt_tokens': 1,
                        'completion_tokens': 1,
                        'total_tokens': 2,
                    },
                }):
            payload = self.env['ai.chat.service'].stream_chat('hi', session)
        types = [event['type'] for event in payload['events']]
        self.assertIn('delta', types)
        self.assertIn('reasoning_delta', types)
        self.assertIn('usage', types)
        self.assertFalse(payload.get('error'))
        for event in payload['events']:
            self.assertNotIn('env', event)
            self.assertIsInstance(event, dict)
