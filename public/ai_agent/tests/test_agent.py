# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.tests import new_test_user
from odoo.addons.ai_base.tests.common import AiBaseCase


class TestAgent(AiBaseCase):
    def setUp(self):
        super().setUp()
        self.env['ai.tool']._sync_registry()
        self.chat_agent = self.env['ai.agent'].search(
            [('is_default', '=', True)], limit=1)
        if not self.chat_agent:
            self.chat_agent = self.env['ai.agent'].create({
                'name': 'Assistant',
                'run_mode': 'chat',
                'is_default': True,
                'memory_enabled': False,
            })
        self.chat_agent.memory_enabled = False
        self.goal_agent = self.env['ai.agent'].create({
            'name': 'Closer',
            'run_mode': 'goal',
            'system_prompt': 'You close the month-end.',
            'memory_enabled': False,
            'max_rounds': 4,
        })

    def _ok(self, content='done', tool_calls=None):
        return {
            'content': content,
            'reasoning': '',
            'tool_calls': tool_calls or [],
            'usage': {
                'prompt_tokens': 3,
                'completion_tokens': 2,
                'total_tokens': 5,
            },
        }

    def test_defaults_expose_default_agent_only(self):
        defaults = self.env['ai.chat.session'].action_get_defaults()
        names = {item['name'] for item in defaults['agents']}
        self.assertIn(self.chat_agent.name, names)
        self.assertNotIn('Closer', names)
        self.assertEqual(defaults['default_agent_id'], self.chat_agent.id)

    def test_new_session_gets_default_agent(self):
        session = self.env['ai.chat.session'].create({'name': 'S'})
        self.assertEqual(session.agent_id, self.chat_agent)

    def test_dedicated_entry_binds_agent(self):
        session = self.env['ai.chat.session'].create({
            'name': 'HR',
            'agent_id': self.goal_agent.id,
        })
        self.assertEqual(session.agent_id, self.goal_agent)
        self.env['ai.chat'].set_options(session, {
            'agent_id': self.chat_agent.id,
        })
        self.assertEqual(session.agent_id, self.goal_agent)

    def test_tool_manifest_filtered_by_agent(self):
        count_tool = self.env['ai.tool'].search(
            [('name', '=', 'generic.search_count')], limit=1)
        read_tool = self.env['ai.tool'].search(
            [('name', '=', 'generic.search_read')], limit=1)
        self.assertTrue(count_tool and read_tool)
        self.chat_agent.tool_ids = count_tool
        session = self.env['ai.chat.session'].create({'name': 'Filtered'})
        names = [
            item['name']
            for item in self.env['ai.tool'].action_get_manifest_for_user(
                session=session)
        ]
        self.assertEqual(names, ['generic.search_count'])
        self.chat_agent.tool_ids = self.env['ai.tool']
        names = [
            item['name']
            for item in self.env['ai.tool'].action_get_manifest_for_user(
                session=session)
        ]
        self.assertIn('generic.search_read', names)

    def test_system_messages_include_agent_prompt(self):
        session = self.env['ai.chat.session'].create({
            'name': 'Persona',
            'agent_id': self.goal_agent.id,
        })
        messages = self.env['ai.base.service']._system_messages(
            session, query='hello')
        self.assertTrue(messages)
        self.assertIn('month-end', messages[0]['content'])

    def test_agent_tool_limits_are_per_agent(self):
        self.chat_agent.write({
            'max_rounds': 3,
            'max_tool_calls_per_round': 2,
        })
        self.assertEqual(self.chat_agent._effective_max_rounds(), 3)
        self.assertEqual(self.chat_agent._effective_max_calls_per_round(), 2)
        session = self.env['ai.chat.session'].create({'name': 'Limits'})
        rounds, calls = self.env['ai.base.service']._tool_loop_limits({}, session)
        self.assertEqual((rounds, calls), (3, 2))

    def test_memory_isolated_by_user(self):
        self.chat_agent.memory_enabled = True
        other = new_test_user(self.env, login='agent_other', groups='base.group_user')
        Memory = self.env['ai.agent.memory']
        Memory._remember(self.chat_agent, 'alpha fact')
        Memory.with_user(other)._remember(self.chat_agent, 'beta fact')
        mine = Memory._prompt_text(self.chat_agent)
        theirs = Memory.with_user(other)._prompt_text(self.chat_agent)
        self.assertIn('alpha fact', mine)
        self.assertNotIn('beta fact', mine)
        self.assertIn('beta fact', theirs)
        self.assertNotIn('alpha fact', theirs)

    def test_memory_injected_into_system_prompt(self):
        self.chat_agent.memory_enabled = True
        self.env['ai.agent.memory']._remember(self.chat_agent, 'prefers lists')
        session = self.env['ai.chat.session'].create({'name': 'Mem'})
        messages = self.env['ai.base.service']._system_messages(
            session, query='hello')
        self.assertIn('prefers lists', messages[0]['content'])

    def test_chat_mode_still_replies_inline(self):
        session = self.env['ai.chat.session'].create({'name': 'Chat'})
        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                return_value=self._ok('hello there')):
            payload = self.env['ai.chat'].send_message(session, 'hi')
        self.assertTrue(any(
            msg['role'] == 'assistant' and 'hello there' in (msg['content'] or '')
            for msg in payload['messages']))
        self.assertFalse(self.env['ai.agent.run'].search(
            [('session_id', '=', session.id)]))

    def test_goal_run_cron_and_cancel(self):
        session = self.env['ai.chat.session'].create({
            'name': 'Goal',
            'agent_id': self.goal_agent.id,
        })
        payload = self.env['ai.chat'].send_message(session, 'close the books')
        self.assertTrue(any(
            'leave this chat' in (msg.get('content') or '').lower()
            for msg in payload['messages'] if msg['role'] == 'assistant'))
        self.assertIn('close the books', payload['messages'][-1]['content'])
        run = self.env['ai.agent.run'].search(
            [('session_id', '=', session.id)], limit=1)
        self.assertEqual(run.state, 'pending')
        self.assertEqual(payload['session']['agent_run']['id'], run.id)
        self.assertEqual(payload['session']['agent_run']['goal'], 'close the books')

        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                return_value=self._ok('books closed')):
            self.env['ai.agent.run']._cron_step_runs()
        run.invalidate_recordset()
        self.assertEqual(run.state, 'done')
        session.invalidate_recordset()
        self.assertTrue(any(
            'books closed' in (msg.content or '')
            for msg in session.message_ids if msg.role == 'assistant'))

        session2 = self.env['ai.chat.session'].create({
            'name': 'Cancel',
            'agent_id': self.goal_agent.id,
        })
        self.env['ai.chat'].send_message(session2, 'long job')
        run2 = self.env['ai.agent.run'].search(
            [('session_id', '=', session2.id)], limit=1)
        session2.action_cancel_agent_run()
        self.assertEqual(run2.state, 'cancelled')
        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                return_value=self._ok('should not run')):
            self.env['ai.agent.run']._cron_step_runs()
        run2.invalidate_recordset()
        self.assertEqual(run2.state, 'cancelled')
        self.assertFalse(any(
            'should not run' in (msg.content or '')
            for msg in session2.message_ids))

    def test_goal_schedules_step_without_running_in_send(self):
        session = self.env['ai.chat.session'].create({
            'name': 'Goal',
            'agent_id': self.goal_agent.id,
        })
        with patch.object(
                type(self.env['ai.agent.run']), '_schedule_step') as schedule:
            self.env['ai.chat'].send_message(session, 'close the books')
            self.assertTrue(schedule.called)
        run = self.env['ai.agent.run'].search(
            [('session_id', '=', session.id)], limit=1)
        self.assertEqual(run.state, 'pending')
        self.assertFalse(any(
            'books closed' in (msg.content or '')
            for msg in session.message_ids if msg.role == 'assistant'))

    def test_goal_enqueues_when_queue_job_is_available(self):
        session = self.env['ai.chat.session'].create({
            'name': 'Goal',
            'agent_id': self.goal_agent.id,
        })
        delayed = []

        class Delayed:
            def _step(self):
                delayed.append(True)

        Run = self.env['ai.agent.run']
        with patch.object(type(Run), '_should_delay', return_value=True), patch.object(
                type(Run), 'with_delay', return_value=Delayed(), create=True):
            self.env['ai.chat'].send_message(session, 'close the books')
        self.assertEqual(delayed, [True])
        run = Run.search([('session_id', '=', session.id)], limit=1)
        self.assertEqual(run.state, 'pending')

    def test_goal_busy_keeps_current_run(self):
        session = self.env['ai.chat.session'].create({
            'name': 'Goal',
            'agent_id': self.goal_agent.id,
        })
        self.env['ai.chat'].send_message(session, 'close the books')
        runs = self.env['ai.agent.run'].search(
            [('session_id', '=', session.id)])
        self.assertEqual(len(runs), 1)
        payload = self.env['ai.chat'].send_message(session, 'another job')
        self.assertEqual(runs.state, 'pending')
        self.assertEqual(len(self.env['ai.agent.run'].search(
            [('session_id', '=', session.id)])), 1)
        self.assertTrue(any(
            'still working' in (msg.get('content') or '').lower()
            for msg in payload['messages'] if msg['role'] == 'assistant'))

    def test_agent_whitelist_blocks_are_audited(self):
        count_tool = self.env['ai.tool'].search(
            [('name', '=', 'generic.search_count')], limit=1)
        self.chat_agent.tool_ids = count_tool
        session = self.env['ai.chat.session'].create({'name': 'Filtered'})
        calls = {'n': 0}

        def fake_chat(this, model, messages, options=None):
            calls['n'] += 1
            if calls['n'] == 1:
                return self._ok('', tool_calls=[{
                    'id': '1',
                    'name': 'generic.search_read',
                    'arguments': {'model': 'res.users'},
                }])
            return self._ok('blocked')

        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                fake_chat):
            self.env['ai.base.service'].chat(
                'read users', session=session)
        audit = self.env['ai.audit.log'].search([
            ('event_type', '=', 'tool_blocked'),
            ('tool_name', '=', 'generic.search_read'),
            ('session_id', '=', session.id),
        ], limit=1)
        self.assertTrue(audit)
        self.assertEqual(audit.status, 'blocked')
        self.assertEqual(audit.agent_id, self.chat_agent)

    def test_goal_start_writes_usage_and_audit(self):
        session = self.env['ai.chat.session'].create({
            'name': 'Goal',
            'agent_id': self.goal_agent.id,
        })
        self.env['ai.chat'].send_message(session, 'close the books')
        run = self.env['ai.agent.run'].search(
            [('session_id', '=', session.id)], limit=1)
        audit = self.env['ai.audit.log'].search([
            ('event_type', '=', 'agent_start'),
            ('session_id', '=', session.id),
        ], limit=1)
        self.assertTrue(audit)
        self.assertEqual(audit.run_id, run)
        self.assertEqual(audit.agent_id, self.goal_agent)
        self.assertIn('close the books', audit.input_summary or '')
        log = self.env['ai.request.log'].search([
            ('request_type', '=', 'agent'),
            ('session_id', '=', session.id),
        ], limit=1)
        self.assertTrue(log)
        self.assertIn('close the books', log.input_summary or '')

    def test_goal_done_and_cancel_are_audited(self):
        session = self.env['ai.chat.session'].create({
            'name': 'Goal',
            'agent_id': self.goal_agent.id,
        })
        self.env['ai.chat'].send_message(session, 'close the books')
        run = self.env['ai.agent.run'].search(
            [('session_id', '=', session.id)], limit=1)
        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                return_value=self._ok('books closed')):
            self.env['ai.agent.run']._cron_step_runs()
        self.assertTrue(self.env['ai.audit.log'].search([
            ('event_type', '=', 'agent_done'),
            ('run_id', '=', run.id),
        ], limit=1))

        session2 = self.env['ai.chat.session'].create({
            'name': 'Cancel',
            'agent_id': self.goal_agent.id,
        })
        self.env['ai.chat'].send_message(session2, 'long job')
        run2 = self.env['ai.agent.run'].search(
            [('session_id', '=', session2.id)], limit=1)
        session2.action_cancel_agent_run()
        cancelled = self.env['ai.audit.log'].search([
            ('event_type', '=', 'agent_cancelled'),
            ('run_id', '=', run2.id),
        ], limit=1)
        self.assertTrue(cancelled)

    def test_memory_write_is_audited(self):
        self.chat_agent.memory_enabled = True
        self.env['ai.agent.memory']._remember(self.chat_agent, 'alpha fact')
        audit = self.env['ai.audit.log'].search([
            ('event_type', '=', 'memory_write'),
            ('agent_id', '=', self.chat_agent.id),
        ], limit=1)
        self.assertTrue(audit)
        self.assertIn('alpha fact', audit.input_summary or '')
