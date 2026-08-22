# -*- coding: utf-8 -*-
"""Offline tests for model capability probing and the read-only capability
fields (configuration page: capabilities detected / permissions configured).
"""

from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase

from odoo.addons.hdai_base.models.llm_service import LLMService


class TestModelCapabilities(TransactionCase):

    def setUp(self):
        super().setUp()
        self.provider = self.env['hdai.provider'].create({
            'name': 'Capability Provider',
            'provider_type': 'openai',
            'base_url': 'https://api.test/v1',
            'api_key': 'sk-abcdef1234567890',
        })
        self.model = self.env['hdai.model'].create({
            'name': 'Capability Model',
            'code': 'probe-model',
            'provider_id': self.provider.id,
        })

    def _probe_result(self, **overrides):
        result = {
            'ok': True,
            'supports_reasoning': True,
            'supports_web_search': False,
            'supports_streaming': True,
            'context_length': 64000,
            'context_length_detected': True,
            'max_output_tokens': 2048,
            'max_output_tokens_detected': True,
            'latency': 1.2,
            'reasoning_probe': {'supported': True, 'error': ''},
            'web_search_probe': {
                'supported': False,
                'error': 'web search unavailable',
            },
            'streaming_probe': {'supported': True, 'error': ''},
        }
        result.update(overrides)
        return result

    def test_test_connection_fills_capabilities(self):
        """action_test_connection persists the probed capabilities and the
        detected parameters, and never touches the permission fields."""
        with patch.object(
                LLMService, 'probe_model_capabilities',
                return_value=self._probe_result()) as probe_mock:
            action = self.model.action_test_connection()
        probe_mock.assert_called_once_with(self.model)
        self.assertEqual(action['params']['type'], 'success')
        self.assertTrue(self.model.supports_reasoning)
        self.assertFalse(self.model.supports_web_search)
        self.assertTrue(self.model.supports_streaming)
        self.assertEqual(self.model.context_length, 64000)
        self.assertEqual(self.model.max_output_tokens, 2048)
        self.assertTrue(self.model.allow_reasoning)
        self.assertTrue(self.model.allow_streaming)
        # The permission field follows the detected capability: web search
        # is not supported, so the permission is disabled by the write sync.
        self.assertFalse(self.model.allow_web_search)

    def test_test_connection_failure_keeps_values(self):
        with patch.object(
                LLMService, 'probe_model_capabilities',
                return_value={'ok': False, 'error': 'connection refused'}):
            action = self.model.action_test_connection()
        self.assertEqual(action['params']['type'], 'warning')
        self.assertFalse(self.model.supports_reasoning)
        self.assertFalse(self.model.supports_web_search)

    def test_capability_fields_are_programmatic_only(self):
        """Capability values cannot be written or created manually; the
        internal probe flag opens the programmatic path."""
        with self.assertRaises(UserError):
            self.model.write({'supports_reasoning': True})
        with self.assertRaises(UserError):
            self.model.write({'supports_streaming': True})
        with self.assertRaises(UserError):
            self.env['hdai.model'].create({
                'name': 'Manual Create',
                'code': 'manual',
                'provider_id': self.provider.id,
                'supports_reasoning': True,
            })
        with self.assertRaises(UserError):
            self.env['hdai.model'].create({
                'name': 'Manual Create Stream',
                'code': 'manual-stream',
                'provider_id': self.provider.id,
                'supports_streaming': True,
            })
        # Programmatic (internal) writes still work and keep the allow_*
        # permission fields in sync.
        self.model.with_context(hdai_capability_probe=True).write({
            'supports_reasoning': True,
            'supports_web_search': False,
        })
        self.assertTrue(self.model.supports_reasoning)
        self.assertFalse(self.model.supports_web_search)
        self.assertFalse(self.model.allow_web_search)

    def test_allowed_options_gates_capability_and_permission(self):
        self.model.with_context(hdai_capability_probe=True).write({
            'supports_reasoning': True,
            'supports_web_search': True,
            'supports_streaming': True,
        })
        allowed = self.model._allowed_options()
        self.assertTrue(allowed['reasoning'])
        self.assertTrue(allowed['web_search'])
        self.assertTrue(allowed['streaming'])
        self.model.write({'allow_reasoning': False})
        self.assertFalse(self.model._allowed_options()['reasoning'])
        # A missing capability disables the permission automatically.
        self.model.with_context(hdai_capability_probe=True).write({
            'supports_streaming': False,
        })
        self.assertFalse(self.model._allowed_options()['streaming'])
        self.assertFalse(self.model.allow_streaming)

    def test_test_connection_streaming_unsupported_disables_permission(self):
        with patch.object(
                LLMService, 'probe_model_capabilities',
                return_value=self._probe_result(
                    supports_streaming=False,
                    streaming_probe={
                        'supported': False,
                        'error': 'streaming unavailable',
                    })):
            self.model.action_test_connection()
        self.assertFalse(self.model.supports_streaming)
        self.assertFalse(self.model.allow_streaming)

    def test_test_connection_missing_metadata_uses_defaults(self):
        """Without provider metadata the test connection falls back to the
        recommended defaults and notifies the administrator."""
        self.model.write({'context_length': 0, 'max_output_tokens': 0})
        probe = self._probe_result(
            context_length=0,
            max_output_tokens=0,
            context_length_detected=False,
            max_output_tokens_detected=False)
        with patch.object(
                LLMService, 'probe_model_capabilities',
                return_value=probe):
            action = self.model.action_test_connection()
        self.assertEqual(
            self.model.context_length, LLMService.DEFAULT_CONTEXT_LENGTH)
        self.assertEqual(
            self.model.max_output_tokens,
            LLMService.DEFAULT_MAX_OUTPUT_TOKENS)
        message = action['params']['message']
        self.assertIn(
            str(LLMService.DEFAULT_CONTEXT_LENGTH), message)
        self.assertIn(
            str(LLMService.DEFAULT_MAX_OUTPUT_TOKENS), message)

    def test_provider_test_connection_writes_capabilities(self):
        """The provider test connection fills capabilities through the
        internal path (no manual write error)."""
        models_info = [{
            'code': 'probe-model',
            'name': 'Capability Model',
            'context_length': 32000,
            'max_output_tokens': 1024,
            'supports_reasoning': True,
            'supports_web_search': False,
            'supports_streaming': True,
        }]
        with patch.object(LLMService, 'list_models',
                          return_value=models_info):
            self.provider.action_test_provider()
        self.model.invalidate_recordset()
        self.assertTrue(self.model.supports_reasoning)
        self.assertFalse(self.model.supports_web_search)
        self.assertTrue(self.model.supports_streaming)
        self.assertEqual(self.model.context_length, 32000)

    def test_model_create_fills_provider_specific_defaults(self):
        """Creating a model without explicit parameters fills the provider
        profile defaults, overridden by the documented model-code specs;
        explicit values are always preserved."""
        deepseek = self.env['hdai.provider'].create({
            'name': 'DeepSeek',
            'provider_type': 'deepseek',
            'base_url': 'https://api.deepseek.com/v1',
        })
        v4 = self.env['hdai.model'].create({
            'name': 'DeepSeek V4 Flash',
            'code': 'deepseek-v4-flash',
            'provider_id': deepseek.id,
        })
        self.assertEqual(v4.context_length, 1000000)
        self.assertEqual(v4.max_output_tokens, 32768)
        self.assertEqual(v4.temperature, 1.0)
        self.assertEqual(v4.top_p, 1.0)
        self.assertEqual(v4.top_k, 0)
        # Explicit values win over the recommended defaults.
        custom = self.env['hdai.model'].create({
            'name': 'Custom V4',
            'code': 'deepseek-v4-pro',
            'provider_id': deepseek.id,
            'context_length': 50000,
            'temperature': 0.3,
        })
        self.assertEqual(custom.context_length, 50000)
        self.assertEqual(custom.temperature, 0.3)
        self.assertEqual(custom.max_output_tokens, 32768)
        # A DashScope endpoint resolves its own profile (qwen-max 32K/8K).
        dashscope = self.env['hdai.provider'].create({
            'name': 'DashScope',
            'provider_type': 'openai_compatible',
            'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        })
        qwen = self.env['hdai.model'].create({
            'name': 'Qwen Max',
            'code': 'qwen-max',
            'provider_id': dashscope.id,
        })
        self.assertEqual(qwen.context_length, 32768)
        self.assertEqual(qwen.max_output_tokens, 8192)
        self.assertEqual(qwen.temperature, 0.7)
        self.assertEqual(qwen.top_p, 0.8)

    def test_probe_falls_back_to_provider_specific_defaults(self):
        """probe_model_capabilities fills the provider/model-code defaults
        when the API exposes no context / max-output metadata."""
        deepseek = self.env['hdai.provider'].create({
            'name': 'DeepSeek',
            'provider_type': 'deepseek',
            'base_url': 'https://api.deepseek.com/v1',
            'api_key': 'sk-abcdef1234567890',
        })
        model = self.env['hdai.model'].create({
            'name': 'DeepSeek V4 Flash',
            'code': 'deepseek-v4-flash',
            'provider_id': deepseek.id,
            'context_length': 0,
            'max_output_tokens': 0,
        })
        with patch.object(
                LLMService, 'test_connection',
                return_value={'ok': True, 'latency': 0.2}), \
                patch.object(
                    LLMService, 'chat',
                    return_value=('ok', '', {'total_tokens': 1})), \
                patch.object(
                    LLMService, 'stream_chat',
                    return_value=iter([{'content': 'ok'}])), \
                patch.object(
                    LLMService, 'list_models',
                    return_value=[{
                        'code': 'deepseek-v4-flash',
                        'context_length': None,
                        'max_output_tokens': None,
                    }]):
            result = LLMService.probe_model_capabilities(model)
        self.assertTrue(result['ok'])
        self.assertFalse(result['context_length_detected'])
        self.assertFalse(result['max_output_tokens_detected'])
        self.assertEqual(result['context_length'], 1000000)
        self.assertEqual(result['max_output_tokens'], 32768)
