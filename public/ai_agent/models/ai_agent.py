# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AiAgent(models.Model):
    """Persona bound to a chat session.

    Systray chat always uses the default agent; extra records exist so a
    dedicated menu can create a session with a fixed ``agent_id``. Agents do
    not call other agents. Tools and background runs stay on that one agent.
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
        help='Systray new sessions use this agent. Dedicated menus should '
             'pass agent_id when creating a session.')
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
        help='Upper bound for tool-loop rounds on a chat turn or a goal run.')
    memory_enabled = fields.Boolean(string='Write Memory', default=True)
    memory_limit = fields.Integer(
        string='Memory Entries to Keep', default=20)
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

    def _to_choice(self):
        self.ensure_one()
        return {
            'id': self.id,
            'name': self.name,
            'run_mode': self.run_mode,
        }
