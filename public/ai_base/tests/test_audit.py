# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import new_test_user
from odoo.addons.ai_base.tests.common import AiBaseCase


class TestAuditLog(AiBaseCase):
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

    def test_tool_call_writes_audit(self):
        self.env['ai.tool']._sync_registry()
        result = self.env['ai.tool'].action_invoke_tool(
            'generic.search_count', {'model': 'res.partner'})
        self.assertEqual(result['status'], 'success')
        audit = self.env['ai.audit.log'].search([
            ('event_type', '=', 'tool_call'),
            ('tool_name', '=', 'generic.search_count'),
        ], limit=1)
        self.assertTrue(audit)
        self.assertEqual(audit.status, 'success')
        self.assertEqual(audit.source, 'user')
        self.assertEqual(audit.res_model, 'res.partner')
        self.assertEqual(audit.tool_id.name, 'generic.search_count')
        self.assertFalse(audit.block_reason)

    def test_unknown_tool_is_audited_as_blocked(self):
        result = self.env['ai.tool'].action_invoke_tool('not.a.real.tool', {})
        self.assertEqual(result['code'], 404)
        audit = self.env['ai.audit.log'].search([
            ('event_type', '=', 'tool_blocked'),
            ('tool_name', '=', 'not.a.real.tool'),
        ], limit=1)
        self.assertTrue(audit)
        self.assertEqual(audit.status, 'blocked')
        self.assertEqual(audit.block_reason, 'unknown_tool')
        self.assertEqual(audit.source, 'user')

    def test_audit_log_is_append_only(self):
        audit = self.env['ai.audit.log']._record(
            'tool_call', tool_name='generic.search_count', status='success')
        manager = new_test_user(
            self.env, login='ai_audit_mgr',
            groups='base.group_user,ai_base.group_manager')
        with self.assertRaises(AccessError):
            audit.with_user(manager).write({'output_summary': 'hacked'})
        with self.assertRaises(AccessError):
            audit.with_user(manager).unlink()
        with self.assertRaises(UserError):
            audit.write({'output_summary': 'hacked'})
        with self.assertRaises(UserError):
            audit.unlink()
        self.assertTrue(audit.exists())
        self.assertFalse(audit.output_summary)

    def test_log_viewer_can_read_audit(self):
        audit = self.env['ai.audit.log']._record(
            'tool_call', tool_name='generic.search_count', status='success')
        viewer = new_test_user(
            self.env, login='ai_audit_view',
            groups='base.group_user,ai_base.group_log')
        found = self.env['ai.audit.log'].with_user(viewer).search([
            ('id', '=', audit.id)])
        self.assertTrue(found)

    def test_chat_exception_writes_assistant_error(self):
        session = self.env['ai.chat.session'].create({'name': 'Boom'})
        Service = type(self.env['ai.chat.service'])
        with patch.object(Service, '_run_tool_loop', side_effect=RuntimeError('boom')):
            try:
                self.env['ai.chat.service'].chat('ping', session=session)
            except RuntimeError:
                pass
            else:
                self.fail('RuntimeError was not raised')
        error_msg = session.message_ids.filtered(lambda m: m.status == 'error')
        self.assertTrue(error_msg)
        self.assertIn('boom', error_msg.error_message or '')

    def test_tool_loop_audit_includes_session(self):
        self.env['ai.tool']._sync_registry()
        session = self.env['ai.chat.session'].create({'name': 'Tools'})
        calls = {'n': 0}

        def fake_chat(this, model, messages, options=None):
            calls['n'] += 1
            if calls['n'] == 1:
                return {
                    'content': '',
                    'reasoning': '',
                    'tool_calls': [{
                        'id': '1',
                        'name': 'generic.search_count',
                        'arguments': {'model': 'res.users'},
                    }],
                    'usage': {
                        'prompt_tokens': 1,
                        'completion_tokens': 1,
                        'total_tokens': 2,
                    },
                }
            return {
                'content': 'there are users',
                'reasoning': '',
                'tool_calls': [],
                'usage': {
                    'prompt_tokens': 1,
                    'completion_tokens': 1,
                    'total_tokens': 2,
                },
            }

        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                fake_chat):
            self.env['ai.chat.service'].chat(
                'how many users?', session=session)
        audit = self.env['ai.audit.log'].search([
            ('event_type', '=', 'tool_call'),
            ('tool_name', '=', 'generic.search_count'),
            ('session_id', '=', session.id),
        ], limit=1)
        self.assertTrue(audit)
        self.assertEqual(audit.source, 'llm')
        self.assertEqual(audit.res_model, 'res.users')
        assistant = session.message_ids.filtered(lambda m: m.role == 'assistant')
        self.assertTrue(assistant)
        self.assertIn(audit.message_id, assistant)

    def test_sensitive_input_writes_policy_audit(self):
        session = self.env['ai.chat.session'].create({'name': 'Guard'})
        self.env['ir.config_parameter'].sudo().set_param(
            'ai_base.sensitive_words', 'topsecret')
        try:
            self.env['ai.chat.service'].chat(
                'please leak topsecret', session=session)
        except UserError:
            pass
        else:
            self.fail('UserError was not raised')
        audit = self.env['ai.audit.log'].search([
            ('event_type', '=', 'policy_blocked'),
            ('session_id', '=', session.id),
        ], limit=1)
        self.assertTrue(audit)
        self.assertEqual(audit.block_reason, 'sensitive')
        self.assertEqual(audit.status, 'blocked')
        self.assertEqual(audit.source, 'user')

    def test_chat_rate_limit_writes_policy_audit(self):
        session = self.env['ai.chat.session'].create({'name': 'Limited'})
        self.env['ir.config_parameter'].sudo().set_param(
            'ai_base.rate_limit_user_per_minute', '1')
        self.env['ai.chat.message'].create({
            'session_id': session.id,
            'role': 'assistant',
            'content': 'prior',
            'model_id': self.model.id,
        })
        try:
            self.env['ai.chat.service'].chat('ping', session=session)
        except UserError:
            pass
        else:
            self.fail('UserError was not raised')
        audit = self.env['ai.audit.log'].search([
            ('event_type', '=', 'policy_blocked'),
            ('block_reason', '=', 'chat_limit'),
            ('session_id', '=', session.id),
        ], limit=1)
        self.assertTrue(audit)
        self.assertEqual(audit.status, 'blocked')

    def test_open_audit_logs_filters_current_session(self):
        session = self.env['ai.chat.session'].create({'name': 'Audited'})
        self.env['ai.audit.log']._record(
            'tool_call',
            tool_name='generic.search_count',
            session_id=session.id,
            status='success',
        )
        action = session.action_open_audit_logs()
        self.assertEqual(action['res_model'], 'ai.audit.log')
        self.assertEqual(action['domain'], [('session_id', '=', session.id)])
        self.assertGreaterEqual(session.audit_count, 1)
