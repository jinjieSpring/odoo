# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AiChatSession(models.Model):
    _inherit = 'ai.chat.session'

    agent_id = fields.Many2one(
        'ai.agent', string='Agent', ondelete='set null', index=True,
        help='Set on create by the default assistant or a dedicated entry. '
             'The chat UI does not switch agents.')

    @api.model_create_multi
    def create(self, vals_list):
        Agent = self.env['ai.agent']
        default = Agent._get_default_agent()
        for vals in vals_list:
            if not vals.get('agent_id') and default:
                vals['agent_id'] = default.id
        return super().create(vals_list)

    def action_cancel_agent_run(self):
        self.ensure_one()
        self.env['ai.agent.run'].search([
            ('session_id', '=', self.id),
            ('state', 'in', ('pending', 'running')),
        ]).action_cancel()
        return self.env['ai.chat'].session_payload(self)

    def _active_agent_run(self):
        self.ensure_one()
        return self.env['ai.agent.run'].search([
            ('session_id', '=', self.id),
            ('state', 'in', ('pending', 'running', 'waiting_user')),
        ], limit=1)
