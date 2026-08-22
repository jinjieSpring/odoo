# -*- coding: utf-8 -*-
"""Tests for the HD AI res.config.settings integration."""

from odoo.tests import TransactionCase


class TestResConfigSettings(TransactionCase):

    def setUp(self):
        super().setUp()
        self.provider = self.env['hdai.provider'].create({
            'name': 'Settings Provider',
            'provider_type': 'vllm',
            'api_type': 'chat_completions',
            'base_url': 'http://localhost:8000/v1',
        })
        self.model_a = self.env['hdai.model'].create({
            'name': 'Model A',
            'code': 'model-a',
            'provider_id': self.provider.id,
        })
        self.model_b = self.env['hdai.model'].create({
            'name': 'Model B',
            'code': 'model-b',
            'provider_id': self.provider.id,
        })

    def test_provider_onchange_syncs_model(self):
        """Changing the default provider clears/pre-selects the default
        model (error_reference 6.4)."""
        settings = self.env['res.config.settings'].create({
            'hdai_default_provider_id': self.provider.id,
        })
        methods = settings._onchange_methods.get('hdai_default_provider_id')
        self.assertTrue(methods, 'the provider onchange must be registered')
        settings.hdai_default_provider_id = self.provider.id
        for method in methods:
            method(settings)
        self.assertEqual(
            settings.hdai_default_model_id.id, self.model_a.id,
            'the first model of the provider must be pre-selected')
        # The onchange must assign a recordset, not a bare integer: Odoo 19
        # web_read cleanup crashes on int Many2one values
        # ('int' object has no attribute 'origin').
        self.assertIsInstance(
            settings.hdai_default_model_id, type(self.env['hdai.model']))

    def test_provider_cleared_clears_model(self):
        """Clearing the provider clears the default model."""
        settings = self.env['res.config.settings'].create({
            'hdai_default_provider_id': False,
            'hdai_default_model_id': self.model_a.id,
        })
        methods = settings._onchange_methods.get('hdai_default_provider_id')
        settings.hdai_default_provider_id = False
        for method in methods:
            method(settings)
        self.assertFalse(settings.hdai_default_model_id)

    def test_open_provider_action(self):
        """The Configure Provider button returns a form action for the
        selected provider."""
        settings = self.env['res.config.settings'].create({
            'hdai_default_provider_id': self.provider.id,
        })
        action = settings.hdai_action_open_provider()
        self.assertEqual(action['res_model'], 'hdai.provider')
        self.assertEqual(action['res_id'], self.provider.id)

    def test_web_onchange_with_m2o_spec_does_not_crash(self):
        """The web client onchange (full spec with M2O 'fields') must not
        crash when the settings M2O values are empty: get_values returns
        False instead of the integer 0, otherwise web_read produces a
        {'id': 0} row and cleanup fails ('int' object has no attribute
        'origin')."""
        values = self.env['res.config.settings'].get_values()
        # Many2one values must never be the integer 0 (False or a real id).
        def not_zero(value):
            return value is False or (isinstance(value, int) and value > 0)
        self.assertTrue(not_zero(values['hdai_default_provider_id']))
        self.assertTrue(not_zero(values['hdai_default_model_id']))
        for field in ('hdai_route_chat', 'hdai_route_channel',
                      'hdai_route_summary', 'hdai_route_suggest',
                      'hdai_route_embed'):
            self.assertTrue(not_zero(values[field]))
        spec = {
            'hdai_default_provider_id': {'fields': {'display_name': {}}},
            'hdai_default_model_id': {'fields': {'display_name': {}}},
            'hdai_route_chat': {'fields': {'display_name': {}}},
            'hdai_route_channel': {'fields': {'display_name': {}}},
            'hdai_route_summary': {'fields': {'display_name': {}}},
            'hdai_route_suggest': {'fields': {'display_name': {}}},
            'hdai_route_embed': {'fields': {'display_name': {}}},
        }
        result = self.env['res.config.settings'].onchange({}, [], spec)
        for field in spec:
            # The web onchange completes without crashing and returns the
            # fields (the crash was in the internal web_read, not the
            # output format).
            self.assertIn(field, result['value'])
