# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests import new_test_user
from odoo.addons.ai_base.tests.common import AiBaseCase


class TestChat(AiBaseCase):
    def _chat_ok(self, content='ok'):
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

    def test_defaults_include_layout_and_knowledge(self):
        defaults = self.env['ai.chat.session'].action_get_defaults()
        self.assertTrue(defaults['model_ready'])
        self.assertEqual(defaults['model_status']['code'], 'ready')
        self.assertIn('sidebar_collapsed', defaults)
        self.assertIn('has_knowledge', defaults)
        self.assertIn('agents', defaults)
        if 'ai.agent' in self.env:
            self.assertTrue(isinstance(defaults['agents'], list))
        else:
            self.assertEqual(defaults['agents'], [])
        settings = self.env['ai.user.settings']._get_for_user()
        self.assertEqual(settings.user_id, self.env.user)
        self.assertEqual(settings.sidebar_width, 260)

    def test_user_settings_roundtrip(self):
        self.env['ai.chat.session'].action_save_user_settings({
            'attach_context': False,
            'sidebar_collapsed': True,
            'sidebar_width': 320,
        })
        settings = self.env['ai.chat.session'].action_get_user_settings()
        self.assertFalse(settings['attach_context'])
        self.assertTrue(settings['sidebar_collapsed'])
        self.assertEqual(settings['sidebar_width'], 320)
        self.assertNotIn('language_mode', settings)

    def test_attach_and_clear_record_context(self):
        partner = self.env['res.partner'].create({'name': 'Acme Context'})
        info = self.env['ai.chat.session'].action_get_record_context(
            'res.partner', partner.id)
        self.assertEqual(info['display_name'], 'Acme Context')
        session = self.env['ai.chat.session'].create({'name': 'Ctx'})
        result = session.action_attach_context('res.partner', partner.id)
        self.assertTrue(result['attached'])
        self.assertEqual(session.context_model, 'res.partner')
        self.assertEqual(session.context_res_id, partner.id)
        self.assertIn('Acme Context', session.context_snapshot)
        session.action_clear_context()
        self.assertFalse(session.context_model)
        self.assertTrue(session.attach_context)

    def test_list_context_snapshot(self):
        info = self.env['ai.chat.session'].action_get_list_context(
            'res.partner', [1, 2], 3)
        self.assertEqual(info['count'], 3)
        self.assertEqual(info['model'], 'res.partner')
        session = self.env['ai.chat.session'].create({'name': 'List'})
        result = session.action_attach_list_context('res.partner', [1, 2], 3)
        self.assertTrue(result['attached'])
        self.assertIn('3', session.context_snapshot)

    def test_edit_and_resend_truncates_later_messages(self):
        session = self.env['ai.chat.session'].create({'name': 'Edit'})
        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                return_value=self._chat_ok('first')):
            session.action_send_message('hello')
        user_msg = session.message_ids.filtered(lambda m: m.role == 'user')
        self.assertEqual(len(user_msg), 1)
        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                return_value=self._chat_ok('second')):
            result = session.action_edit_and_resend(user_msg.id, 'hello again')
        self.assertIn('messages', result)
        self.assertEqual(session.message_ids.filtered(
            lambda m: m.role == 'user').content, 'hello again')
        self.assertEqual(
            session.message_ids.filtered(lambda m: m.role == 'assistant').content,
            'second')

    def test_regenerate_replaces_assistant_reply(self):
        session = self.env['ai.chat.session'].create({'name': 'Regen'})
        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                return_value=self._chat_ok('old')):
            session.action_send_message('ask')
        assistant = session.message_ids.filtered(lambda m: m.role == 'assistant')
        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                return_value=self._chat_ok('new')):
            session.action_regenerate(assistant.id)
        self.assertEqual(
            session.message_ids.filtered(lambda m: m.role == 'assistant').content,
            'new')

    def test_send_as_message_needs_context(self):
        session = self.env['ai.chat.session'].create({'name': 'Mail'})
        message = self.env['ai.chat.message'].create({
            'session_id': session.id,
            'role': 'assistant',
            'content': 'Draft reply',
        })
        action = session.action_send_as_message(message.id)
        self.assertEqual(action['tag'], 'display_notification')
        partner = self.env['res.partner'].create({'name': 'Mail Partner'})
        session.action_attach_context('res.partner', partner.id)
        action = session.action_send_as_message(message.id)
        self.assertEqual(action['res_model'], 'mail.compose.message')
        self.assertIn('<p>Draft reply</p>', action['context']['default_body'])

    def test_log_as_note_posts_safe_html(self):
        partner = self.env['res.partner'].create({'name': 'Note Partner'})
        session = self.env['ai.chat.session'].create({'name': 'Note'})
        message = self.env['ai.chat.message'].create({
            'session_id': session.id,
            'role': 'assistant',
            'content': '**hello**\n\n<script>alert(1)</script>',
        })
        session.action_attach_context('res.partner', partner.id)
        action = session.action_log_as_note(message.id)
        self.assertEqual(action['tag'], 'display_notification')
        note = partner.message_ids[0]
        self.assertIn('<strong>hello</strong>', note.body)
        self.assertNotIn('<script>', note.body)
        self.assertIn('&lt;script&gt;', note.body)

    def test_open_in_discuss_is_stub(self):
        session = self.env['ai.chat.session'].create({'name': 'Discuss'})
        action = session.action_open_in_discuss()
        self.assertEqual(action['tag'], 'display_notification')

    def test_set_options_saves_layout(self):
        session = self.env['ai.chat.session'].create({'name': 'Opts'})
        session.action_set_options({'sidebar_width': 400})
        settings = self.env['ai.user.settings']._get_for_user()
        self.assertEqual(settings.sidebar_width, 400)

    def test_set_options_prompt_updates_user_default(self):
        prompt = self.env['ai.prompt.template'].create({
            'name': 'Default',
            'code': 'test.chat.default.prompt',
            'user_template': 'Hi',
        })
        session = self.env['ai.chat.session'].create({'name': 'Opts'})
        session.action_set_options({'prompt_id': prompt.id})
        settings = self.env['ai.user.settings']._get_for_user()
        self.assertEqual(session.prompt_id, prompt)
        self.assertEqual(settings.default_prompt_id, prompt)
        session.action_set_options({'prompt_id': False})
        self.assertFalse(session.prompt_id)
        self.assertFalse(settings.default_prompt_id)

    def test_get_session_payload_matches_ui(self):
        session = self.env['ai.chat.session'].create({'name': 'Payload'})
        self.env['ai.chat.message'].create({
            'session_id': session.id,
            'role': 'user',
            'content': 'hi',
            'prompt_tokens': 4,
        })
        payload = session.action_get_session()
        self.assertIn('capabilities', payload['session'])
        self.assertEqual(payload['session']['name'], 'Payload')
        self.assertEqual(payload['messages'][0]['content'], 'hi')
        self.assertIn('feedback', payload['messages'][0])

    def test_submit_feedback_on_assistant_message(self):
        session = self.env['ai.chat.session'].create({'name': 'Rate'})
        assistant = self.env['ai.chat.message'].create({
            'session_id': session.id,
            'role': 'assistant',
            'content': 'answer',
        })
        session.action_submit_feedback(assistant.id, 'up')
        self.assertEqual(assistant.feedback, 'up')
        session.action_submit_feedback(assistant.id, 'down')
        self.assertEqual(assistant.feedback, 'down')

    def test_settings_are_per_user(self):
        other = new_test_user(
            self.env, login='ai_chat_other',
            groups='base.group_user,ai_base.group_user')
        self.env['ai.chat.session'].action_save_user_settings({
            'sidebar_collapsed': True,
        })
        other_settings = self.env['ai.user.settings'].with_user(other)._get_for_user(other)
        self.assertFalse(other_settings.sidebar_collapsed)
