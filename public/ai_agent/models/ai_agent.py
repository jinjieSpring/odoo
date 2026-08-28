# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AiAgent(models.Model):
    """Persona for a dedicated entry that creates a session with ``agent_id``.

    Systray chat does not bind an agent. Agents do not call other agents.
    Tools and background runs stay on that one agent.
    """
    _name = 'ai.agent'
    _description = 'AI Agent'
    _order = 'sequence, name'
    _check_company_auto = True

    name = fields.Char(string='Name', required=True, translate=True)
    description = fields.Text(string='Description', translate=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)
    company_id = fields.Many2one(
        'res.company', string='Company', index=True,
        default=lambda self: self.env.company)
    is_default = fields.Boolean(
        string='Default Agent',
        help='Fallback for dedicated menus that call _get_default_agent. '
             'Systray chat does not use this.')
    run_mode = fields.Selection([
        ('chat', 'Chat'),
        ('goal', 'Goal (background)'),
    ], string='Run Mode', required=True, default='chat',
        help='Chat: reply in the current request. Goal: accept a task and '
             'continue it in the background.')
    system_prompt = fields.Text(
        string='System Prompt', translate=True,
        help='Persona instructions prepended to every turn. Ignored when a '
             'prompt template is set.')
    prompt_id = fields.Many2one(
        'ai.prompt.template', string='Prompt Template', ondelete='set null')
    tool_ids = fields.Many2many(
        'ai.tool', string='Tools',
        help='Empty means every tool the user is allowed to call.')
    max_rounds = fields.Integer(
        string='Max Tool Rounds', default=8,
        help='How many times the model may be called in one chat turn or '
             'background goal run. One round is one model reply, which may '
             'include several tool calls. This is not the number of '
             'registered tools.')
    max_tool_calls_per_round = fields.Integer(
        string='Max tool calls per round', default=10,
        help='How many tools the model may invoke in a single round (one '
             'model reply). Distinct from max tool rounds, which limits how '
             'many times the model is called.')
    memory_enabled = fields.Boolean(
        string='Write Memory', default=True,
        help='After a turn, store a short note the agent can reuse later.')
    memory_limit = fields.Integer(
        string='Memory Entries to Keep', default=20,
        help='Oldest entries are dropped when this limit is exceeded.')
    memory_ids = fields.One2many(
        'ai.agent.memory', 'agent_id', string='Memory')
    run_ids = fields.One2many(
        'ai.agent.run', 'agent_id', string='Runs')

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered('is_default')._ensure_single_default()
        return records

    def write(self, vals):
        result = super().write(vals)
        if vals.get('is_default'):
            self.filtered('is_default')._ensure_single_default()
        return result

    def _ensure_single_default(self):
        for agent in self:
            others = self.search([
                ('is_default', '=', True),
                ('id', '!=', agent.id),
            ])
            if others:
                others.write({'is_default': False})

    @api.model
    def _get_default_agent(self):
        agent = self.search([
            ('is_default', '=', True), ('active', '=', True),
        ], limit=1)
        return agent or self.search([('active', '=', True)], limit=1)

    def _effective_max_rounds(self):
        """This agent's max tool rounds (at least 1)."""
        self.ensure_one()
        return max(1, int(self.max_rounds or 8))

    def _effective_max_calls_per_round(self):
        """This agent's max tool calls in one model reply (at least 1)."""
        self.ensure_one()
        return max(1, int(self.max_tool_calls_per_round or 10))

    def _to_choice(self):
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name,
            'run_mode': self.run_mode,
        }
