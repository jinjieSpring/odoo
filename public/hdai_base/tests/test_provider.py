# -*- coding: utf-8 -*-
from types import SimpleNamespace
from unittest.mock import patch

import requests

from odoo.tests import TransactionCase

from odoo.addons.hdai_base.models.llm_service import LLMError, LLMService


class TestProvider(TransactionCase):
    def _provider(self, provider_type='openai', base_url='https://api.test/v1'):
        return self.env['hdai.provider'].create({
            'name': 'Test Provider',
            'provider_type': provider_type,
            'base_url': base_url,
        })

    def test_local_provider_never_requires_key(self):
        provider = self._provider('ollama', 'http://localhost:11434')
        self.assertFalse(provider.api_key_required)
        self.assertTrue(provider.api_key_valid)
        provider.invalidate_recordset(['api_key_hint'])
        self.assertIn(
            'no api key required',
            provider.with_context(lang='en_US').api_key_hint.lower())

    def test_openai_key_format_validation(self):
        provider = self._provider('openai', 'https://api.openai.com/v1')
        provider.write({'api_key': 'sk-abcdef1234567890'})
        self.assertTrue(provider.api_key_valid)
        provider.write({'api_key': 'bad-key'})
        self.assertFalse(provider.api_key_valid)
        provider.invalidate_recordset(['api_key_hint'])
        self.assertIn(
            'invalid',
            provider.with_context(lang='en_US').api_key_hint.lower())

    def test_zhipu_key_format_validation(self):
        provider = self._provider('openai', 'https://open.bigmodel.cn/api/paas/v4')
        provider.write({'api_key': 'abc123.def456'})
        self.assertTrue(provider.api_key_valid)
        provider.write({'api_key': 'nodot'})
        self.assertFalse(provider.api_key_valid)

    def test_base_url_scheme_is_auto_prepended(self):
        """A base URL without a scheme is stored with http:// so requests
        never fails with 'No connection adapters were found'."""
        provider = self.env['hdai.provider'].create({
            'name': 'Scheme Provider',
            'provider_type': 'llamacpp',
            'base_url': '127.0.0.1:8080',
        })
        self.assertEqual(provider.base_url, 'http://127.0.0.1:8080')
        provider.write({'base_url': '10.0.0.2:9000'})
        self.assertEqual(provider.base_url, 'http://10.0.0.2:9000')
        # An explicit scheme is left untouched.
        provider.write({'base_url': 'https://api.example.com/v1'})
        self.assertEqual(provider.base_url, 'https://api.example.com/v1')

    def test_llm_service_normalizes_base_url(self):
        provider = self.env['hdai.provider'].create({
            'name': 'Normalized Provider',
            'provider_type': 'llamacpp',
            'base_url': '127.0.0.1:8080',
        })
        self.assertEqual(
            LLMService._base_url(provider), 'http://127.0.0.1:8080')
        snapshot = SimpleNamespace(base_url='127.0.0.1:8080')
        self.assertEqual(
            LLMService._base_url(snapshot), 'http://127.0.0.1:8080')

    def test_connection_error_message_is_actionable(self):
        """A missing scheme or unreachable host produces a precise hint
        instead of the raw requests error text."""
        message = LLMService._request_error_message(
            '127.0.0.1:8080/models',
            requests.exceptions.InvalidSchema(
                'No connection adapters were found for '
                "'127.0.0.1:8080/models'"))
        self.assertIn('http://127.0.0.1:8080/v1', message)
        message = LLMService._request_error_message(
            'http://127.0.0.1:8080/v1/models',
            requests.exceptions.ConnectionError(
                'Connection refused'))
        self.assertIn('running', message)
        with patch.object(
                requests, 'request',
                side_effect=requests.exceptions.ConnectionError(
                    'Connection refused')):
            with self.assertRaises(LLMError) as ctx:
                LLMService._request(
                    'POST', 'http://127.0.0.1:8080/v1/chat/completions')
            self.assertIn('Could not connect', str(ctx.exception))
        # A 404 on /models gets a hint about the /v1 endpoint.
        message = LLMService._http_error_message(
            'http://127.0.0.1:8080/models', 404, 'Not Found')
        self.assertIn('/v1/models', message)

    def test_save_and_return_keeps_settings_selection(self):
        provider = self._provider('openai', 'https://api.openai.com/v1')
        model = self.env['hdai.model'].create({
            'name': 'Key Model',
            'code': 'gpt-4o-mini',
            'provider_id': provider.id,
        })
        action = provider.with_context(
            hdai_return_to_settings=True).action_save_and_return()
        self.assertEqual(action['tag'], 'hdai_open_settings')
        params = self.env['ir.config_parameter'].sudo()
        self.assertEqual(params.get_param('hdai.default_provider_id'),
                         str(provider.id))
        self.assertEqual(params.get_param('hdai.default_model_id'),
                         str(model.id))

    def test_create_fills_type_presets(self):
        """Creating a provider with only a type fills the recommended
        name / Base URL / API protocol for that type."""
        cases = {
            'deepseek': (
                'DeepSeek', 'https://api.deepseek.com/v1', 'responses'),
            'vllm': (
                'vLLM (Local)', 'http://localhost:8000/v1',
                'chat_completions'),
            'ollama': (
                'Ollama (Local)', 'http://localhost:11434',
                'chat_completions'),
            'llamacpp': (
                'llama.cpp (Local)', 'http://localhost:8080/v1',
                'chat_completions'),
            'openai': (
                'OpenAI', 'https://api.openai.com/v1', 'chat_completions'),
            'openai_compatible': (
                'OpenAI Compatible', '', 'chat_completions'),
        }
        for provider_type, (name, base_url, api_type) in cases.items():
            provider = self.env['hdai.provider'].create({
                'provider_type': provider_type,
            })
            self.assertEqual(provider.name, name)
            self.assertEqual(provider.base_url, base_url)
            self.assertEqual(provider.api_type, api_type)

    def test_create_keeps_explicit_values_over_presets(self):
        provider = self.env['hdai.provider'].create({
            'provider_type': 'deepseek',
            'name': 'Custom DeepSeek',
            'base_url': 'https://custom.deepseek.example/v1',
            'api_type': 'chat_completions',
        })
        self.assertEqual(provider.name, 'Custom DeepSeek')
        self.assertEqual(provider.base_url, 'https://custom.deepseek.example/v1')
        self.assertEqual(provider.api_type, 'chat_completions')

    def test_onchange_provider_type_fills_fields(self):
        """Switching the type on the form fills the recommended settings
        while preserving a custom provider name."""
        provider = self.env['hdai.provider'].new({
            'provider_type': 'deepseek',
        })
        provider.provider_type = 'ollama'
        provider._onchange_provider_type()
        self.assertEqual(provider.base_url, 'http://localhost:11434')
        self.assertEqual(provider.api_type, 'chat_completions')
        self.assertEqual(provider.name, 'Ollama (Local)')
        provider.name = 'My Ollama'
        provider.provider_type = 'vllm'
        provider._onchange_provider_type()
        self.assertEqual(provider.name, 'My Ollama')
        self.assertEqual(provider.base_url, 'http://localhost:8000/v1')

    def test_provider_test_missing_metadata_uses_defaults(self):
        """When the provider does not expose context length / max output
        tokens, the test connection fills the provider-specific defaults and
        tells the administrator instead of writing 0."""
        models_info = [{
            'code': 'no-meta',
            'name': 'No Metadata Model',
            'supports_reasoning': False,
            'supports_web_search': False,
        }]
        defaults = LLMService._PROVIDER_DEFAULTS['openai']
        with patch.object(LLMService, 'list_models',
                          return_value=models_info):
            action = self._provider().action_test_provider()
        model = self.env['hdai.model'].search(
            [('code', '=', 'no-meta')], limit=1)
        self.assertTrue(model)
        self.assertEqual(
            model.context_length, defaults['context_length'])
        self.assertEqual(
            model.max_output_tokens, defaults['max_output_tokens'])
        self.assertEqual(action['params']['type'], 'success')

    def test_provider_test_missing_metadata_uses_model_code_defaults(self):
        """A documented cloud model gets its official specs when the API
        returns no metadata (deepseek-v4-flash: 1M context / 32K output)."""
        deepseek = self.env['hdai.provider'].create({
            'name': 'DeepSeek',
            'provider_type': 'deepseek',
            'base_url': 'https://api.deepseek.com/v1',
            'api_key': 'sk-abcdef1234567890',
        })
        models_info = [{
            'code': 'deepseek-v4-flash',
            'name': 'DeepSeek V4 Flash',
            'supports_reasoning': True,
            'supports_web_search': False,
        }]
        with patch.object(LLMService, 'list_models',
                          return_value=models_info):
            deepseek.action_test_provider()
        model = self.env['hdai.model'].search(
            [('code', '=', 'deepseek-v4-flash')], limit=1)
        self.assertEqual(model.context_length, 1000000)
        self.assertEqual(model.max_output_tokens, 32768)
        self.assertEqual(model.temperature, 1.0)
        self.assertEqual(model.top_p, 1.0)
