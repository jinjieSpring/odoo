# -*- coding: utf-8 -*-
from odoo import fields, models


class AiChatSession(models.Model):
    _inherit = 'ai.chat.session'

    agent_id = fields.Many2one(
        'ai.agent', string='Agent', ondelete='set null', index=True,
        help='Empty for systray chat. Dedicated menus pass agent_id when '
             'creating a session.')

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

    def _is_goal_run(self):
        self.ensure_one()
        return bool(self.agent_id and self.agent_id.run_mode == 'goal')

    def _restricted_tool_names(self):
        """Agent 限定的工具名。``None`` 表示不限制。"""
        self.ensure_one()
        if not self.agent_id or not self.agent_id.tool_ids:
            return None
        return set(self.agent_id.tool_ids.mapped('name'))
