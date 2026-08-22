# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class AiConfig(models.TransientModel):
    """Module-owned configuration. Values persist in ir.config_parameter."""

    _name = 'ai.config'
    _description = 'AI Base Configuration'

    default_model_id = fields.Many2one(
        'ai.model', string='Default Chat Model',
        domain="[('model_kind', '=', 'chat'), ('is_active', '=', True), "
               "('provider_id.is_active', '=', True)]")
    embed_model_id = fields.Many2one(
        'ai.model', string='Default Embedding Model',
        domain="[('model_kind', '=', 'embedding'), ('is_active', '=', True), "
               "('provider_id.is_active', '=', True)]")
    log_retention_days = fields.Integer(
        string='Log Retention (days)', default=90)
    rate_limit_user = fields.Integer(
        string='Per-user calls / minute', default=30)
    rate_limit_global = fields.Integer(
        string='Global calls / minute', default=120)
    max_input_chars = fields.Integer(
        string='Max input characters', default=20000)
    sensitive_words = fields.Char(
        string='Sensitive words (comma-separated)')
    max_tool_rounds = fields.Integer(
        string='Max agent rounds', default=10)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        params = self.env['ir.config_parameter'].sudo()

        def _model(key):
            model_id = int(params.get_param(key, '0') or 0)
            return model_id if model_id and self.env['ai.model'].browse(
                model_id).exists() else False

        values.update({
            'default_model_id': _model('ai.default_model_id'),
            'embed_model_id': _model('ai.route.embed'),
            'log_retention_days': int(
                params.get_param('ai_base.log_retention_days', '90') or 90),
            'rate_limit_user': int(
                params.get_param('ai_base.rate_limit_user_per_minute', '30') or 30),
            'rate_limit_global': int(
                params.get_param('ai_base.rate_limit_global_per_minute', '120') or 120),
            'max_input_chars': int(
                params.get_param('ai_base.max_input_chars', '20000') or 20000),
            'sensitive_words': params.get_param('ai_base.sensitive_words', '') or '',
            'max_tool_rounds': int(
                params.get_param('ai_base.max_tool_rounds', '10') or 10),
        })
        return values

    def action_save(self):
        self.ensure_one()
        params = self.env['ir.config_parameter'].sudo()
        chat_id = int(self.default_model_id.id or 0)
        embed_id = int(self.embed_model_id.id or 0)
        params.set_param('ai.default_model_id', str(chat_id))
        params.set_param('ai.route.chat', str(chat_id))
        params.set_param('ai.route.embed', str(embed_id))
        params.set_param(
            'ai_base.log_retention_days', str(self.log_retention_days or 90))
        params.set_param(
            'ai_base.rate_limit_user_per_minute', str(self.rate_limit_user or 30))
        params.set_param(
            'ai_base.rate_limit_global_per_minute', str(self.rate_limit_global or 120))
        params.set_param(
            'ai_base.max_input_chars', str(self.max_input_chars or 20000))
        params.set_param(
            'ai_base.sensitive_words', self.sensitive_words or '')
        params.set_param(
            'ai_base.max_tool_rounds', str(self.max_tool_rounds or 10))
        if self.default_model_id:
            self.default_model_id.action_set_as_default('chat')
        if self.embed_model_id:
            self.embed_model_id.action_set_as_default('embed')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Configuration saved'),
                'message': _('AI Base settings have been updated.'),
                'next': self.action_open(),
            },
        }

    @api.model
    def action_open(self):
        wizard = self.create({})
        return {
            'type': 'ir.actions.act_window',
            'name': _('AI Configuration'),
            'res_model': 'ai.config',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'current',
        }
