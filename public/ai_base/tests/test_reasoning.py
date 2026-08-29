# -*- coding: utf-8 -*-
from unittest.mock import patch

from ..tools import AiError, get_provider
from odoo.addons.ai_base.tests.common import AiBaseCase


def _ok(content='OK', reasoning='', tool_calls=None):
    return {
        'content': content,
        'reasoning': reasoning,
        'tool_calls': tool_calls or [],
        'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
    }


class TestReasoning(AiBaseCase):
    def test_model_test_persists_reasoning_support(self):
        calls = []

        def fake_chat(this, model, messages, options=None):
            calls.append(dict(options or {}))
            if (options or {}).get('thinking_enabled'):
                return _ok(reasoning='step by step')
            return _ok()

        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                fake_chat):
            action = self.model.action_test_connection()
        self.assertEqual(action['params']['type'], 'success')
        self.assertTrue(self.model.supports_thinking)
        self.assertTrue(self.model._allowed_options()['thinking'])
        self.assertTrue(any(call.get('thinking_enabled') for call in calls))
        self.assertIn('thinking', (action['params']['message'] or '').lower())

    def test_model_test_without_reasoning_content(self):
        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                return_value=_ok()):
            self.model.action_test_connection()
        self.assertFalse(self.model.supports_thinking)
        self.assertFalse(self.model._allowed_options()['thinking'])

    def test_model_test_keeps_connection_success_if_reasoning_probe_fails(self):
        calls = {'n': 0}

        def fake_chat(this, model, messages, options=None):
            calls['n'] += 1
            if (options or {}).get('thinking_enabled'):
                raise AiError('thinking not supported')
            return _ok()

        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                fake_chat):
            action = self.model.action_test_connection()
        self.assertGreaterEqual(calls['n'], 2)
        self.assertEqual(action['params']['type'], 'success')
        self.assertFalse(self.model.supports_thinking)

    def test_provider_test_probes_thinking_on_listed_chat_models(self):
        payload = {
            'data': [
                {'id': 'think-probe-chat', 'owned_by': 'vllm'},
                {'id': 'text-embedding-probe-bge'},
            ]
        }

        def fake_chat(this, model, messages, options=None):
            if (options or {}).get('thinking_enabled'):
                return _ok(reasoning='step by step')
            return _ok()

        with patch(
                'odoo.addons.ai_base.tools.providers.http_request',
                return_value=payload), patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                fake_chat):
            action = self.provider.action_test_connection()
        self.assertEqual(action['params']['type'], 'success')
        chat = self.env['ai.model'].search([
            ('provider_id', '=', self.provider.id),
            ('model_name_remote', '=', 'think-probe-chat'),
        ])
        self.assertTrue(chat.supports_thinking)
        embed = self.env['ai.model'].search([
            ('provider_id', '=', self.provider.id),
            ('model_name_remote', '=', 'text-embedding-probe-bge'),
        ])
        self.assertFalse(embed.supports_thinking)
        self.assertIn('thinking', (action['params']['message'] or '').lower())

    def test_provider_test_survives_thinking_probe_error(self):
        payload = {'data': [{'id': 'think-probe-fail'}]}

        def fake_chat(this, model, messages, options=None):
            raise AiError('thinking probe failed')

        with patch(
                'odoo.addons.ai_base.tools.providers.http_request',
                return_value=payload), patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                fake_chat):
            action = self.provider.action_test_connection()
        self.assertEqual(action['params']['type'], 'success')
        chat = self.env['ai.model'].search([
            ('provider_id', '=', self.provider.id),
            ('model_name_remote', '=', 'think-probe-fail'),
        ])
        self.assertTrue(chat)
        self.assertFalse(chat.supports_thinking)

    def test_qwen_payload_keeps_tools_when_thinking(self):
        qwen = self.env['ai.provider'].create({
            'name': 'Qwen',
            'provider_type': 'qwen',
            'endpoint': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
            'api_key': 'sk-abcdef1234567890',
        })
        model = self.env['ai.model'].create({
            'name': 'Qwen Plus Test',
            'code': 'qwen-plus-thinking-test',
            'provider_id': qwen.id,
            'model_name_remote': 'qwen-plus-thinking-test',
            'supports_thinking': True,
        })
        tools = [{
            'type': 'function',
            'function': {
                'name': 'ping',
                'description': 'Health check',
                'parameters': {'type': 'object', 'properties': {}},
            },
        }]
        client = get_provider(qwen)
        on = client._payload(model, [{'role': 'user', 'content': 'hi'}], {
            'thinking_enabled': True,
            'tools': tools,
        })
        self.assertTrue(on.get('enable_thinking'))
        self.assertEqual(on.get('tools'), tools)
        off = client._payload(model, [{'role': 'user', 'content': 'hi'}], {
            'thinking_enabled': False,
        })
        self.assertFalse(off.get('enable_thinking'))

    def test_deepseek_payload_keeps_tools_when_thinking(self):
        deepseek = self.env['ai.provider'].create({
            'name': 'DeepSeek',
            'provider_type': 'deepseek',
            'endpoint': 'https://api.deepseek.com/v1',
            'api_key': 'sk-abcdef1234567890',
        })
        model = self.env['ai.model'].create({
            'name': 'V4 Flash Test',
            'code': 'ds-v4-flash-thinking-test',
            'provider_id': deepseek.id,
            'model_name_remote': 'ds-v4-flash-thinking-test',
            'supports_thinking': True,
        })
        tools = [{
            'type': 'function',
            'function': {
                'name': 'ping',
                'parameters': {'type': 'object', 'properties': {}},
            },
        }]
        client = get_provider(deepseek)
        on = client._payload(model, [{'role': 'user', 'content': 'hi'}], {
            'thinking_enabled': True,
            'tools': tools,
        })
        self.assertEqual(on.get('thinking'), {'type': 'enabled'})
        self.assertEqual(on.get('tools'), tools)
        off = client._payload(model, [{'role': 'user', 'content': 'hi'}], {
            'thinking_enabled': False,
        })
        self.assertEqual(off.get('thinking'), {'type': 'disabled'})

    def test_tool_loop_keeps_tools_after_reasoning(self):
        self.env['ai.tool']._sync_registry()
        captured = []

        def fake_chat(this, model, messages, options=None):
            captured.append({
                'messages': [dict(msg) for msg in messages],
                'options': dict(options or {}),
            })
            if len(captured) == 1:
                return _ok(
                    content='',
                    reasoning='I should count the users',
                    tool_calls=[{
                        'id': 'call_1',
                        'name': 'generic.search_count',
                        'arguments': {'model': 'res.users'},
                    }],
                )
            return _ok(content='there are users')

        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                fake_chat):
            result = self.env['ai.base.service'].agent_run(
                'how many users?',
                options={'thinking_enabled': True},
            )
        self.assertEqual(result['reply'], 'there are users')
        self.assertEqual(len(captured), 2)
        self.assertTrue(captured[0]['options'].get('tools'))
        self.assertTrue(captured[1]['options'].get('tools'))
        self.assertTrue(captured[0]['options'].get('thinking_enabled'))
        self.assertTrue(captured[1]['options'].get('thinking_enabled'))
        assistant = next(
            msg for msg in captured[1]['messages'] if msg.get('role') == 'assistant')
        self.assertEqual(assistant.get('reasoning_content'), 'I should count the users')
        self.assertTrue(assistant.get('tool_calls'))
        tool = next(
            msg for msg in captured[1]['messages'] if msg.get('role') == 'tool')
        self.assertEqual(tool.get('tool_call_id'), 'call_1')
        round_info = result['rounds'][0]
        self.assertEqual(round_info['reasoning'], 'I should count the users')
        self.assertTrue(round_info['cards'])

    def test_session_toggle_is_gated_by_model_capability(self):
        session = self.env['ai.chat.session'].create({
            'name': 'Think',
            'thinking_enabled': True,
        })
        self.assertFalse(session._call_options()['thinking_enabled'])
        self.model.supports_thinking = True
        session.thinking_enabled = True
        self.assertTrue(session._call_options()['thinking_enabled'])

    def test_set_options_saves_thinking_enabled(self):
        self.model.supports_thinking = True
        session = self.env['ai.chat.session'].create({'name': 'Opts'})
        session.action_set_options({'thinking_enabled': True})
        self.assertTrue(session.thinking_enabled)
        payload = session.action_get_session()
        self.assertTrue(payload['session']['thinking_enabled'])
        self.assertTrue(payload['session']['capabilities']['thinking'])

    def test_history_keeps_reasoning_content(self):
        session = self.env['ai.chat.session'].create({'name': 'Hist'})
        self.env['ai.chat.message'].create({
            'session_id': session.id,
            'role': 'assistant',
            'content': 'done',
            'reasoning_content': 'let me think',
        })
        history = session._build_history()
        self.assertEqual(history[-1]['reasoning_content'], 'let me think')
