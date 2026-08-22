# -*- coding: utf-8 -*-
from odoo import fields, models


class HdaiActionLog(models.Model):
    _name = 'hdai.action.log'
    _description = 'AI Action Log'
    _order = 'create_date desc, id desc'

    user_id = fields.Many2one(
        'res.users', string='User', required=True,
        default=lambda self: self.env.user, ondelete='cascade')
    session_id = fields.Many2one(
        'hdai.session', string='Session', ondelete='set null')
    channel_id = fields.Many2one(
        'discuss.channel', string='Channel', ondelete='set null')
    action = fields.Selection([
        ('chat', 'Chat'),
        ('send_message', 'Send as Message'),
        ('log_note', 'Log as Note'),
        ('open_view', 'Open View'),
        ('livechat_reply', 'Livechat Reply'),
        ('discuss_reply', 'Discuss Reply'),
        ('agent_run', 'Agent Run'),
        ('agent_multi_run', 'Multi-Agent Run'),
        ('mcp_tool_call', 'MCP Tool Call'),
        ('documents_classify', 'Document Classification'),
        ('documents_classify_apply', 'Document Classification Applied'),
    ], string='Action', required=True, default='chat')
    query = fields.Text(string='Query')
    result = fields.Text(string='Result')
    model_name = fields.Char(string='Target Model')
    res_id = fields.Integer(string='Target Record')
    error = fields.Text(string='Error')
    create_date = fields.Datetime(string='Date', readonly=True)
