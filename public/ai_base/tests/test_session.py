# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests import new_test_user
from odoo.addons.ai_base.tests.common import AiBaseCase


class TestSession(AiBaseCase):
    def _chat_ok(self):
        return {
            'content': 'ok',
            'reasoning': '',
            'tool_calls': [],
            'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
        }

    def test_send_persists_messages(self):
        session = self.env['ai.chat.session'].create({'name': 'New Session'})
        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                return_value=self._chat_ok()):
            session.action_send_message('hello there')
        self.assertEqual(session.name, 'hello there'[:30])
        roles = session.message_ids.mapped('role')
        self.assertIn('user', roles)
        self.assertIn('assistant', roles)

    def test_polymorphic_record(self):
        partner = self.env['res.partner'].create({'name': 'Acme'})
        session = self.env['ai.chat.session'].create({
            'name': 'About partner',
            'res_model': 'res.partner',
            'res_id': partner.id,
        })
        self.assertEqual(session.res_name, 'Acme')
        action = session.action_open_related_record()
        self.assertEqual(action['res_model'], 'res.partner')
        self.assertEqual(action['res_id'], partner.id)

    def test_own_session_rule(self):
        session = self.env['ai.chat.session'].create({'name': 'Mine'})
        other = new_test_user(
            self.env, login='ai_other',
            groups='base.group_user,ai_base.group_user')
        found = self.env['ai.chat.session'].with_user(other).search([
            ('id', '=', session.id)])
        self.assertFalse(found)

    def test_assistant_message_stores_usage(self):
        session = self.env['ai.chat.session'].create({'name': 'Logged'})
        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                return_value=self._chat_ok()):
            session.action_send_message('hello there')
        assistant = session.message_ids.filtered(lambda m: m.role == 'assistant')
        self.assertEqual(len(assistant), 1)
        self.assertEqual(assistant.total_tokens, 2)
        self.assertEqual(assistant.status, 'success')
        self.assertTrue(assistant.model_id)

    def test_message_preview_collapses_long_content(self):
        session = self.env['ai.chat.session'].create({'name': 'Preview'})
        long_text = ('hello world ' * 20).strip()
        message = self.env['ai.chat.message'].create({
            'session_id': session.id,
            'role': 'user',
            'content': long_text,
        })
        self.assertEqual(len(message.content_preview), 80)
        self.assertTrue(message.content_preview.endswith('…'))
        self.assertNotIn('\n', message.content_preview)
