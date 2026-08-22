# -*- coding: utf-8 -*-
from odoo.exceptions import AccessError
from odoo.tests import TransactionCase, new_test_user


class TestSecurity(TransactionCase):
    def setUp(self):
        super().setUp()
        self.admin = self.env.user
        self.user = new_test_user(
            self.env, login='hdai_test_user', groups='base.group_user')
        self.provider = self.env['hdai.provider'].create({
            'name': 'Test Provider',
            'provider_type': 'openai',
            'base_url': 'https://api.test.openai/v1',
            'api_key': 'super-secret',
        })

    def test_api_key_admin_only(self):
        self.assertEqual(
            self.provider.with_user(self.admin).sudo().api_key,
            'super-secret')
        self.assertEqual(self.provider.with_user(self.admin).api_key,
                         'super-secret')
        with self.assertRaises(AccessError):
            self.provider.with_user(self.user).read(['api_key'])

    def test_sessions_isolated_per_user(self):
        session = self.env['hdai.session'].create({
            'name': 'Admin Session',
            'user_id': self.admin.id,
        })
        other = self.env['hdai.session'].with_user(self.user).search(
            [('id', '=', session.id)])
        self.assertFalse(other)

    def test_providers_readable_by_users(self):
        providers = self.env['hdai.provider'].with_user(
            self.user).search([('id', '=', self.provider.id)])
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers.base_url, 'https://api.test.openai/v1')
