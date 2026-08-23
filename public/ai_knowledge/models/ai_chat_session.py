# -*- coding: utf-8 -*-
from odoo import fields, models


class AiChatSession(models.Model):
    _inherit = 'ai.chat.session'

    knowledge_enabled = fields.Boolean(string='Use Knowledge Base', default=False)
    knowledge_top_k = fields.Integer(string='Knowledge Top K', default=5)
    knowledge_ids = fields.Many2many(
        'ai.knowledge.base', string='Knowledge Bases')
    knowledge_document_ids = fields.Many2many(
        'ai.knowledge.document', string='Knowledge Documents')
