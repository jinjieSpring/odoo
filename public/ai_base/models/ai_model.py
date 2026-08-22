# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ai_base.models.ai_provider import AiError, get_provider


class AiModel(models.Model):
    _name = 'ai.model'
    _description = 'AI Model Pool Entry'
    _order = 'sequence, name'
    _check_company_auto = True

    _SCENARIOS = (
        ('chat', 'Chat'),
        ('embed', 'Embedding'),
        ('image', 'Image'),
        ('audio', 'Audio Transcribe'),
        ('rag', 'RAG'),
        ('agent', 'Agent'),
        ('summary', 'Summary / Rewrite'),
    )

    name = fields.Char(string='Display Name', required=True)
    code = fields.Char(
        string='Model Code', required=True, index=True,
        help='Business modules pass this code to ai.base.service.')
    provider_id = fields.Many2one(
        'ai.provider', string='Provider', required=True, ondelete='cascade',
        check_company=True)
    model_kind = fields.Selection([
        ('chat', 'Chat'),
        ('embedding', 'Embedding'),
        ('image', 'Image Generation'),
        ('audio_transcribe', 'Audio Transcribe'),
    ], string='Model Type', required=True, default='chat')
    model_name_remote = fields.Char(
        string='Remote Model Name', required=True,
        help='Value sent as the vendor ``model`` parameter.')
    max_context_tokens = fields.Integer(string='Max Context Tokens', default=8192)
    temperature_default = fields.Float(string='Default Temperature', default=0.7)
    top_p_default = fields.Float(string='Default Top P', default=0.9)
    max_tokens_default = fields.Integer(string='Default Max Tokens', default=2048)
    sequence = fields.Integer(string='Sequence', default=10)
    is_default = fields.Boolean(string='System Default')
    is_active = fields.Boolean(string='Active', default=True)
    supports_streaming = fields.Boolean(string='Supports Streaming', default=True)
    company_id = fields.Many2one(
        'res.company', string='Company', index=True,
        related='provider_id.company_id', store=True, readonly=True)

    _code_uniq = models.Constraint(
        'UNIQUE(code)',
        'The model code must be unique.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('model_name_remote') and vals.get('code'):
                vals['model_name_remote'] = vals['code']
        records = super().create(vals_list)
        for record in records:
            if record.is_default:
                record.action_set_as_default(record._kind_to_scenario())
        return records

    def write(self, vals):
        res = super().write(vals)
        if vals.get('is_default'):
            for record in self:
                record.action_set_as_default(record._kind_to_scenario())
        return res

    def _kind_to_scenario(self):
        self.ensure_one()
        return {
            'chat': 'chat',
            'embedding': 'embed',
            'image': 'image',
            'audio_transcribe': 'audio',
        }.get(self.model_kind, 'chat')

    def _allowed_options(self):
        self.ensure_one()
        return {
            'streaming': bool(self.supports_streaming),
            'reasoning': False,
            'web_search': False,
        }

    @api.model
    def _get_default_model(self):
        params = self.env['ir.config_parameter'].sudo()
        model_id = int(params.get_param('ai.default_model_id', '0') or 0)
        model = self.browse(model_id).exists()
        if model and model.is_active:
            return model
        return self.search([
            ('is_default', '=', True), ('is_active', '=', True),
            ('model_kind', '=', 'chat'),
        ], limit=1)

    @api.model
    def _get_model_for_scenario(self, scenario='chat'):
        params = self.env['ir.config_parameter'].sudo()
        model_id = int(params.get_param('ai.route.%s' % scenario, '0') or 0)
        model = self.browse(model_id).exists()
        if model and model.is_active:
            return model
        kind = {
            'chat': 'chat', 'agent': 'chat', 'rag': 'chat', 'summary': 'chat',
            'embed': 'embedding', 'image': 'image', 'audio': 'audio_transcribe',
        }.get(scenario, 'chat')
        found = self.search([
            ('is_active', '=', True), ('model_kind', '=', kind),
        ], limit=1)
        if found:
            return found
        return self._get_default_model()

    @api.model
    def _get_by_code(self, code):
        if not code:
            return self.browse()
        return self.search([('code', '=', code), ('is_active', '=', True)], limit=1)

    @api.model
    def _get_scenario_models(self, scenario='chat'):
        candidates = []
        seen = set()

        def add(model):
            if model and model.id not in seen:
                seen.add(model.id)
                candidates.append(model)

        add(self._get_model_for_scenario(scenario))
        add(self._get_default_model())
        models = self.search([('is_active', '=', True), ('model_kind', '=', 'chat')])
        models = models.sorted(key=lambda m: (m.provider_id.sequence, m.sequence, m.id))
        for model in models:
            add(model)
        return candidates

    def action_set_as_default(self, scenario='chat'):
        self.ensure_one()
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('ai.route.%s' % scenario, str(self.id))
        if scenario in ('chat', 'agent', 'rag'):
            params.set_param('ai.default_model_id', str(self.id))
            others = self.search([
                ('id', '!=', self.id), ('is_default', '=', True),
                ('model_kind', '=', self.model_kind),
            ])
            if others:
                others.write({'is_default': False})
            if not self.is_default:
                super(AiModel, self).write({'is_default': True})
        return True

    def action_test_connection(self):
        self.ensure_one()
        if not self.provider_id.is_active:
            raise UserError(_('Provider "%s" is disabled.') % self.provider_id.name)
        client = get_provider(self.provider_id)
        try:
            if self.model_kind == 'embedding':
                vectors = client.embedding(self, ['ping'])
                ok = bool(vectors and vectors[0])
                message = _('Embedding probe succeeded.') if ok else _(
                    'Embedding probe returned an empty vector.')
            else:
                result = client.chat_completion(
                    self,
                    [{'role': 'user', 'content': 'Reply with OK only.'}],
                    {'max_tokens': 16},
                )
                ok = True
                message = _('Chat probe succeeded: %s') % (
                    (result.get('content') or '')[:80] or _('empty reply'))
        except AiError as exc:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('Model test failed'),
                    'message': str(exc),
                    'sticky': True,
                },
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if ok else 'warning',
                'title': _('Model test successful') if ok else _('Model test failed'),
                'message': message,
            },
        }
