# -*- coding: utf-8 -*-
from odoo import fields, models


class AiAuditLog(models.Model):
    _inherit = 'ai.audit.log'

    agent_id = fields.Many2one(
        'ai.agent', string='Agent', ondelete='set null', index=True)
    run_id = fields.Many2one(
        'ai.agent.run', string='Agent Run', ondelete='set null', index=True)
