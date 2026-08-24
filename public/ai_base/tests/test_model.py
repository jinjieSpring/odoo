# -*- coding: utf-8 -*-
from odoo.addons.ai_base.tests.common import AiBaseCase


class TestModel(AiBaseCase):
    def test_scenario_default(self):
        self.assertEqual(
            self.env['ai.model']._get_model_for_scenario('chat'), self.model)
        self.assertEqual(
            self.env['ai.model']._get_model_for_scenario('embed'), self.embed_model)

    def test_get_by_code(self):
        found = self.env['ai.model']._get_by_code('gpt-4o-mini')
        self.assertEqual(found, self.model)

    def test_scenario_failover_order(self):
        second = self.env['ai.model'].create({
            'name': 'Fallback',
            'code': 'fallback-chat',
            'provider_id': self.provider.id,
            'model_name_remote': 'fallback',
        })
        other = self.env['ai.provider'].create({
            'name': 'Other',
            'provider_type': 'openai_compat',
            'endpoint': 'https://api.other/v1',
            'api_key': 'sk-abcdef1234567890',
            'sequence': 20,
        })
        third = self.env['ai.model'].create({
            'name': 'Low',
            'code': 'low-chat',
            'provider_id': other.id,
            'model_name_remote': 'low',
        })
        chain = self.env['ai.model']._get_scenario_models('chat')
        self.assertEqual(chain[0], self.model)
        self.assertIn(second, chain)
        self.assertIn(third, chain)
        self.assertLess(chain.index(self.model), chain.index(third))

    def test_create_fills_code_and_pretty_name(self):
        model = self.env['ai.model'].create({
            'provider_id': self.provider.id,
            'model_name_remote': 'qwen2.5-7b',
        })
        self.assertEqual(model.name, 'Qwen2.5 7B')
        self.assertEqual(model.code, 'qwen2.5-7b')

    def test_code_collision_prefixes_provider(self):
        other = self.env['ai.provider'].create({
            'name': 'Other',
            'provider_type': 'openai_compat',
            'endpoint': 'https://api.other/v1',
            'api_key': 'sk-abcdef1234567890',
        })
        model = self.env['ai.model'].create({
            'provider_id': other.id,
            'model_name_remote': 'gpt-4o-mini',
        })
        self.assertEqual(model.code, '%s-gpt-4o-mini' % other.id)
        self.assertEqual(model.name, 'GPT-4o Mini')

    def test_write_remote_keeps_custom_name(self):
        self.model.write({'model_name_remote': 'gpt-4o'})
        self.assertEqual(self.model.name, 'Test Model')
        self.assertEqual(self.model.code, 'gpt-4o')

    def test_disabled_provider_skips_models(self):
        other = self.env['ai.provider'].create({
            'name': 'Other',
            'provider_type': 'openai_compat',
            'endpoint': 'https://api.other/v1',
            'api_key': 'sk-abcdef1234567890',
            'sequence': 20,
        })
        fallback = self.env['ai.model'].create({
            'provider_id': other.id,
            'model_name_remote': 'fallback-chat',
            'model_kind': 'chat',
        })
        self.provider.is_active = False
        self.assertFalse(self.env['ai.model']._get_by_code('gpt-4o-mini'))
        self.assertEqual(
            self.env['ai.model']._get_model_for_scenario('chat'), fallback)
        chain = self.env['ai.model']._get_scenario_models('chat')
        self.assertNotIn(self.model, chain)
        self.assertIn(fallback, chain)

    def test_disabled_model_skipped_while_provider_stays_on(self):
        self.model.is_active = False
        other = self.env['ai.model'].create({
            'provider_id': self.provider.id,
            'model_name_remote': 'alt-chat',
            'model_kind': 'chat',
        })
        self.assertEqual(
            self.env['ai.model']._get_model_for_scenario('chat'), other)

    def test_allowed_options(self):
        allowed = self.model._allowed_options()
        self.assertTrue(allowed['streaming'])
        self.assertFalse(allowed['thinking'])
        self.model.supports_streaming = False
        self.assertFalse(self.model._allowed_options()['streaming'])
        self.model.supports_thinking = True
        self.assertTrue(self.model._allowed_options()['thinking'])
