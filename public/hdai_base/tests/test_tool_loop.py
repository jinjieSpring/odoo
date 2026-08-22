# -*- coding: utf-8 -*-
"""Offline tests for the server-side read-only tool loop (P1-G6).

The loop (design 2.3) calls the model repeatedly with the tool manifest:
read-only tool calls are schema-validated and executed as the calling user,
suggestive tools pause the loop with a card, and the round/call limits stop
runaway loops. All LLM interactions are mocked so the tests run offline.
"""

from unittest.mock import patch

from odoo.tests import TransactionCase

from odoo.addons.hdai_base.models.llm_service import LLMService
from odoo.addons.hdai_base.models.hdai_tools import (
    extract_tool_calls,
    validate_tool_schema,
)


class TestToolLoop(TransactionCase):

    def setUp(self):
        super().setUp()
        self.provider = self.env['hdai.provider'].create({
            'name': 'Loop Provider',
            'provider_type': 'openai',
            'base_url': 'https://api.test.openai/v1',
            'api_key': 'loop-key',
        })
        self.model = self.env['hdai.model'].create({
            'name': 'Loop Model',
            'code': 'gpt-4o-mini',
            'provider_id': self.provider.id,
        })
        self.env['ir.config_parameter'].set_param(
            'hdai.default_model_id', self.model.id)
        # Make sure the framework's tool registry records exist so the loop
        # can validate/execute them (registry hook may not have run in the
        # test database).
        self.env['hdai.tool']._sync_registry()

    def _partner(self):
        return self.env['res.partner'].create({
            'name': 'ACME Loop Partner',
            'email': 'loop@example.com',
        })

    def _mock_sequence(self, *results):
        return patch.object(
            LLMService, 'chat_tools', side_effect=list(results))

    def _tool_call(self, name, arguments, call_id='call_1'):
        return {'id': call_id, 'name': name, 'arguments': arguments}

    def _reply(self, content, usage=None):
        usage = usage or {'prompt_tokens': 4, 'completion_tokens': 2,
                          'total_tokens': 6}
        return {'content': content, 'reasoning': '', 'usage': usage,
                'tool_calls': []}

    def test_read_only_tools_executed_and_fed_back(self):
        """A read-only tool call is executed automatically and the loop
        continues with a plain answer on the next round."""
        self._partner()
        session = self.env['hdai.session'].create({'name': 'Loop Session'})
        first = self._reply('', {'prompt_tokens': 10,
                                 'completion_tokens': 1,
                                 'total_tokens': 11})
        first['tool_calls'] = [self._tool_call(
            'generic.search_read', {
                'model': 'res.partner',
                'domain': [['email', '=', 'loop@example.com']],
                'fields': ['id', 'name'],
            })]
        with self._mock_sequence(first, self._reply(
                'Found the ACME Loop Partner.')):
            result = session.action_send_message(
                'Find the partner with email loop@example.com.')
        self.assertFalse(result['error'])
        # The read-only tool was executed and audited.
        log = self.env['hdai.tool.log'].search([
            ('tool_name', '=', 'generic.search_read')])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.status, 'success')
        # Two assistant rounds were persisted; the second carries the reply
        # and the first carries the executed tool card.
        assistants = session.message_ids.filtered(
            lambda m: m.role == 'assistant').sorted(
                lambda m: (m.create_date, m.id))
        self.assertEqual(len(assistants), 2)
        self.assertEqual(len(assistants[0].tool_cards), 1)
        self.assertEqual(assistants[0].tool_cards[0]['status'], 'done')
        self.assertIn('Found the ACME Loop Partner.',
                      assistants[-1].content)
        # Usage was accumulated across both rounds.
        self.assertEqual(session.total_tokens, 17)

    def test_suggestive_tool_pauses_loop(self):
        """A suggestive tool call is never executed automatically: the loop
        pauses with a ready card for user confirmation."""
        partner = self._partner()
        # hdai_assistant (which ships generic.suggest_update) is not
        # installed in the base test database; register a minimal suggestive
        # tool so the loop has something to pause on.
        self.env['hdai.tool'].create({
            'name': 'test.suggest',
            'description': 'Test suggestion tool.',
            'category': 'generic',
            'suggestive': True,
            'input_schema': {
                'type': 'object',
                'properties': {
                    'model': {'type': 'string'},
                    'record_id': {'type': 'integer'},
                },
                'required': ['model', 'record_id'],
                'additionalProperties': False,
            },
        })
        session = self.env['hdai.session'].create({'name': 'Loop Session'})
        first = self._reply('')
        first['tool_calls'] = [self._tool_call(
            'test.suggest', {
                'model': 'res.partner',
                'record_id': partner.id,
            })]
        with self._mock_sequence(first):
            result = session.action_send_message(
                'Mark this partner as VIP.')
        self.assertFalse(result['error'])
        self.assertEqual(result['messages'][-1]['tool_cards'][0]['status'],
                         'ready')
        # Nothing was written and no audit row was created.
        self.assertFalse(self.env['hdai.tool.log'].search([]))

    def test_loop_limit_stops_with_message(self):
        """The configured round limit stops the loop with an explicit end
        message instead of calling tools forever."""
        self.env['ir.config_parameter'].set_param(
            'hdai.max_successive_calls', '2')
        session = self.env['hdai.session'].create({'name': 'Loop Session'})
        call = self._reply('')
        call['tool_calls'] = [self._tool_call(
            'generic.search_count',
            {'model': 'res.partner'})]
        with self._mock_sequence(call, call):
            result = session._run_tool_loop(
                self.model, session._build_history())
        self.assertEqual(result['ended'], 'limit')
        self.assertTrue(result['limit_message'])
        self.assertIn('2', result['reply'])
        self.assertEqual(len(result['rounds']), 2)
        self.assertEqual(
            len(self.env['hdai.tool.log'].search([
                ('tool_name', '=', 'generic.search_count')])), 2)

    def test_end_message_terminates(self):
        """__end_message stops the loop without executing further tools."""
        session = self.env['hdai.session'].create({'name': 'Loop Session'})
        with self._mock_sequence(self._reply(
                'Done. __end_message')):
            result = session.action_send_message('Quick answer please.')
        self.assertFalse(result['error'])
        self.assertEqual(result['messages'][-1]['content'], 'Done.')
        self.assertFalse(self.env['hdai.tool.log'].search([]))

    def test_invalid_schema_is_blocked_and_loop_recovers(self):
        """A tool call with parameters violating the JSON Schema is blocked,
        an error is fed back and the model gets a second round to answer."""
        self._partner()
        session = self.env['hdai.session'].create({'name': 'Loop Session'})
        first = self._reply('')
        first['tool_calls'] = [self._tool_call(
            'generic.search_read',
            {'model': 123})]  # model must be a string
        with self._mock_sequence(first, self._reply(
                'The request was invalid, but here is the answer.')):
            result = session.action_send_message('Search something.')
        self.assertFalse(result['error'])
        cards = result['messages'][-2]['tool_cards']
        self.assertEqual(cards[0]['status'], 'blocked')
        self.assertEqual(cards[0]['error']['code'], 'invalid_schema')
        self.assertFalse(self.env['hdai.tool.log'].search([]))
        self.assertIn('here is the answer', result['messages'][-1]['content'])

    def test_permission_denied_is_blocked(self):
        """A tool the caller is not allowed to use is blocked, not executed."""
        session = self.env['hdai.session'].create({'name': 'Loop Session'})
        tool = self.env['hdai.tool'].search(
            [('name', '=', 'generic.search_count')], limit=1)
        # No user (not even the admin) belongs to this group, so the hard
        # permission check must block the call.
        tool.write({'required_permissions': 'no.such.group'})
        first = self._reply('')
        first['tool_calls'] = [self._tool_call(
            'generic.search_count', {'model': 'res.partner'})]
        with self._mock_sequence(first, self._reply('No access.')):
            result = session.action_send_message('Count partners.')
        self.assertFalse(result['error'])
        cards = result['messages'][-2]['tool_cards']
        self.assertEqual(cards[0]['status'], 'blocked')
        self.assertEqual(cards[0]['error']['code'], 'forbidden')
        self.assertFalse(self.env['hdai.tool.log'].search([]))

    def test_loop_emits_stream_events(self):
        """The loop emits plain-data events (delta, tool_call, usage) so the
        stream controller can replay them without touching ORM."""
        self._partner()
        session = self.env['hdai.session'].create({'name': 'Loop Session'})
        first = self._reply('Checking the database.')
        first['usage'] = {'prompt_tokens': 6, 'completion_tokens': 1,
                          'total_tokens': 7}
        first['tool_calls'] = [self._tool_call(
            'generic.search_count',
            {'model': 'res.partner'})]
        events = []
        with self._mock_sequence(first, self._reply(
                'There is 1 partner.')):
            result = session._run_tool_loop(
                self.model, session._build_history(),
                emit=lambda event: events.append(event))
        self.assertEqual(result['ended'], 'completed')
        event_types = [event['type'] for event in events]
        self.assertIn('delta', event_types)
        self.assertIn('tool_call', event_types)
        self.assertIn('usage', event_types)
        tool_call_events = [
            event for event in events
            if event['type'] == 'tool_call']
        self.assertEqual(tool_call_events[0]['name'],
                         'generic.search_count')
        self.assertEqual(events[-1]['type'], 'usage')
        # Round 1 usage (7) + round 2 usage (6).
        self.assertEqual(events[-1]['usage']['total_tokens'], 13)

    def test_extract_tool_calls_pure_parser(self):
        """The text-protocol parser extracts every fenced tool block."""
        calls = extract_tool_calls(
            'Checking.\n```json\n{"tool": "generic.search_count", '
            '"params": {"model": "res.partner"}}\n```\n'
            '```json\n{"tool": "generic.search_read", '
            '"params": {"model": "res.users"}}\n```')
        self.assertEqual([call['name'] for call in calls],
                         ['generic.search_count', 'generic.search_read'])
        self.assertEqual(calls[0]['arguments'], {'model': 'res.partner'})
        self.assertIsNone(calls[0]['id'])
        self.assertEqual(
            extract_tool_calls('Just a plain answer.'), [])

    def test_validate_tool_schema_pure_function(self):
        schema = {
            'type': 'object',
            'properties': {
                'model': {'type': 'string'},
                'limit': {'type': 'integer', 'minimum': 1, 'maximum': 500},
                'domain': {
                    'type': 'array',
                    'items': {'type': 'array'},
                },
            },
            'required': ['model'],
            'additionalProperties': False,
        }
        ok, errors = validate_tool_schema(
            {'model': 'res.partner', 'limit': 10}, schema)
        self.assertTrue(ok)
        self.assertEqual(errors, [])
        ok, errors = validate_tool_schema(
            {'model': 1, 'limit': 999, 'extra': True}, schema)
        self.assertFalse(ok)
        self.assertTrue(any('must be a string' in error
                            for error in errors))
        self.assertTrue(any('must be <= 500' in error
                            for error in errors))
        self.assertTrue(any('is not allowed here' in error
                            for error in errors))
        ok, errors = validate_tool_schema({}, schema)
        self.assertFalse(ok)
        self.assertTrue(any('is required' in error
                            for error in errors))
