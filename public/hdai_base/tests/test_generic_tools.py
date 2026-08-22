# -*- coding: utf-8 -*-
"""Offline tests for the generic read-only tools and the tool framework."""

from odoo.tests import TransactionCase


class TestGenericTools(TransactionCase):

    def setUp(self):
        super().setUp()
        self.user = self.env.user
        self.user.sudo().group_ids = [
            (4, self.env.ref('hdai_base.hdai_group_user').id)]
        self.tools = self.env['hdai.generic.tools']
        self.partner = self.env['res.partner'].create({
            'name': 'ACME Test Partner',
            'email': 'acme@example.com',
        })

    def test_search_read(self):
        """search_read returns records, pagination and total_count."""
        result = self.tools._ai_search_read({
            'model': 'res.partner',
            'domain': [['name', 'ilike', 'acme']],
            'fields': ['id', 'name', 'email'],
        })
        self.assertEqual(result['status'], 'success')
        self.assertGreaterEqual(result['data']['total_count'], 1)
        self.assertTrue(any(
            record['name'] == 'ACME Test Partner'
            for record in result['data']['records']))
        self.assertEqual(result['data']['source_type'], 'database')

    def test_search_read_unknown_model(self):
        """An unknown model returns a 404 error."""
        result = self.tools._ai_search_read({'model': 'no.such.model'})
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['code'], 404)

    def test_search_read_bad_domain(self):
        """A malformed domain returns a 400 error."""
        result = self.tools._ai_search_read({
            'model': 'res.partner',
            'domain': [['name']],
        })
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['code'], 400)

    def test_search_count(self):
        """search_count returns the matching count."""
        result = self.tools._ai_search_count({
            'model': 'res.partner',
            'domain': [['email', '=', 'acme@example.com']],
        })
        self.assertEqual(result['status'], 'success')
        self.assertGreaterEqual(result['data']['count'], 1)

    def test_group_by(self):
        """group_by computes aggregates with _read_group."""
        country = self.env['res.country'].search([], limit=1)
        self.assertTrue(country, 'the base data must provide a country')
        partner_b = self.env['res.partner'].create({
            'name': 'Beta Partner',
            'email': 'beta@example.com',
            'country_id': country.id,
        })
        result = self.tools._ai_group_by({
            'model': 'res.partner',
            'groupby': 'country_id',
            'aggregates': ['id:count'],
            'domain': [['id', 'in', [self.partner.id, partner_b.id]]],
        })
        self.assertEqual(result['status'], 'success')
        self.assertTrue(result['data']['groups'])
        total = sum(
            group.get('id_count', 0) for group in result['data']['groups'])
        self.assertEqual(total, 2)

    def test_group_by_invalid_aggregator(self):
        """An unsupported aggregator returns a 400 error."""
        result = self.tools._ai_group_by({
            'model': 'res.partner',
            'groupby': 'country_id',
            'aggregates': ['id:bogus'],
        })
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['code'], 400)

    def test_sensitive_fields_never_returned(self):
        """Sensitive fields are stripped even when requested."""
        result = self.tools._ai_search_read({
            'model': 'res.partner',
            'domain': [['id', '=', self.partner.id]],
            'fields': ['id', 'name', 'password'],
        })
        record = result['data']['records'][0]
        self.assertNotIn('password', record)

    def test_tool_framework_permission_and_audit(self):
        """Tool invocation checks permissions and writes the audit log."""
        # Ensure the registry contains the generic tools.
        self.env['hdai.tool']._sync_registry()
        tool = self.env['hdai.tool'].search(
            [('name', '=', 'generic.search_count')], limit=1)
        self.assertTrue(tool)
        result = self.env['hdai.tool'].with_user(self.user).action_invoke_tool(
            'generic.search_count',
            {'model': 'res.partner', 'domain': [['email', '=', 'acme@example.com']]})
        self.assertEqual(result['status'], 'success')
        log = self.env['hdai.tool.log'].search(
            [('tool_name', '=', 'generic.search_count')],
            order='id desc', limit=1)
        self.assertTrue(log)
        self.assertEqual(log.status, 'success')
        self.assertIn('acme', log.input_params)

    def test_tool_framework_rejects_unauthorized_user(self):
        """A user without the hdai group gets a 421 permission error."""
        self.env['hdai.tool']._sync_registry()
        # The base public user is never a member of the hdai groups.
        outsider = self.env.ref('base.public_user')
        result = self.env['hdai.tool'].sudo().with_user(outsider).action_invoke_tool(
            'generic.search_count',
            {'model': 'res.partner', 'domain': []})
        self.assertEqual(result['status'], 'error')
        self.assertEqual(result['code'], 421)
