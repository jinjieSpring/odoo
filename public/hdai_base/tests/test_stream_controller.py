from contextlib import contextmanager
from unittest.mock import patch

from odoo.tests import TransactionCase

from odoo.addons.hdai_base.controllers.hdai_main import _save_stream_result
from odoo.addons.hdai_base.models.hdai_session import HdaiSession
from odoo.addons.hdai_base.models.llm_service import LLMService
from odoo.addons.hdai_base.models.hdai_tools import split_tool_content
from odoo.modules.registry import Registry


class TestStreamController(TransactionCase):
    def test_parse_tool_payload(self):
        session = self.env['hdai.session']
        payload = session._parse_tool_payload(
            '```json\n{"tool": "open_view", "model": "res.partner"}\n```')
        self.assertEqual(payload['model'], 'res.partner')
        self.assertIsNone(session._parse_tool_payload('plain answer'))

    def test_parse_tool_payload_is_env_free(self):
        """The stream generator parses the tool payload after the request
        context is gone, so the parser must work as a pure static call."""
        payload = HdaiSession._parse_tool_payload(
            '```json\n{"tool": "open_view", "model": "res.partner"}\n```')
        self.assertEqual(payload['model'], 'res.partner')
        self.assertIsNone(HdaiSession._parse_tool_payload('plain answer'))

    def test_split_tool_content(self):
        before, payload, after = split_tool_content(
            'Here is the view:\n```json\n{"tool": "open_view", '
            '"model": "res.partner"}\n```\nEnjoy.')
        self.assertIn('Here is the view', before)
        self.assertEqual(payload['model'], 'res.partner')
        self.assertIn('Enjoy', after)
        before, payload, after = split_tool_content('plain text')
        self.assertIsNone(payload)
        self.assertEqual(before, 'plain text')

    def test_save_stream_result_persists_reply(self):
        provider = self.env['hdai.provider'].create({
            'name': 'Stream Provider',
            'provider_type': 'openai',
            'base_url': 'https://api.test.openai/v1',
            'api_key': 'key',
        })
        model = self.env['hdai.model'].create({
            'name': 'Stream Model',
            'code': 'gpt-4o-mini',
            'provider_id': provider.id,
        })
        session = self.env['hdai.session'].create({
            'name': 'Stream Session',
            'model_id': model.id,
        })
        dbname = self.env.cr.dbname

        @contextmanager
        def current_cursor(*args, **kwargs):
            yield self.env.cr

        with patch.object(Registry, 'cursor', current_cursor):
            _save_stream_result(
                dbname, self.env.uid, dict(self.env.context),
                session.id, 'streamed reply', 'thinking',
                {'prompt_tokens': 4, 'completion_tokens': 2,
                 'total_tokens': 6})
        message = session.message_ids.filtered(
            lambda m: m.role == 'assistant')[:1]
        self.assertEqual(message.content, 'streamed reply')
        self.assertEqual(message.reasoning_content, 'thinking')
        self.assertEqual(message.total_tokens, 6)
