# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import new_test_user
from odoo.addons.ai_base.tests.common import AiBaseCase


class TestSecurity(AiBaseCase):
    def test_user_cannot_write_prompt(self):
        user = new_test_user(
            self.env, login='ai_plain',
            groups='base.group_user,ai_base.group_user')
        template = self.env['ai.prompt.template'].create({
            'name': 'Core',
            'code': 'core.locked',
            'user_template': 'keep',
        })
        with self.assertRaises(AccessError):
            template.with_user(user).write({'user_template': 'hacked'})

    def test_log_viewer_can_read_audit(self):
        audit = self.env['ai.audit.log']._record(
            'tool_call', tool_name='generic.search_count', status='success')
        viewer = new_test_user(
            self.env, login='ai_logs',
            groups='base.group_user,ai_base.group_log')
        found = self.env['ai.audit.log'].with_user(viewer).search([
            ('id', '=', audit.id)])
        self.assertTrue(found)

    def test_log_viewer_can_read_other_sessions_but_not_write(self):
        session = self.env['ai.chat.session'].create({'name': 'Someone else'})
        viewer = new_test_user(
            self.env, login='ai_session_logs',
            groups='base.group_user,ai_base.group_log')
        found = self.env['ai.chat.session'].with_user(viewer).search([
            ('id', '=', session.id)])
        self.assertTrue(found)
        with self.assertRaises(AccessError):
            found.write({'name': 'Hacked'})
