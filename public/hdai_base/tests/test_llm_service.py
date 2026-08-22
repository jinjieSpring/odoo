# -*- coding: utf-8 -*-
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from odoo.tests import TransactionCase

from odoo.addons.hdai_base.models.llm_service import LLMError, LLMService


class TestLLMService(TransactionCase):
    def setUp(self):
        super().setUp()
        self.provider = self.env['hdai.provider'].create({
            'name': 'Test OpenAI',
            'provider_type': 'openai',
            'base_url': 'https://api.test.openai/v1',
            'api_key': 'test-key',
        })
        self.model = self.env['hdai.model'].create({
            'name': 'Test Model',
            'code': 'gpt-4o-mini',
            'provider_id': self.provider.id,
            'context_length': 128000,
            'max_output_tokens': 100,
        })

    def _mock_json_response(self, payload):
        response = Mock()
        response.status_code = 200
        response.json.return_value = payload
        response.text = json.dumps(payload)
        return response

    def test_chat_openai_compatible(self):
        payload = {
            'choices': [{'message': {'content': 'Hi there'}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5},
        }
        with patch.object(LLMService, '_request',
                          return_value=payload) as request_mock:
            content, reasoning, usage = LLMService.chat(
                self.model, [{'role': 'user', 'content': 'Hello'}])
        self.assertEqual(content, 'Hi there')
        self.assertEqual(reasoning, '')
        self.assertEqual(usage['total_tokens'], 15)
        request_mock.assert_called_once()
        url = request_mock.call_args[0][1]
        self.assertTrue(url.endswith('/chat/completions'))

    def test_chat_tools_parses_native_tool_calls(self):
        """chat_tools normalizes OpenAI-style tool_calls and includes the
        tools definitions in the request payload."""
        payload = {
            'choices': [{
                'message': {
                    'content': '',
                    'tool_calls': [{
                        'id': 'call_abc',
                        'type': 'function',
                        'function': {
                            'name': 'generic.search_count',
                            'arguments': '{"model": "res.partner"}',
                        },
                    }],
                },
            }],
            'usage': {'prompt_tokens': 6, 'completion_tokens': 1},
        }
        tools = [{
            'type': 'function',
            'function': {
                'name': 'generic.search_count',
                'description': 'Count records.',
                'parameters': {
                    'type': 'object',
                    'properties': {'model': {'type': 'string'}},
                    'required': ['model'],
                },
            },
        }]
        with patch.object(LLMService, '_request',
                          return_value=payload) as request_mock:
            result = LLMService.chat_tools(
                self.model,
                [{'role': 'user', 'content': 'How many partners?'}],
                {'tools': tools})
        self.assertEqual(result['content'], '')
        self.assertEqual(len(result['tool_calls']), 1)
        call = result['tool_calls'][0]
        self.assertEqual(call['id'], 'call_abc')
        self.assertEqual(call['name'], 'generic.search_count')
        self.assertEqual(call['arguments'], {'model': 'res.partner'})
        sent_payload = request_mock.call_args[1]['json']
        self.assertEqual(sent_payload['tools'], tools)
        self.assertEqual(sent_payload['tool_choice'], 'auto')

    def test_chat_tools_ollama_tool_calls(self):
        ollama = self.env['hdai.provider'].create({
            'name': 'Tool Ollama',
            'provider_type': 'ollama',
            'base_url': 'http://localhost:11434',
        })
        model = self.env['hdai.model'].create({
            'name': 'Tool Local Model',
            'code': 'llama3.1:8b',
            'provider_id': ollama.id,
        })
        payload = {
            'message': {
                'content': '',
                'tool_calls': [{
                    'function': {
                        'name': 'generic.search_count',
                        'arguments': {'model': 'res.partner'},
                    },
                }],
            },
            'prompt_eval_count': 5,
            'eval_count': 1,
        }
        with patch.object(LLMService, '_request', return_value=payload):
            result = LLMService.chat_tools(
                model, [{'role': 'user', 'content': 'Count?'}])
        self.assertEqual(len(result['tool_calls']), 1)
        self.assertEqual(result['tool_calls'][0]['name'],
                         'generic.search_count')
        self.assertEqual(result['tool_calls'][0]['arguments'],
                         {'model': 'res.partner'})

    def test_chat_ollama_usage_mapping(self):
        ollama = self.env['hdai.provider'].create({
            'name': 'Test Ollama',
            'provider_type': 'ollama',
            'base_url': 'http://localhost:11434',
        })
        model = self.env['hdai.model'].create({
            'name': 'Local Model',
            'code': 'llama3.1:8b',
            'provider_id': ollama.id,
        })
        payload = {
            'message': {'content': 'local answer'},
            'prompt_eval_count': 8,
            'eval_count': 4,
        }
        with patch.object(LLMService, '_request', return_value=payload):
            content, reasoning, usage = LLMService.chat(
                model, [{'role': 'user', 'content': 'Hi'}])
        self.assertEqual(content, 'local answer')
        self.assertEqual(usage['prompt_tokens'], 8)
        self.assertEqual(usage['completion_tokens'], 4)
        self.assertEqual(usage['total_tokens'], 12)

    def test_stream_openai_usage_chunks(self):
        chunks = [
            b'data: {"choices":[{"delta":{"content":"A"}}]}\n',
            b'data: {"choices":[{"delta":{"content":"B"}}]}\n',
            b'data: {"choices":[],"usage":{"prompt_tokens":3,'
            b'"completion_tokens":2,"total_tokens":5}}\n',
            b'data: [DONE]\n',
        ]
        response = Mock()
        response.status_code = 200
        response.iter_lines.return_value = chunks
        with patch.object(LLMService, '_request_stream', return_value=response):
            result = list(LLMService.stream_chat(
                self.model, [{'role': 'user', 'content': 'Hi'}]))
        contents = [c['content'] for c in result if 'content' in c]
        usage = next(c['usage'] for c in result if 'usage' in c)
        self.assertEqual(''.join(contents), 'AB')
        self.assertEqual(usage['total_tokens'], 5)
        response.iter_lines.assert_called_once_with(decode_unicode=False)

    def test_deepseek_responses_usage_is_nested(self):
        deepseek = self.env['hdai.provider'].create({
            'name': 'DeepSeek',
            'provider_type': 'openai',
            'base_url': 'https://api.deepseek.com/v1',
            'api_key': 'ds-key',
        })
        model = self.env['hdai.model'].with_context(
            hdai_capability_probe=True).create({
            'name': 'DeepSeek V4 Flash',
            'code': 'deepseek-v4-flash',
            'provider_id': deepseek.id,
            'supports_web_search': True,
        })
        payload = {
            'output': [
                {'type': 'reasoning',
                 'content': [{'type': 'output_text', 'text': 'think'}]},
                {'type': 'message',
                 'content': [{'type': 'output_text', 'text': 'web answer'}]},
            ],
            'usage': {'input_tokens': 7, 'output_tokens': 3,
                      'total_tokens': 10},
        }
        with patch.object(LLMService, '_request', return_value=payload):
            content, reasoning, usage = LLMService.chat(
                model,
                [{'role': 'user', 'content': 'Latest news?'}],
                {'web_search': True},
            )
        self.assertEqual(content, 'web answer')
        self.assertEqual(reasoning, 'think')
        self.assertEqual(usage['prompt_tokens'], 7)

    def test_llamacpp_props_context_length(self):
        """The llama.cpp /props endpoint provides the context window when
        the OpenAI-compatible /models listing does not."""
        provider = self.env['hdai.provider'].create({
            'name': 'llama.cpp',
            'provider_type': 'llamacpp',
            'base_url': 'http://localhost:8080/v1',
        })

        def fake_request(method, url, **kwargs):
            if url.endswith('/props'):
                return {
                    'default_generation_settings': {'n_ctx': 32768},
                }
            raise LLMError('unexpected url: %s' % url)

        with patch.object(
                LLMService, '_request', side_effect=fake_request):
            value = LLMService._llamacpp_props_context_length(provider)
        self.assertEqual(value, 32768)

    def test_list_models_llamacpp_props_fallback(self):
        """list_models fills the context length from /props for llama.cpp
        when the model entry carries no metadata."""
        provider = self.env['hdai.provider'].create({
            'name': 'llama.cpp',
            'provider_type': 'llamacpp',
            'base_url': 'http://localhost:8080/v1',
        })

        def fake_request(method, url, **kwargs):
            if url.endswith('/models'):
                return {'data': [{'id': 'llama3.1:8b'}]}
            if url.endswith('/props'):
                return {
                    'default_generation_settings': {'n_ctx': 4096},
                }
            raise LLMError('unexpected url: %s' % url)

        with patch.object(
                LLMService, '_request', side_effect=fake_request):
            models = LLMService.list_models(provider)
        self.assertEqual(models[0]['code'], 'llama3.1:8b')
        self.assertEqual(models[0]['context_length'], 4096)

    def test_system_prompt_and_context_injection(self):
        messages = [{'role': 'user', 'content': 'Hello'}]
        result = LLMService._with_system_instruction(
            messages, self.model, {
                'system_prompt': 'You are the assistant.',
                'context_text': 'Current record: Demo (res.partner)',
                'language_mode': 'auto',
            })
        self.assertEqual(result[0]['role'], 'system')
        self.assertIn('You are the assistant.', result[0]['content'])
        self.assertIn('Current record: Demo', result[0]['content'])

    def test_configurable_language_instruction(self):
        messages = [{'role': 'user', 'content': 'Hello'}]
        result = LLMService._with_system_instruction(
            messages, self.model, {
                'language_instruction':
                    'Answer {reasoning} in {language}{same_as}. {hint}',
                'reasoning_strength': 'high',
                'language_mode': 'auto',
            })
        self.assertIn('Answer step by step', result[0]['content'])
        self.assertIn('in English', result[0]['content'])

    def test_http_error_raises_llm_error(self):
        response = Mock()
        response.status_code = 500
        response.text = 'boom'
        with patch.object(LLMService, '_request',
                         side_effect=LLMError('HTTP error 500: boom')):
            with self.assertRaises(LLMError):
                LLMService._request('GET', 'http://x')

    def test_stream_decodes_utf8_without_charset(self):
        """llama.cpp returns text/event-stream without charset; the stream
        must be decoded explicitly as UTF-8 (error_reference 8.22)."""
        payload = json.dumps({
            'choices': [{'delta': {'content': '\u4f60\u597d\uff0c\u4e16\u754c'}}],
        }, ensure_ascii=False)
        raw_lines = [
            ('data: ' + payload).encode('utf-8'),
            b'data: [DONE]',
        ]
        response = Mock()
        response.status_code = 200
        response.iter_lines.return_value = iter(raw_lines)
        with patch.object(LLMService, '_request_stream',
                          return_value=response):
            chunks = list(LLMService._stream_openai_compatible(
                self.model, [{'role': 'user', 'content': 'Hello'}]))
        self.assertEqual(chunks[0]['content'], '\u4f60\u597d\uff0c\u4e16\u754c')
        response.iter_lines.assert_called_once_with(decode_unicode=False)

    def test_request_sets_utf8_encoding(self):
        """JSON replies are decoded as UTF-8 even when the provider omits
        the charset in Content-Type."""
        response = Mock()
        response.status_code = 200
        response.json.return_value = {'ok': True}
        with patch(
                'odoo.addons.hdai_base.models.llm_service.requests.request',
                return_value=response):
            data = LLMService._request(
                'POST', 'https://api.test/v1/chat/completions', json={})
        self.assertEqual(data, {'ok': True})
        self.assertEqual(response.encoding, 'utf-8')

    def test_provider_profile_matching(self):
        """Profiles are matched on provider type and base URL keywords so
        openai_compatible endpoints get provider-specific defaults."""
        cases = [
            ('deepseek', 'https://api.deepseek.com/v1', 'deepseek'),
            ('openai', 'https://api.openai.com/v1', 'openai'),
            ('openai_compatible',
             'https://open.bigmodel.cn/api/paas/v4', 'zhipu'),
            ('openai_compatible',
             'https://api.moonshot.cn/v1', 'moonshot'),
            ('openai_compatible',
             'https://dashscope.aliyuncs.com/compatible-mode/v1',
             'dashscope'),
            ('ollama', 'http://localhost:11434', 'ollama'),
            ('llamacpp', 'http://localhost:8080/v1', 'llamacpp'),
            ('vllm', 'http://localhost:8000/v1', 'vllm'),
        ]
        for provider_type, base_url, expected in cases:
            provider = self.env['hdai.provider'].create({
                'name': 'Profile %s' % expected,
                'provider_type': provider_type,
                'base_url': base_url,
            })
            self.assertEqual(
                LLMService._provider_profile(provider), expected)

    def test_model_code_overrides_cloud_defaults(self):
        """Documented cloud model codes override the provider profile with
        their official context / max-output specs."""
        deepseek = self.env['hdai.provider'].create({
            'name': 'DeepSeek',
            'provider_type': 'deepseek',
            'base_url': 'https://api.deepseek.com/v1',
        })
        openai = self.env['hdai.provider'].create({
            'name': 'OpenAI',
            'provider_type': 'openai',
            'base_url': 'https://api.openai.com/v1',
        })
        zhipu = self.env['hdai.provider'].create({
            'name': 'Zhipu',
            'provider_type': 'openai_compatible',
            'base_url': 'https://open.bigmodel.cn/api/paas/v4',
        })
        moonshot = self.env['hdai.provider'].create({
            'name': 'Moonshot',
            'provider_type': 'openai_compatible',
            'base_url': 'https://api.moonshot.cn/v1',
        })
        dashscope = self.env['hdai.provider'].create({
            'name': 'DashScope',
            'provider_type': 'openai_compatible',
            'base_url': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        })
        cases = [
            (deepseek, 'deepseek-v4-flash', 1000000, 32768),
            (deepseek, 'deepseek-chat', 128000, 8192),
            (openai, 'gpt-5', 400000, 128000),
            (openai, 'gpt-5-mini', 400000, 128000),
            (openai, 'gpt-4.1', 1047576, 32768),
            (openai, 'gpt-4.1-mini', 1047576, 32768),
            (zhipu, 'glm-5.2', 1000000, 128000),
            (zhipu, 'glm-5', 200000, 128000),
            (moonshot, 'kimi-k2-thinking', 256000, 16384),
            (dashscope, 'qwen3-max', 262144, 65536),
            (dashscope, 'qwen-max', 32768, 8192),
        ]
        for provider, code, context, output in cases:
            defaults = LLMService._defaults_for_model(provider, code)
            self.assertEqual(defaults['context_length'], context, code)
            self.assertEqual(
                defaults['max_output_tokens'], output, code)

    def test_base_payload_sampling_parameters(self):
        """Configured sampling parameters reach the payload; parameters the
        provider does not accept (top_k on OpenAI) are never sent."""
        self.model.write({'temperature': 0.4, 'top_p': 0.9, 'top_k': 0})
        payload = LLMService._base_payload(
            self.model, [{'role': 'user', 'content': 'Hi'}], {}, False)
        self.assertEqual(payload['temperature'], 0.4)
        self.assertEqual(payload['top_p'], 0.9)
        self.assertNotIn('top_k', payload)
        # A per-request override wins over the model configuration.
        payload = LLMService._base_payload(
            self.model, [{'role': 'user', 'content': 'Hi'}],
            {'temperature': 0.2}, False)
        self.assertEqual(payload['temperature'], 0.2)

    def test_ollama_payload_sampling_options(self):
        """Ollama receives the sampling parameters and max tokens through
        its native options dict."""
        ollama = self.env['hdai.provider'].create({
            'name': 'Ollama',
            'provider_type': 'ollama',
            'base_url': 'http://localhost:11434',
        })
        model = self.env['hdai.model'].create({
            'name': 'Local Model',
            'code': 'llama3.1:8b',
            'provider_id': ollama.id,
            'max_output_tokens': 256,
            'temperature': 0.5,
            'top_p': 0.8,
            'top_k': 20,
        })
        with patch.object(
                LLMService, '_request',
                return_value={'message': {'content': 'ok'}}) as request_mock:
            LLMService._chat_ollama(
                model, [{'role': 'user', 'content': 'Hi'}])
        sent = request_mock.call_args[1]['json']
        self.assertEqual(sent['options'], {
            'num_predict': 256,
            'temperature': 0.5,
            'top_p': 0.8,
            'top_k': 20,
        })

    def test_sampling_skipped_for_fixed_provider(self):
        """Kimi fixes temperature/top_p: even a configured value is never
        sent to the API."""
        moonshot = self.env['hdai.provider'].create({
            'name': 'Moonshot',
            'provider_type': 'openai_compatible',
            'base_url': 'https://api.moonshot.cn/v1',
        })
        model = self.env['hdai.model'].create({
            'name': 'Kimi K2',
            'code': 'kimi-k2',
            'provider_id': moonshot.id,
            'temperature': 0.5,
            'top_p': 0.7,
        })
        payload = LLMService._base_payload(
            model, [{'role': 'user', 'content': 'Hi'}], {}, False)
        self.assertNotIn('temperature', payload)
        self.assertNotIn('top_p', payload)

    def test_sampling_works_with_snapshots(self):
        """Plain-data snapshots without sampling attributes are handled
        gracefully: no sampling parameters are sent and no attribute error
        is raised."""
        snapshot = SimpleNamespace(
            code='snapshot-model',
            max_output_tokens=64,
            supports_reasoning=False,
            supports_web_search=False,
            supports_streaming=True,
            provider_id=self.provider,
        )
        payload = LLMService._base_payload(
            snapshot, [{'role': 'user', 'content': 'Hi'}], {}, False)
        self.assertNotIn('temperature', payload)
        self.assertNotIn('top_p', payload)
        self.assertNotIn('top_k', payload)
