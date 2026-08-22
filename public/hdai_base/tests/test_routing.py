# -*- coding: utf-8 -*-
"""Offline tests for unified model routing and capability persistence
(P1-G7, design 2.4)."""

from unittest.mock import patch

from odoo.tests import TransactionCase

from odoo.addons.hdai_base.models.llm_service import LLMError, LLMService


class TestRouting(TransactionCase):

    def setUp(self):
        super().setUp()
        self.provider_a = self.env['hdai.provider'].create({
            'name': 'Routing Provider A',
            'provider_type': 'openai',
            'base_url': 'https://api.test.a/v1',
            'api_key': 'sk-aaaaaaaaaaaaaaaa',
            'priority': 10,
        })
        self.model_a = self.env['hdai.model'].create({
            'name': 'Routing Model A',
            'code': 'model-a',
            'provider_id': self.provider_a.id,
        })
        self.provider_b = self.env['hdai.provider'].create({
            'name': 'Routing Provider B',
            'provider_type': 'openai',
            'base_url': 'https://api.test.b/v1',
            'api_key': 'sk-bbbbbbbbbbbbbbbb',
            'priority': 1,
        })
        self.model_b = self.env['hdai.model'].create({
            'name': 'Routing Model B',
            'code': 'model-b',
            'provider_id': self.provider_b.id,
        })
        self.env['ir.config_parameter'].set_param(
            'hdai.default_model_id', self.model_a.id)

    def test_scenario_routing_resolves_defaults(self):
        """Scenario defaults override the global default; unset scenarios
        fall back to it."""
        self.env['ir.config_parameter'].set_param(
            'hdai.route.summary', str(self.model_b.id))
        model = self.env['hdai.model']
        self.assertEqual(
            model._get_model_for_scenario('summary'), self.model_b)
        self.assertEqual(
            model._get_model_for_scenario('chat'), self.model_a)
        self.assertEqual(
            model._get_model_for_scenario('suggest'), self.model_a)

    def test_scenario_models_failover_order(self):
        """Candidates are ordered scenario default, global default, then
        provider priority (lower first)."""
        self.env['ir.config_parameter'].set_param(
            'hdai.route.summary', str(self.model_a.id))
        candidates = self.env['hdai.model']._get_scenario_models('summary')
        ids = [model.id for model in candidates]
        # No duplicates and both test models present.
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn(self.model_a.id, ids)
        self.assertIn(self.model_b.id, ids)
        # The scenario default leads the chain.
        self.assertEqual(candidates[0], self.model_a)
        # Every other candidate (besides the leading scenario/global
        # defaults) is ordered by provider priority ascending.
        tail = candidates[2:]
        priorities = [model.provider_id.priority for model in tail]
        self.assertEqual(priorities, sorted(priorities))

    def test_provider_test_persists_capabilities(self):
        """action_test_provider stores capability metadata on created and
        existing models."""
        models_info = [{
            'code': 'model-a',
            'name': 'Routing Model A',
            'context_length': 32000,
            'max_output_tokens': 1024,
            'supports_reasoning': True,
            'supports_web_search': False,
        }]
        with patch.object(LLMService, 'list_models',
                          return_value=models_info):
            self.provider_a.action_test_provider()
        self.model_a.invalidate_recordset()
        self.assertTrue(self.model_a.supports_reasoning)
        self.assertFalse(self.model_a.supports_web_search)
        self.assertEqual(self.model_a.context_length, 32000)
        # Capability changes are applied to existing models too.
        updated = [{
            'code': 'model-a',
            'name': 'Routing Model A',
            'context_length': 64000,
            'max_output_tokens': 2048,
            'supports_reasoning': False,
            'supports_web_search': True,
        }]
        with patch.object(LLMService, 'list_models', return_value=updated):
            self.provider_a.action_test_provider()
        self.model_a.invalidate_recordset()
        self.assertFalse(self.model_a.supports_reasoning)
        self.assertTrue(self.model_a.supports_web_search)
        self.assertEqual(self.model_a.context_length, 64000)

    def test_failover_uses_next_candidate(self):
        """When the first model fails, the loop retries with the next
        candidate and records usage against the model that answered."""
        session = self.env['hdai.session'].create({'name': 'Routing Session'})

        def fake_chat_tools(model, history, options=None):
            if model.id == self.model_a.id:
                raise LLMError('provider A unreachable')
            return {
                'content': 'Answered by model B.',
                'reasoning': '',
                'usage': {'prompt_tokens': 6, 'completion_tokens': 3,
                          'total_tokens': 9},
                'tool_calls': [],
            }

        candidates = self.env['hdai.model']._get_scenario_models('chat')
        with patch.object(LLMService, 'chat_tools',
                          side_effect=fake_chat_tools):
            result = session._run_tool_loop(
                self.model_a, session._build_history(),
                candidates=candidates)
        self.assertEqual(result['ended'], 'completed')
        self.assertEqual(result['reply'], 'Answered by model B.')
        self.assertEqual(result['rounds'][0]['model_code'], 'model-b')
        usage = self.env['hdai.usage'].search([
            ('session_id', '=', session.id)])
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage.model_id, self.model_b)
        self.assertEqual(usage.total_tokens, 9)

    def test_usage_recorded_for_chat_rounds(self):
        """Every loop round with token usage writes an hdai.usage row."""
        session = self.env['hdai.session'].create({'name': 'Usage Session'})
        with patch.object(
                LLMService, 'chat_tools',
                return_value={
                    'content': 'Plain answer.',
                    'reasoning': '',
                    'usage': {'prompt_tokens': 4, 'completion_tokens': 2,
                              'total_tokens': 6},
                    'tool_calls': [],
                }):
            result = session.action_send_message('Hello?')
        self.assertFalse(result['error'])
        usage = self.env['hdai.usage'].search([
            ('session_id', '=', session.id)])
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage.request_type, 'chat')
        self.assertEqual(usage.model_id, self.model_a)
        self.assertEqual(usage.provider_id, self.provider_a)
        self.assertEqual(usage.total_tokens, 6)
