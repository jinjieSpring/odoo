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
                'odoo.addons.ai_base.models.ai_provider.OpenAICompatibleAdapter.chat_completion',
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

    def test_own_session_rule(self):
        session = self.env['ai.chat.session'].create({'name': 'Mine'})
        other = new_test_user(
            self.env, login='ai_other',
            groups='base.group_user,ai_base.group_user')
        found = self.env['ai.chat.session'].with_user(other).search([
            ('id', '=', session.id)])
        self.assertFalse(found)
