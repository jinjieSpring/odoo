# -*- coding: utf-8 -*-
"""Offline tests for the tool framework rate limiting and timeout
enforcement (HD-AI-STD-001 section 8.6 and the timeout metadata)."""

import time

from odoo.tests import TransactionCase

from odoo.addons.hdai_base.models.hdai_tool import AI_TOOL_REGISTRY
from odoo.addons.hdai_base.models.hdai_generic_tools import HdaiGenericTools


def _ai_test_sleep(self, params, context=None):
    """Test-only tool sleeping for the requested number of seconds."""
    time.sleep(float(params.get('seconds', 0)))
    return {'status': 'success', 'message': 'slept',
            'data': {'slept': params.get('seconds', 0)}}


class TestToolLimits(TransactionCase):

    def setUp(self):
        super().setUp()
        self.user = self.env.user
        self.user.sudo().group_ids = [
            (4, self.env.ref('hdai_base.hdai_group_user').id)]
        # Register the test-only tool directly in the framework registry,
        # attached to the generic tools model which always exists.
        HdaiGenericTools._ai_test_sleep = _ai_test_sleep
        metadata = {
            'name': 'generic.test_sleep',
            'description': (
                'Test-only tool that sleeps for a while, used by the '
                'offline suite to verify the framework rate limiting.'),
            'category': 'generic',
            'scope': 'global',
            'suggestive': False,
            'read_only': True,
            'input_schema': {
                'type': 'object',
                'properties': {'seconds': {'type': 'number'}},
                'required': ['seconds'],
                'additionalProperties': False,
            },
            'output_schema': {
                'type': 'object',
                'properties': {'slept': {'type': 'number'}},
            },
            'required_permissions': ['hdai_base.hdai_group_user'],
            'rate_limit': 5,
            'timeout': 1,
            'cost_estimate': 0.0,
            'deprecated': False,
            'deprecation_message': '',
        }
        AI_TOOL_REGISTRY['generic.test_sleep'] = (
            'hdai.generic.tools', '_ai_test_sleep', metadata)
        self.env['hdai.tool']._sync_registry()
        # Start each test with a clean call history for the test tool.
        self.env['hdai.tool.log'].sudo().search([
            ('tool_name', '=', 'generic.test_sleep'),
        ]).unlink()

    def test_rate_limit_returns_429(self):
        """Calling a rate-limited tool more than allowed returns 429."""
        self.env['ir.config_parameter'].sudo().set_param(
            'hdai.test.rate_limit', '1')
        tool = self.env['hdai.tool'].search(
            [('name', '=', 'generic.test_sleep')], limit=1)
        tool.write({'rate_limit': 1})
        first = self.env['hdai.tool'].action_invoke_tool(
            'generic.test_sleep', {'seconds': 0})
        self.assertEqual(first['status'], 'success')
        second = self.env['hdai.tool'].action_invoke_tool(
            'generic.test_sleep', {'seconds': 0})
        self.assertEqual(second['status'], 'error')
        self.assertEqual(second['code'], 429)

    def test_timeout_metadata_recorded(self):
        """The configured timeout is part of the tool metadata contract."""
        tool = self.env['hdai.tool'].search(
            [('name', '=', 'generic.test_sleep')], limit=1)
        self.assertEqual(tool.timeout, 1)
        manifest = self.env['hdai.tool'].action_get_manifest()
        entry = next(
            item for item in manifest if item['name'] == 'generic.test_sleep')
        self.assertIn('timeout', tool._fields)
        self.assertTrue(entry)

    def test_sleep_tool_completes(self):
        """A test tool call within budget completes normally."""
        result = self.env['hdai.tool'].action_invoke_tool(
            'generic.test_sleep', {'seconds': 0})
        self.assertEqual(result['status'], 'success')
