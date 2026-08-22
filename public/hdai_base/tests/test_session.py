# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import AccessError
from odoo.tests import TransactionCase

from odoo.addons.hdai_base.models.llm_service import LLMService


class TestSession(TransactionCase):
    def setUp(self):
        super().setUp()
        self.provider = self.env['hdai.provider'].create({
            'name': 'Test Provider',
            'provider_type': 'openai',
            'base_url': 'https://api.test.openai/v1',
            'api_key': 'secret-key',
        })
        self.model = self.env['hdai.model'].with_context(
            hdai_capability_probe=True).create({
            'name': 'Test Model',
            'code': 'gpt-4o-mini',
            'provider_id': self.provider.id,
            'supports_reasoning': True,
            'supports_web_search': True,
        })
        self.env['ir.config_parameter'].set_param(
            'hdai.default_model_id', self.model.id)

    def _mock_chat(self, reply='hello reply', usage=None):
        usage = usage or {'prompt_tokens': 5, 'completion_tokens': 3,
                          'total_tokens': 8}
        return patch.object(
            LLMService, 'chat_tools',
            return_value={
                'content': reply,
                'reasoning': '',
                'usage': usage,
                'tool_calls': [],
            })

    def test_create_session_defaults(self):
        settings = self.env['hdai.user.settings']._get_for_user(
            self.env.user)
        settings.write({'streaming': False, 'web_search_enabled': True})
        session = self.env['hdai.session'].create({
            'name': 'Session',
        })
        self.assertEqual(session.streaming, False)
        self.assertEqual(session.web_search_enabled, True)
        self.assertEqual(session.model_id, self.model)

    def test_send_message_stores_reply_and_usage(self):
        session = self.env['hdai.session'].create({'name': 'Session'})
        with self._mock_chat():
            result = session.action_send_message('Hello?')
        self.assertFalse(result['error'])
        self.assertEqual(len(result['messages']), 2)
        assistant = result['messages'][-1]
        self.assertEqual(assistant['role'], 'assistant')
        self.assertEqual(assistant['content'], 'hello reply')
        self.assertEqual(session.output_tokens, 3)

    def test_send_message_no_model(self):
        self.env['ir.config_parameter'].set_param(
            'hdai.default_model_id', '0')
        session = self.env['hdai.session'].create({'name': 'Session'})
        session.write({'model_id': False})
        result = session.action_send_message('Hello?')
        self.assertEqual(result['error']['code'], 'no_model')

    def test_options_clamped_by_capabilities(self):
        self.model.with_context(hdai_capability_probe=True).write({
            'supports_reasoning': False,
            'supports_web_search': False,
            'allow_streaming': False,
        })
        session = self.env['hdai.session'].create({
            'name': 'Session',
            'model_id': self.model.id,
        })
        session.action_set_options({
            'reasoning_strength': 'high',
            'web_search_enabled': True,
            'streaming': True,
        })
        self.assertEqual(session.reasoning_strength, 'none')
        self.assertEqual(session.web_search_enabled, False)
        self.assertEqual(session.streaming, False)

    def test_context_attach_and_clear(self):
        partner = self.env['res.partner'].create({'name': 'Demo Partner'})
        session = self.env['hdai.session'].create({'name': 'Session'})
        result = session.action_attach_context('res.partner', partner.id)
        self.assertTrue(result['attached'])
        self.assertIn('Demo Partner', result['snapshot'])
        session.action_clear_context()
        self.assertTrue(session.attach_context)
        self.assertFalse(session.context_model)
        self.assertFalse(session.context_res_id)

    def test_parse_tool_payload(self):
        session = self.env['hdai.session']
        payload = session._parse_tool_payload(
            'Here is the view:\n```json\n{"tool": "open_view", '
            '"model": "res.partner", "domain": [], "view_type": "list"}\n```')
        self.assertEqual(payload['model'], 'res.partner')
        self.assertIsNone(session._parse_tool_payload('Just a normal answer'))

    def test_system_prompt_uses_configured_template(self):
        self.env['ir.config_parameter'].set_param(
            'hdai.prompt.chat', 'Be human and actionable.')
        session = self.env['hdai.session'].create({
            'name': 'Prompt Session'})
        self.assertIn('Be human and actionable.', session._system_prompt())

    def test_context_prompt_uses_template(self):
        partner = self.env['res.partner'].create({'name': 'Demo Partner'})
        self.env['ir.config_parameter'].set_param(
            'hdai.prompt.context', 'Record:\n{snapshot}')
        session = self.env['hdai.session'].create({'name': 'Session'})
        session.action_attach_context('res.partner', partner.id)
        prompt = session._context_prompt()
        self.assertIn('Record:', prompt)
        self.assertIn('Demo Partner', prompt)

    def test_tool_message_content_is_split(self):
        session = self.env['hdai.session'].create({'name': 'Session'})
        self.env['hdai.message'].create({
            'session_id': session.id,
            'role': 'assistant',
            'content': (
                'I will open the view.\n'
                '```json\n{"tool": "open_view", "model": "res.partner", '
                '"domain": [], "view_type": "list"}\n```\n'
                'You can inspect the list below.'),
        })
        item = session.action_get_messages()[-1]
        self.assertIn('tool', item)
        self.assertIn('I will open the view.', item['content_before_tool'])
        self.assertIn('You can inspect', item['content_after_tool'])

    def test_send_as_message_requires_context(self):
        session = self.env['hdai.session'].create({'name': 'Session'})
        with self._mock_chat():
            result = session.action_send_message('Hello?')
        assistant_id = result['messages'][-1]['id']
        action = session.action_send_as_message(assistant_id)
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['params']['type'], 'warning')

    def test_send_as_message_with_context_returns_composer(self):
        partner = self.env['res.partner'].create({'name': 'Demo Partner'})
        session = self.env['hdai.session'].create({'name': 'Session'})
        with self._mock_chat():
            result = session.action_send_message('Hello?')
        session.action_attach_context('res.partner', partner.id)
        assistant_id = result['messages'][-1]['id']
        action = session.action_send_as_message(assistant_id)
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'mail.compose.message')
        self.assertEqual(action['views'], [[False, 'form']])
        self.assertEqual(action['context']['default_model'], 'res.partner')
        self.assertEqual(action['context']['default_res_ids'], [partner.id])
        self.assertEqual(action['context']['default_body'], 'hello reply')

    def test_log_as_note_requires_context(self):
        session = self.env['hdai.session'].create({'name': 'Session'})
        with self._mock_chat():
            result = session.action_send_message('Hello?')
        assistant_id = result['messages'][-1]['id']
        action = session.action_log_as_note(assistant_id)
        self.assertEqual(action['type'], 'ir.actions.client')
        self.assertEqual(action['params']['type'], 'warning')

    def test_log_as_note_posts_to_record(self):
        partner = self.env['res.partner'].create({'name': 'Demo Partner'})
        session = self.env['hdai.session'].create({'name': 'Session'})
        with self._mock_chat():
            result = session.action_send_message('Hello?')
        session.action_attach_context('res.partner', partner.id)
        assistant_id = result['messages'][-1]['id']
        action = session.action_log_as_note(assistant_id)
        self.assertEqual(action['params']['type'], 'success')
        from odoo.tools import html2plaintext
        bodies = [
            html2plaintext(m.body)
            for m in partner.message_ids
            if (m.body or '').strip()
        ]
        self.assertTrue(any('hello reply' in body for body in bodies))

    def test_regenerate_drops_later_messages(self):
        session = self.env['hdai.session'].create({'name': 'Session'})
        with self._mock_chat('first'):
            session.action_send_message('Question 1')
        with self._mock_chat('second'):
            session.action_send_message('Question 2')
        assistant = session.message_ids.filtered(
            lambda m: m.role == 'assistant')[:1]
        with self._mock_chat('regenerated'):
            result = session.action_regenerate(assistant.id)
        self.assertEqual(result['messages'][-1]['content'], 'regenerated')
        # Regeneration drops the assistant message and everything after it,
        # so only the first user message remains before the new answer.
        self.assertEqual(len(result['messages']), 2)

    def test_knowledge_document_ids_parsing(self):
        session = self.env['hdai.session'].create({
            'name': 'KB Session',
            'knowledge_document_ids': '[39]',
        })
        self.assertEqual(session._knowledge_document_ids(), [39])
        session.knowledge_document_ids = '39,47'
        self.assertEqual(session._knowledge_document_ids(), [39, 47])
        session.knowledge_document_ids = ''
        self.assertEqual(session._knowledge_document_ids(), [])
