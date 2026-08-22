# -*- coding: utf-8 -*-
from odoo import fields, models


class HdaiUsage(models.Model):
    _name = 'hdai.usage'
    _description = 'HD AI Token Usage Record'
    _order = 'create_date desc, id desc'

    session_id = fields.Many2one(
        'hdai.session', string='Chat Session', ondelete='set null', index=True)
    user_id = fields.Many2one(
        'res.users', string='User', required=True, index=True)
    provider_id = fields.Many2one(
        'hdai.provider', string='Provider', required=True, ondelete='restrict')
    model_id = fields.Many2one(
        'hdai.model', string='Model', required=True, ondelete='restrict')
    model_code = fields.Char(string='Model Code')
    request_type = fields.Selection([
        ('chat', 'Chat'),
        ('test', 'Connection Test'),
        ('tool', 'Tool Call'),
    ], string='Request Type', default='chat', required=True)
    prompt_tokens = fields.Integer(string='Input Tokens', default=0)
    completion_tokens = fields.Integer(string='Output Tokens', default=0)
    total_tokens = fields.Integer(string='Total Tokens', default=0)
    latency_ms = fields.Integer(string='Latency (ms)', default=0)
    status = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
    ], string='Status', default='success')
