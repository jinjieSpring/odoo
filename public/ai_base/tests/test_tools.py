# -*- coding: utf-8 -*-
from unittest.mock import patch

from odoo.addons.ai_base.models.ai_tool import validate_tool_schema
from odoo.addons.ai_base.tests.common import AiBaseCase


class TestTools(AiBaseCase):
    def test_schema_reject(self):
        schema = {
            'type': 'object',
            'properties': {'model': {'type': 'string'}},
            'required': ['model'],
            'additionalProperties': False,
        }
        ok, errors = validate_tool_schema({}, schema)
        self.assertFalse(ok)
        self.assertTrue(errors)
        ok, errors = validate_tool_schema({'model': 'res.partner', 'x': 1}, schema)
        self.assertFalse(ok)

    def test_search_count_readonly(self):
        self.env['ai.tool']._sync_registry()
        result = self.env['ai.tool'].action_invoke_tool(
            'generic.search_count', {'model': 'res.partner'})
        self.assertEqual(result['status'], 'success')
        self.assertIn('count', result['data'])

    def test_rate_limit(self):
        self.env['ai.tool']._sync_registry()
        tool = self.env['ai.tool'].search(
            [('name', '=', 'generic.search_count')], limit=1)
        tool.rate_limit = 1
        first = self.env['ai.tool'].action_invoke_tool(
            'generic.search_count', {'model': 'res.partner'})
        self.assertEqual(first['status'], 'success')
        second = self.env['ai.tool'].action_invoke_tool(
            'generic.search_count', {'model': 'res.partner'})
        self.assertEqual(second['status'], 'error')
        self.assertEqual(second['code'], 429)

    def test_unregistered_tool_rejected(self):
        result = self.env['ai.tool'].action_invoke_tool(
            'not.a.real.tool', {})
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['code'], 404)

    def test_tool_loop_auto_executes_readonly(self):
        self.env['ai.tool']._sync_registry()
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
                    'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
                }
            return {
                'content': 'there are users',
                'reasoning': '',
                'tool_calls': [],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2},
            }

        with patch(
                'odoo.addons.ai_base.tools.providers.OpenAICompatibleAdapter.chat_completion',
                fake_chat):
            result = self.env['ai.base.service'].agent_run('how many users?')
        self.assertEqual(result['reply'], 'there are users')
        self.assertEqual(calls['n'], 2)
        log = self.env['ai.request.log'].search([
            ('request_type', '=', 'tool'),
            ('tool_name', '=', 'generic.search_count'),
        ], limit=1)
        self.assertTrue(log)

    def test_group_by_readonly(self):
        self.env['ai.tool']._sync_registry()
        country = self.env['res.country'].search([], limit=1)
        self.assertTrue(country)
        partners = self.env['res.partner'].create([
            {'name': 'Group A', 'country_id': country.id},
            {'name': 'Group B', 'country_id': country.id},
        ])
        result = self.env['ai.tool'].action_invoke_tool('generic.group_by', {
            'model': 'res.partner',
            'groupby': 'country_id',
            'aggregates': ['id:count'],
            'domain': [['id', 'in', partners.ids]],
        })
        self.assertEqual(result['status'], 'success')
        self.assertTrue(result['data']['groups'])
        total = sum(
            group.get('id_count', 0) for group in result['data']['groups'])
        self.assertEqual(total, 2)

    def test_group_by_rejects_bad_aggregator(self):
        self.env['ai.tool']._sync_registry()
        result = self.env['ai.tool'].action_invoke_tool('generic.group_by', {
            'model': 'res.partner',
            'groupby': 'country_id',
            'aggregates': ['id:bogus'],
        })
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['code'], 400)

    def test_group_by_rejects_unknown_field(self):
        self.env['ai.tool']._sync_registry()
        result = self.env['ai.tool'].action_invoke_tool('generic.group_by', {
            'model': 'res.partner',
            'groupby': 'not_a_field',
            'aggregates': ['id:count'],
        })
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['code'], 400)
