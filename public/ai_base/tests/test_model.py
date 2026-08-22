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

    def test_allowed_options(self):
        allowed = self.model._allowed_options()
        self.assertTrue(allowed['streaming'])
        self.model.supports_streaming = False
        self.assertFalse(self.model._allowed_options()['streaming'])
