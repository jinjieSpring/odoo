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
            'content': 'keep',
        })
        with self.assertRaises(AccessError):
            template.with_user(user).write({'content': 'hacked'})

    def test_log_viewer_can_read_logs(self):
        log = self.env['ai.request.log'].sudo().create({
            'request_type': 'chat',
            'user_id': self.env.user.id,
            'status': 'success',
        })
        viewer = new_test_user(
            self.env, login='ai_logs',
            groups='base.group_user,ai_base.group_log')
        found = self.env['ai.request.log'].with_user(viewer).search([
            ('id', '=', log.id)])
        self.assertTrue(found)
