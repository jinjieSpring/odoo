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

    def test_tool_call_writes_audit_not_request_log(self):
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
        self.assertFalse(self.env['ai.request.log'].search([
            ('request_type', '=', 'tool'),
            ('tool_name', '=', 'generic.search_count'),
        ]))

    def test_unknown_tool_is_audited_as_blocked(self):
        result = self.env['ai.tool'].action_invoke_tool('not.a.real.tool', {})
        self.assertEqual(result['code'], 404)
        audit = self.env['ai.audit.log'].search([
            ('event_type', '=', 'tool_blocked'),
            ('tool_name', '=', 'not.a.real.tool'),
        ], limit=1)
        self.assertTrue(audit)
        self.assertEqual(audit.status, 'blocked')

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

    def test_chat_exception_writes_request_log(self):
        Service = type(self.env['ai.base.service'])
        with patch.object(Service, '_run_tool_loop', side_effect=RuntimeError('boom')):
            try:
                self.env['ai.base.service'].chat('ping')
            except RuntimeError:
                pass
            else:
                self.fail('RuntimeError was not raised')
        log = self.env['ai.request.log'].search([
            ('status', '=', 'error'),
            ('request_type', '=', 'chat'),
        ], limit=1)
        self.assertTrue(log)
        self.assertIn('boom', log.error_message or '')
        self.assertTrue(log.error_traceback)

    def test_agent_run_logs_request_type_agent(self):
        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                return_value=self._ok('done')):
            self.env['ai.base.service'].agent_run('how many users?')
        log = self.env['ai.request.log'].search([
            ('request_type', '=', 'agent'),
            ('scenario_key', '=', 'agent'),
        ], limit=1)
        self.assertTrue(log)
        self.assertEqual(log.status, 'success')

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
            self.env['ai.base.service'].agent_run(
                'how many users?', session=session)
        audit = self.env['ai.audit.log'].search([
            ('event_type', '=', 'tool_call'),
            ('tool_name', '=', 'generic.search_count'),
            ('session_id', '=', session.id),
        ], limit=1)
        self.assertTrue(audit)

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
