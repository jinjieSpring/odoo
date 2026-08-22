# -*- coding: utf-8 -*-
from odoo import api, fields, models


class HdaiMessage(models.Model):
    _name = 'hdai.message'
    _description = 'AI Chat Message'
    _order = 'create_date, id'

    session_id = fields.Many2one(
        'hdai.session', string='Session', required=True,
        ondelete='cascade', index=True)
    role = fields.Selection([
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
    ], string='Role', required=True, default='user')
    content = fields.Text(string='Content', required=True)
    reasoning_content = fields.Text(string='Reasoning Content')
    model_id = fields.Many2one(
        related='session_id.model_id', string='Model', store=True)
    tool_cards = fields.Json(
        string='Tool Cards',
        default=list,
        help='Structured tool cards attached to this assistant message by '
             'the server-side tool loop (read-only tools that were executed '
             'automatically and suggestive tools that paused the loop for '
             'user confirmation).')
    prompt_tokens = fields.Integer(string='Input Tokens', default=0)
    completion_tokens = fields.Integer(string='Output Tokens', default=0)
    total_tokens = fields.Integer(string='Total Tokens', default=0)
    create_date = fields.Datetime(string='Date', readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        """Bump the parent session's write_date so the conversation moves to
        the top of the history whenever a message is added (send, resend,
        edit, regenerate or streamed reply)."""
        records = super().create(vals_list)
        for session in records.session_id:
            session.write({'state': session.state})
        return records
