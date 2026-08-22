# -*- coding: utf-8 -*-
"""Offline tests for the NL open-view upgrade (P1-G8, design 3.2/3.3):
whitelist enforcement, search blueprint, group/measure validation, the
session-tagged bus closed loop and the read-only open_view tool."""

from unittest.mock import patch

from odoo.tests import TransactionCase

from odoo.addons.hdai_base.models.hdai_tools import ToolError
from odoo.addons.hdai_base.models.llm_service import LLMService


class TestNlview(TransactionCase):

    def setUp(self):
        super().setUp()
        self.env['hdai.tool']._sync_registry()
        self.provider = self.env['hdai.provider'].create({
            'name': 'NL Provider',
            'provider_type': 'openai',
            'base_url': 'https://api.test.nl/v1',
            'api_key': 'sk-nnnnnnnnnnnnnnnn',
        })
        self.model = self.env['hdai.model'].create({
            'name': 'NL Model',
            'code': 'nl-model',
            'provider_id': self.provider.id,
        })

    def test_open_view_action_built(self):
        """Valid whitelisted payloads produce an act_window with the applied
        domain, grouping and measures, and are audited."""
        result = self.env['hdai.nlview.model']._ai_open_view({
            'model': 'res.partner',
            'view_type': 'pivot',
            'domain': [['active', '=', True]],
            'group_by': ['country_id'],
            'measures': ['id'],
            'label': 'Partners by country',
        })
        self.assertEqual(result['status'], 'success')
        action = result['action']
        self.assertEqual(action['type'], 'ir.actions.act_window')
        self.assertEqual(action['res_model'], 'res.partner')
        self.assertEqual(action['view_mode'], 'pivot')
        self.assertEqual(action['domain'], [['active', '=', True]])
        self.assertEqual(action['context']['group_by'], ['country_id'])
        self.assertEqual(action['context']['pivot_measures'], ['id'])
        log = self.env['hdai.action.log'].search(
            [('action', '=', 'open_view')])
        self.assertEqual(len(log), 1)
        self.assertEqual(log.model_name, 'res.partner')

    def test_non_whitelisted_model_rejected(self):
        """Models outside the whitelist are rejected server-side."""
        with self.assertRaises(ToolError) as ctx:
            self.env['hdai.nlview.model']._ai_open_view({
                'model': 'res.country',
            })
        self.assertEqual(ctx.exception.code, 'not_whitelisted')

    def test_dotted_field_chain_rejected(self):
        """Dotted field paths are not allowed in NL view parameters."""
        with self.assertRaises(ToolError) as ctx:
            self.env['hdai.nlview.model']._ai_open_view({
                'model': 'res.partner',
                'domain': [['country_id.name', '=', 'China']],
            })
        self.assertEqual(ctx.exception.code, 'invalid_parameter')

    def test_invalid_group_and_measure_rejected(self):
        with self.assertRaises(ToolError) as ctx:
            self.env['hdai.nlview.model']._ai_open_view({
                'model': 'res.partner',
                'group_by': ['no.such.field'],
            })
        self.assertEqual(ctx.exception.code, 'invalid_parameter')
        with self.assertRaises(ToolError) as ctx:
            self.env['hdai.nlview.model']._ai_open_view({
                'model': 'res.partner',
                'measures': ['name'],
            })
        self.assertEqual(ctx.exception.code, 'invalid_measure')

    def test_bus_event_sent_with_session_tag(self):
        """The open_view execution emits a bus notification tagged with the
        session id so concurrent sessions never apply each other's views."""
        bus_model = self.env['bus.bus']
        session = self.env['hdai.session'].create({'name': 'Bus Session'})
        with patch.object(bus_model.__class__, '_sendone') as sendone:
            self.env['hdai.nlview.model']._ai_open_view(
                {'model': 'res.partner', 'view_type': 'list'},
                context={'session_id': session.id})
        sendone.assert_called_once()
        _target, notification_type, message = sendone.call_args[0]
        self.assertEqual(notification_type, 'hdai_base/nlview')
        self.assertEqual(message['session_id'], session.id)
        self.assertEqual(message['action']['res_model'], 'res.partner')

    def test_search_blueprint_parsed(self):
        blueprint = self.env['hdai.nlview.model']._search_blueprint(
            'res.partner')
        self.assertEqual(blueprint['model'], 'res.partner')
        self.assertIn('name', blueprint['searchable_fields'])
        self.assertIsInstance(blueprint['measures'], list)
        self.assertIsInstance(blueprint['groupbys'], list)

    def test_manifest_only_readable_whitelisted_models(self):
        manifest = self.env['hdai.nlview.model'].action_get_nlview_manifest()
        models = {entry['model'] for entry in manifest}
        self.assertIn('res.partner', models)
        self.assertNotIn('res.country', models)

    def test_loop_emits_open_view_action_event(self):
        """The server-side tool loop auto-executes the read-only open_view
        tool and emits the returned action as a stream event."""
        session = self.env['hdai.session'].create({'name': 'NL Session'})
        first = {
            'content': '',
            'reasoning': '',
            'usage': {'prompt_tokens': 5, 'completion_tokens': 1,
                      'total_tokens': 6},
            'tool_calls': [{
                'id': 'call_nl_1',
                'name': 'open_view',
                'arguments': {
                    'model': 'res.partner',
                    'view_type': 'list',
                    'domain': [['active', '=', True]],
                },
            }],
        }
        second = {
            'content': 'Opened the partners list.',
            'reasoning': '',
            'usage': {'prompt_tokens': 4, 'completion_tokens': 2,
                      'total_tokens': 6},
            'tool_calls': [],
        }
        events = []
        with patch.object(LLMService, 'chat_tools',
                          side_effect=[first, second]):
            result = session._run_tool_loop(
                self.model, session._build_history(),
                emit=lambda event: events.append(event))
        self.assertEqual(result['ended'], 'completed')
        action_events = [
            event for event in events if event['type'] == 'action']
        self.assertEqual(len(action_events), 1)
        action = action_events[0]['action']
        self.assertEqual(action['res_model'], 'res.partner')
        self.assertEqual(action['view_mode'], 'list')
        self.assertEqual(action['domain'], [['active', '=', True]])
