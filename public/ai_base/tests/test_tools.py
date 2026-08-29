# -*- coding: utf-8 -*-
import re
from unittest.mock import patch

from odoo.exceptions import UserError
from ..models.ai_tool import validate_tool_schema
from odoo.addons.ai_base.tests.common import AiBaseCase

_OPENAI_FUNCTION_NAME = re.compile(r'^[a-zA-Z0-9_-]+$')


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
        tool = self.env['ai.tool'].create({
            'name': 'custom.orm.rate_limit',
            'description': 'Rate limit test',
            'tool_type': 'orm',
            'orm_model': 'res.partner',
            'orm_method': 'search',
            'rate_limit': 1,
            'input_schema': {
                'type': 'object',
                'properties': {'model': {'type': 'string'}},
            },
        })
        first = self.env['ai.tool'].action_invoke_tool(
            tool.name, {'model': 'res.partner'})
        self.assertEqual(first['status'], 'success')
        second = self.env['ai.tool'].action_invoke_tool(
            tool.name, {'model': 'res.partner'})
        self.assertEqual(second['status'], 'error')
        self.assertEqual(second['code'], 429)

    def test_unregistered_tool_rejected(self):
        result = self.env['ai.tool'].action_invoke_tool(
            'not.a.real.tool', {})
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['code'], 404)

    def test_function_schemas_match_openai_name_pattern(self):
        """OpenAI rejects tools[0].function.name unless it matches ^[a-zA-Z0-9_-]+$."""
        schemas = self.env['ai.tool']._function_schemas([
            {
                'name': 'generic.search_count',
                'description': 'Count records',
                'input_schema': {'type': 'object', 'properties': {}},
            },
            {
                'name': '查询客户',
                'description': 'Find partners',
                'input_schema': {'type': 'object', 'properties': {}},
            },
        ])
        names = [item['function']['name'] for item in schemas]
        self.assertEqual(len(names), 2)
        for name in names:
            self.assertRegex(name, _OPENAI_FUNCTION_NAME)
        self.assertEqual(names[0], 'generic_search_count')
        self.assertNotEqual(names[1], '查询客户')
        self.assertTrue(names[1])

    def test_display_name_uses_label(self):
        tool = self.env['ai.tool'].create({
            'name': 'search_partners',
            'label': '查询客户',
            'description': '按名称搜索客户',
            'tool_type': 'http',
            'http_url': 'https://example.com',
        })
        self.assertEqual(tool.display_name, '查询客户')
        found = self.env['ai.tool'].name_search('查询客户')
        self.assertIn(tool.id, [row[0] for row in found])

    def test_display_name_falls_back_to_code(self):
        tool = self.env['ai.tool'].create({
            'name': 'search_partners',
            'description': 'Find partners',
            'tool_type': 'http',
            'http_url': 'https://example.com',
        })
        self.assertEqual(tool.display_name, 'search_partners')

    def test_function_schemas_prefix_label(self):
        schemas = self.env['ai.tool']._function_schemas([{
            'name': 'search_partners',
            'label': '查询客户',
            'description': '按名称搜索。',
            'input_schema': {'type': 'object', 'properties': {}},
        }])
        function = schemas[0]['function']
        self.assertEqual(function['name'], 'search_partners')
        self.assertTrue(function['description'].startswith('查询客户'))
        self.assertIn('按名称搜索', function['description'])

    def test_manifest_includes_label(self):
        self.env['ai.tool'].create({
            'name': 'search_partners',
            'label': '查询客户',
            'description': '按名称搜索客户',
            'tool_type': 'http',
            'http_url': 'https://example.com',
        })
        manifest = self.env['ai.tool'].action_get_manifest_for_user()
        item = next(
            row for row in manifest if row['name'] == 'search_partners')
        self.assertEqual(item['label'], '查询客户')

    def test_builtin_label_can_be_edited(self):
        self.env['ai.tool']._sync_registry()
        tool = self.env['ai.tool'].search(
            [('name', '=', 'generic.search_count')], limit=1)
        self.assertTrue(tool.label)
        tool.write({'label': '统计记录'})
        self.assertEqual(tool.label, '统计记录')
        self.assertEqual(tool.display_name, '统计记录')

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
            result = self.env['ai.base.service'].chat('how many users?')
        self.assertEqual(result['reply'], 'there are users')
        self.assertEqual(calls['n'], 2)
        log = self.env['ai.audit.log'].search([
            ('event_type', '=', 'tool_call'),
            ('tool_name', '=', 'generic.search_count'),
        ], limit=1)
        self.assertTrue(log)

    def test_tool_loop_resolves_openai_function_name(self):
        """The model echoes the sanitized name; the loop still runs the internal tool."""
        self.env['ai.tool']._sync_registry()
        calls = {'n': 0}

        def fake_chat(this, model, messages, options=None):
            calls['n'] += 1
            sent = [
                tool['function']['name']
                for tool in (options or {}).get('tools') or []
            ]
            self.assertIn('generic_search_count', sent)
            self.assertNotIn('generic.search_count', sent)
            if calls['n'] == 1:
                return {
                    'content': '',
                    'reasoning': '',
                    'tool_calls': [{
                        'id': '1',
                        'name': 'generic_search_count',
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
            result = self.env['ai.base.service'].chat('how many users?')
        self.assertEqual(result['reply'], 'there are users')
        self.assertEqual(calls['n'], 2)
        log = self.env['ai.audit.log'].search([
            ('event_type', '=', 'tool_call'),
            ('tool_name', '=', 'generic.search_count'),
        ], limit=1)
        self.assertTrue(log)
        card = result['rounds'][0]['cards'][0]
        count_tool = self.env['ai.tool'].search(
            [('name', '=', 'generic.search_count')], limit=1)
        self.assertEqual(card['label'], count_tool.label or count_tool.name)

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

    def test_builtin_tool_cannot_be_deleted(self):
        self.env['ai.tool']._sync_registry()
        tool = self.env['ai.tool'].search(
            [('name', '=', 'generic.search_count')], limit=1)
        self.assertTrue(tool.is_builtin)
        with self.assertRaises(UserError):
            tool.unlink()
        self.assertTrue(tool.exists())
        with self.assertRaises(UserError):
            tool.write({'is_active': False})
        with self.assertRaises(UserError):
            tool.write({'rate_limit': 1})
        self.assertTrue(tool.is_active)

    def test_custom_tool_can_be_deleted(self):
        tool = self.env['ai.tool'].create({
            'name': 'custom.http.ping',
            'description': 'Ping',
            'tool_type': 'http',
            'http_url': 'https://example.com',
        })
        tool.unlink()
        self.assertFalse(tool.exists())

    def test_group_by_rejects_unknown_field(self):
        self.env['ai.tool']._sync_registry()
        result = self.env['ai.tool'].action_invoke_tool('generic.group_by', {
            'model': 'res.partner',
            'groupby': 'not_a_field',
            'aggregates': ['id:count'],
        })
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['code'], 400)
