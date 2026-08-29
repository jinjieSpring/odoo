# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import _, api, fields, models


class AiRequestLog(models.Model):
    """Session-less usage (embed, API chat without a session). Conversation
    usage lives on ``ai.chat.message``. Tool actions stay on ``ai.audit.log``.
    """

    _name = 'ai.request.log'
    _description = 'AI Usage Line'
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    create_date = fields.Datetime(string='Created On', readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Company', index=True,
        default=lambda self: self.env.company)
    user_id = fields.Many2one(
        'res.users', string='User', required=True, index=True,
        default=lambda self: self.env.user)
    session_id = fields.Many2one(
        'ai.chat.session', string='Session', ondelete='cascade', index=True)
    provider_id = fields.Many2one(
        'ai.provider', string='Provider', ondelete='set null')
    model_id = fields.Many2one(
        'ai.model', string='Model', ondelete='set null')
    model_code = fields.Char(string='Model Code')
    scenario_key = fields.Char(string='Scenario Key', index=True)
    request_type = fields.Selection([
        ('chat', 'Chat'),
        ('rag', 'RAG Chat'),
        ('embed', 'Embedding'),
        ('agent', 'Agent'),
        ('tool', 'Tool Call'),
        ('image', 'Image'),
        ('audio', 'Audio'),
        ('probe', 'Connection Test'),
    ], string='Request Type', default='chat', required=True, index=True)
    prompt_tokens = fields.Integer(string='Input Tokens', default=0)
    completion_tokens = fields.Integer(string='Output Tokens', default=0)
    total_tokens = fields.Integer(string='Total Tokens', default=0)
    latency_ms = fields.Integer(string='Latency (ms)', default=0)
    status = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
    ], string='Status', default='success', index=True)
    error_message = fields.Char(string='Error')
    error_traceback = fields.Text(string='Traceback')
    input_summary = fields.Text(string='Input Prompt')
    output_summary = fields.Text(string='Output Result')
    rag_snippets = fields.Text(string='RAG Snippets')

    def action_export_xlsx(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Usage'),
            'res_model': 'ai.request.log',
            'view_mode': 'list,form,pivot,graph',
            'target': 'current',
        }

    @api.model
    def _cron_gc_logs(self):
        days = int(self.env['ir.config_parameter'].sudo().get_param(
            'ai_base.log_retention_days', '90') or 90)
        if days <= 0:
            return
        limit_date = fields.Datetime.now() - timedelta(days=days)
        self.sudo().search([('create_date', '<', limit_date)]).unlink()

    @api.model
    def _cron_error_alert(self):
        params = self.env['ir.config_parameter'].sudo()
        window = int(params.get_param('ai_base.alert_window_minutes', '15') or 15)
        threshold = float(params.get_param('ai_base.alert_error_rate', '0.3') or 0.3)
        since = fields.Datetime.now() - timedelta(minutes=window)
        logs = self.sudo().search([('create_date', '>=', since)])
        messages = self.env['ai.chat.message'].sudo().search([
            ('role', '=', 'assistant'),
            ('model_id', '!=', False),
            ('create_date', '>=', since),
        ])
        total = len(logs) + len(messages)
        if total < 5:
            return
        errors = len(logs.filtered(lambda log: log.status == 'error')) + len(
            messages.filtered(lambda msg: msg.status == 'error'))
        rate = errors / float(total)
        if rate < threshold:
            return
        users = self.env.ref('ai_base.group_manager').all_user_ids.filtered('email')
        if not users:
            return
        self.env['mail.mail'].sudo().create({
            'subject': _('AI Base error rate alert'),
            'body_html': _(
                '<p>AI request error rate is %(rate).0f%% over the last '
                '%(window)s minutes (%(errors)s / %(total)s).</p>'
            ) % {
                'rate': rate * 100,
                'window': window,
                'errors': errors,
                'total': total,
            },
            'email_to': ','.join(users.mapped('email')),
            'auto_delete': True,
        }).send()
