# -*- coding: utf-8 -*-
from unittest.mock import Mock, patch

from odoo.addons.ai_base.models.ai_adapter import (
    AiError,
    OpenAICompatibleAdapter,
    get_adapter,
    normalize_base_url,
)
from odoo.addons.ai_base.tests.common import AiBaseCase


class TestAdapter(AiBaseCase):
    def test_registry_resolves_vendor(self):
        self.assertIsInstance(get_adapter(self.adapter), OpenAICompatibleAdapter)
        ollama = self.env['ai.adapter'].create({
            'name': 'Ollama',
            'code': 'ollama_local',
            'adapter_type': 'ollama',
        })
        self.assertEqual(get_adapter(ollama).__class__.__name__, 'OllamaAdapter')
        qwen = self.env['ai.adapter'].create({
            'name': 'Qwen',
            'code': 'qwen_dash',
            'adapter_type': 'qwen',
        })
        self.assertEqual(get_adapter(qwen).__class__.__name__, 'QwenAdapter')

    def test_create_fills_type_presets(self):
        cases = {
            'deepseek': 'https://api.deepseek.com/v1',
            'ollama': 'http://localhost:11434',
            'qwen': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            'openai_compat': 'https://api.openai.com/v1',
        }
        for adapter_type, endpoint in cases.items():
            adapter = self.env['ai.adapter'].create({
                'adapter_type': adapter_type,
                'code': 'preset_%s' % adapter_type,
            })
            self.assertEqual(adapter.endpoint, endpoint)
            self.assertTrue(adapter.name)

    def test_base_url_scheme_is_auto_prepended(self):
        adapter = self.env['ai.adapter'].create({
            'name': 'Local',
            'code': 'local_llama',
            'adapter_type': 'custom',
            'endpoint': '127.0.0.1:8080/v1',
        })
        self.assertEqual(adapter.endpoint, 'http://127.0.0.1:8080/v1')

    def test_chat_openai_compatible(self):
        payload = {
            'choices': [{'message': {'content': 'Hi there'}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
        }
        adapter = get_adapter(self.adapter)
        with patch(
                'odoo.addons.ai_base.models.ai_adapter.http_request',
                return_value=payload) as request_mock:
            result = adapter.chat(
                self.model, [{'role': 'user', 'content': 'Hello'}])
        self.assertEqual(result['content'], 'Hi there')
        self.assertEqual(result['usage']['total_tokens'], 15)
        url = request_mock.call_args[0][1]
        self.assertTrue(url.endswith('/chat/completions'))

    def test_stream_decodes_utf8(self):
        line = b'data: {"choices":[{"delta":{"content":"\xe4\xb8\xad"}}]}'
        response = Mock()
        response.iter_lines.return_value = [line]
        adapter = get_adapter(self.adapter)
        with patch(
                'odoo.addons.ai_base.models.ai_adapter.http_stream',
                return_value=response):
            chunks = list(adapter.stream_chat(
                self.model, [{'role': 'user', 'content': 'hi'}]))
        self.assertEqual(chunks[0]['content'], '中')

    def test_http_error_on_models_is_actionable(self):
        from odoo.addons.ai_base.models.ai_adapter import _http_error_message
        message = _http_error_message(
            'http://127.0.0.1:8080/models', 404, 'Not Found')
        self.assertIn('/v1/models', message)

    def test_normalize_base_url(self):
        self.assertEqual(normalize_base_url('127.0.0.1:8080'), 'http://127.0.0.1:8080')
        self.assertEqual(
            normalize_base_url('https://api.example.com/v1'),
            'https://api.example.com/v1')

    def test_missing_key_raises(self):
        cloud = self.env['ai.adapter'].create({
            'name': 'Cloud',
            'code': 'cloud_no_key',
            'adapter_type': 'openai_compat',
            'endpoint': 'https://api.openai.com/v1',
            'api_key': False,
        })
        model = self.env['ai.model'].create({
            'name': 'No Key',
            'code': 'no-key-model',
            'adapter_id': cloud.id,
            'model_name_remote': 'gpt-4o-mini',
        })
        adapter = get_adapter(cloud)
        with self.assertRaises(AiError):
            adapter.chat(model, [{'role': 'user', 'content': 'hi'}])
