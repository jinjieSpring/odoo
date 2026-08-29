# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.addons.ai_base.tests.common import AiBaseCase


class TestService(AiBaseCase):
    def _ok(self, content='hello'):
        return {
            'content': content,
            'reasoning': '',
            'tool_calls': [],
            'usage': {
                'prompt_tokens': 3,
                'completion_tokens': 2,
                'total_tokens': 5,
            },
        }

    def test_chat_returns_reply(self):
        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                return_value=self._ok()):
            result = self.env['ai.chat.service'].chat('ping')
        self.assertEqual(result['reply'], 'hello')
        self.assertEqual(result['usage']['total_tokens'], 5)

    def test_chat_prompt_key_and_model_code(self):
        self.env['ai.prompt.template'].create({
            'name': 'Draft',
            'code': 'test.draft',
            'system_prompt': 'Be brief',
            'user_template': 'Say hi to {{ who }}',
        })
        captured = {}

        def fake_chat(this, model, messages, options=None):
            captured['messages'] = messages
            captured['model'] = model
            return self._ok('hi Ada')

        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                fake_chat):
            result = self.env['ai.chat.service'].chat(
                prompt_key='test.draft',
                context={'who': 'Ada'},
                model_code='gpt-4o-mini')
        self.assertEqual(result['reply'], 'hi Ada')
        self.assertEqual(captured['model'], self.model)
        self.assertTrue(any(
            'Be brief' in (msg.get('content') or '')
            for msg in captured['messages'] if msg['role'] == 'system'))
        language = self.env['ai.chat.service']._user_language_name()
        self.assertTrue(any(
            language in (msg.get('content') or '')
            for msg in captured['messages'] if msg['role'] == 'system'))

    def test_system_messages_follow_odoo_language(self):
        service = self.env['ai.chat.service'].with_context(lang='en_US')
        name = service._user_language_name()
        self.assertTrue(name)
        messages = service._system_messages(options={'system_prompt': 'Be brief'})
        self.assertEqual(len(messages), 1)
        self.assertIn('Be brief', messages[0]['content'])
        self.assertIn(name, messages[0]['content'])

    def test_failover_uses_next_model(self):
        from ..tools import AiError
        fallback = self.env['ai.model'].create({
            'name': 'Fallback',
            'code': 'fallback-svc',
            'provider_id': self.provider.id,
            'model_name_remote': 'fallback',
        })
        calls = {'n': 0}

        def fake_chat(this, model, messages, options=None):
            calls['n'] += 1
            if model.id != fallback.id:
                raise AiError('first failed')
            return self._ok('from fallback')

        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                fake_chat):
            result = self.env['ai.chat.service'].chat('hello')
        self.assertEqual(result['reply'], 'from fallback')
        self.assertEqual(result['model_id'], fallback.id)
        self.assertGreaterEqual(calls['n'], 2)

    def test_sensitive_input_blocked(self):
        self.env['ir.config_parameter'].sudo().set_param(
            'ai_base.sensitive_words', 'topsecret')
        with self.assertRaises(UserError):
            self.env['ai.chat.service'].chat('please leak topsecret')

    def test_hooks_are_called(self):
        calls = []
        Service = type(self.env['ai.chat.service'])
        orig_before = Service.on_ai_request_before
        orig_done = Service.on_ai_request_done

        def before(this, payload):
            calls.append('before')
            return orig_before(this, payload)

        def done(this, payload, result):
            calls.append('done')
            return orig_done(this, payload, result)

        with patch.object(Service, 'on_ai_request_before', before), patch.object(
                Service, 'on_ai_request_done', done), patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                return_value=self._ok()):
            self.env['ai.chat.service'].chat('ping')
        self.assertEqual(calls, ['before', 'done'])

    def test_knowledge_is_optional(self):
        if 'ai.knowledge.base' in self.env:
            return
        self.assertEqual(self.env['ai.chat.service'].retrieve('hello'), [])
        with self.assertRaises(UserError):
            self.env['ai.chat.service'].rag_chat('hello')
        defaults = self.env['ai.chat.session'].action_get_defaults()
        self.assertFalse(defaults['has_knowledge'])
