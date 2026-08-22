# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HdaiAgent(models.Model):
    _name = 'hdai.agent'
    _description = 'AI Agent'
    _order = 'sequence, name'

    name = fields.Char(string='Name', required=True, translate=True)
    description = fields.Text(string='Description')
    system_prompt = fields.Text(
        string='System Prompt',
        default='You are the Linkin AI assistant embedded in Odoo. Answer '
                'questions about the database, open the right views when the '
                'user asks about business data, improve content and suggest '
                'next steps. You never modify the database directly.')
    provider_id = fields.Many2one(
        'hdai.provider', string='Model Provider')
    model_id = fields.Many2one(
        'hdai.model', string='Model',
        domain="[('provider_id', '=', provider_id)]")
    response_style = fields.Selection([
        ('analytical', 'Analytical'),
        ('balanced', 'Balanced'),
        ('creative', 'Creative'),
    ], string='Response Style', default='balanced',
        help='Analytical: deterministic and factual answers. Balanced: '
             'moderate tone. Creative: more human-like, varied answers.')
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)
    is_default = fields.Boolean(
        string='Default Agent',
        help='Used when no agent is selected explicitly (chat, livechat and '
             'Discuss continuation).')

    @api.model
    def _get_default_agent(self):
        agent = self.search(
            [('is_default', '=', True), ('active', '=', True)], limit=1)
        return agent or self.search([('active', '=', True)], limit=1)

    def _resolve_model(self):
        """Return the model used by this agent, falling back to the default
        model when the agent has none configured."""
        self.ensure_one()
        if self.model_id:
            return self.model_id
        return self.env['hdai.model']._get_default_model()
