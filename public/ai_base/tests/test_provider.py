# -*- coding: utf-8 -*-
from unittest.mock import Mock, patch

from ..tools import (
    AiError,
    OpenAICompatibleAdapter,
    get_provider,
    normalize_base_url,
    pretty_model_name,
)
from odoo.addons.ai_base.tests.common import AiBaseCase


class TestProvider(AiBaseCase):
    def test_registry_resolves_vendor(self):
        self.assertIsInstance(get_provider(self.provider), OpenAICompatibleAdapter)
        ollama = self.env['ai.provider'].create({
            'name': 'Ollama',
            'provider_type': 'ollama',
        })
        self.assertEqual(get_provider(ollama).__class__.__name__, 'OllamaAdapter')
        qwen = self.env['ai.provider'].create({
            'name': 'Qwen',
            'provider_type': 'qwen',
        })
        self.assertEqual(get_provider(qwen).__class__.__name__, 'QwenAdapter')

    def test_create_fills_type_presets(self):
        cases = {
            'deepseek': 'https://api.deepseek.com/v1',
            'ollama': 'http://localhost:11434',
            'qwen': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            'openai_compat': 'https://api.openai.com/v1',
        }
        for provider_type, endpoint in cases.items():
            provider = self.env['ai.provider'].create({
                'provider_type': provider_type,
            })
            self.assertEqual(provider.endpoint, endpoint)
            self.assertTrue(provider.name)

    def test_base_url_scheme_is_auto_prepended(self):
        provider = self.env['ai.provider'].create({
            'name': 'Local',
            'provider_type': 'custom',
            'endpoint': '127.0.0.1:8080/v1',
        })
        self.assertEqual(provider.endpoint, 'http://127.0.0.1:8080/v1')

    def test_chat_openai_compatible(self):
        payload = {
            'choices': [{'message': {'content': 'Hi there'}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
        }
        client = get_provider(self.provider)
        with patch(
                'odoo.addons.ai_base.tools.providers.http_request',
                return_value=payload) as request_mock:
            result = client.chat(
                self.model, [{'role': 'user', 'content': 'Hello'}])
        self.assertEqual(result['content'], 'Hi there')
        self.assertEqual(result['usage']['total_tokens'], 15)
        url = request_mock.call_args[0][1]
        self.assertTrue(url.endswith('/chat/completions'))

    def test_stream_decodes_utf8(self):
        line = b'data: {"choices":[{"delta":{"content":"\xe4\xb8\xad"}}]}'
        response = Mock()
        response.iter_lines.return_value = [line]
        client = get_provider(self.provider)
        with patch(
                'odoo.addons.ai_base.tools.providers.http_stream',
                return_value=response):
            chunks = list(client.stream_chat(
                self.model, [{'role': 'user', 'content': 'hi'}]))
        self.assertEqual(chunks[0]['content'], '中')

    def test_http_error_on_models_is_actionable(self):
        from ..tools.http import _http_error_message
        message = _http_error_message(
            'http://127.0.0.1:8080/models', 404, 'Not Found')
        self.assertIn('/v1/models', message)

    def test_normalize_base_url(self):
        self.assertEqual(normalize_base_url('127.0.0.1:8080'), 'http://127.0.0.1:8080')
        self.assertEqual(
            normalize_base_url('https://api.example.com/v1'),
            'https://api.example.com/v1')

    def test_missing_key_raises(self):
        cloud = self.env['ai.provider'].create({
            'name': 'Cloud',
            'provider_type': 'openai_compat',
            'endpoint': 'https://api.openai.com/v1',
            'api_key': False,
        })
        model = self.env['ai.model'].create({
            'name': 'No Key',
            'code': 'no-key-model',
            'provider_id': cloud.id,
            'model_name_remote': 'gpt-4o-mini',
        })
        client = get_provider(cloud)
        with self.assertRaises(AiError):
            client.chat(model, [{'role': 'user', 'content': 'hi'}])

    def test_test_connection_creates_listed_models(self):
        payload = {
            'data': [
                {
                    'id': 'qwen2.5-7b',
                    'owned_by': 'vllm',
                    'max_model_len': 32768,
                    'max_tokens': 8192,
                    'root': 'Qwen/Qwen2.5-7B',
                },
                {
                    'id': 'text-embedding-bge',
                    'owned_by': 'vllm',
                    'max_model_len': 8192,
                },
            ]
        }
        with patch(
                'odoo.addons.ai_base.tools.providers.http_request',
                return_value=payload):
            action = self.provider.action_test_connection()
        self.assertEqual(action['params']['type'], 'success')
        chat = self.env['ai.model'].search([
            ('provider_id', '=', self.provider.id),
            ('model_name_remote', '=', 'qwen2.5-7b'),
        ])
        self.assertTrue(chat)
        self.assertEqual(chat.name, 'Qwen2.5 7B')
        self.assertEqual(chat.code, 'qwen2.5-7b')
        self.assertEqual(chat.model_kind, 'chat')
        self.assertEqual(chat.max_context_tokens, 32768)
        self.assertEqual(chat.max_tokens_default, 8192)
        self.assertEqual(chat.vendor_info.get('owned_by'), 'vllm')
        embed = self.env['ai.model'].search([
            ('provider_id', '=', self.provider.id),
            ('model_name_remote', '=', 'text-embedding-bge'),
        ])
        self.assertEqual(embed.model_kind, 'embedding')
        self.assertEqual(embed.name, 'Text Embedding BGE')
        self.assertEqual(embed.code, 'text-embedding-bge')
        self.assertFalse(embed.supports_streaming)

    def test_test_connection_updates_existing_without_duplicate(self):
        payload = {
            'data': [{
                'id': 'gpt-4o-mini',
                'owned_by': 'openai',
                'context_length': 200000,
            }]
        }
        with patch(
                'odoo.addons.ai_base.tools.providers.http_request',
                return_value=payload):
            self.provider.action_test_connection()
        matches = self.env['ai.model'].search([
            ('provider_id', '=', self.provider.id),
            ('model_name_remote', '=', 'gpt-4o-mini'),
        ])
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches.name, 'Test Model')
        self.assertEqual(matches.max_context_tokens, 200000)
        self.assertEqual(matches.vendor_info.get('owned_by'), 'openai')

    def test_test_connection_ollama_tags(self):
        ollama = self.env['ai.provider'].create({
            'name': 'Ollama Local',
            'provider_type': 'ollama',
            'endpoint': 'http://127.0.0.1:11434',
        })

        def fake_request(method, url, **kwargs):
            if url.endswith('/api/tags'):
                return {
                    'models': [{
                        'name': 'llama3:latest',
                        'size': 4661224676,
                        'details': {
                            'family': 'llama',
                            'parameter_size': '8B',
                            'quantization_level': 'Q4_0',
                        },
                    }]
                }
            if url.endswith('/api/show'):
                return {
                    'details': {'family': 'llama'},
                    'model_info': {'llama.context_length': 8192},
                    'parameters': 'temperature 0.8',
                }
            raise AssertionError(url)

        with patch(
                'odoo.addons.ai_base.tools.providers.http_request',
                side_effect=fake_request):
            ollama.action_test_connection()
        model = self.env['ai.model'].search([
            ('provider_id', '=', ollama.id),
            ('model_name_remote', '=', 'llama3:latest'),
        ])
        self.assertTrue(model)
        self.assertEqual(model.name, 'Llama3 (latest)')
        self.assertEqual(model.code, 'llama3:latest')
        self.assertEqual(model.max_context_tokens, 8192)
        self.assertEqual(
            (model.vendor_info.get('details') or {}).get('parameter_size'),
            '8B')

    def test_pretty_model_name(self):
        self.assertEqual(pretty_model_name('qwen2.5-7b'), 'Qwen2.5 7B')
        self.assertEqual(pretty_model_name('gpt-4o-mini'), 'GPT-4o Mini')
        self.assertEqual(pretty_model_name('llama3:latest'), 'Llama3 (latest)')
        self.assertEqual(
            pretty_model_name('Qwen/Qwen2.5-7B'), 'Qwen2.5 7B')
        self.assertEqual(
            pretty_model_name('text-embedding-bge'), 'Text Embedding BGE')
