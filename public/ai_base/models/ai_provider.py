# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ai_base.tools import (
    AiError, get_provider, normalize_base_url, pretty_model_name)


class AiProvider(models.Model):
    _name = 'ai.provider'
    _description = 'AI Model Provider'
    _order = 'sequence, name'
    _check_company_auto = True

    _TYPE_PRESETS = {
        'openai_compat': {
            'name': 'OpenAI Compatible',
            'endpoint': 'https://api.openai.com/v1',
        },
        'qwen': {
            'name': 'Tongyi Qianwen',
            'endpoint': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        },
        'ernie': {
            'name': 'Wenxin Yiyan',
            'endpoint': 'https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions',
        },
        'deepseek': {
            'name': 'DeepSeek',
            'endpoint': 'https://api.deepseek.com/v1',
        },
        'ollama': {
            'name': 'Ollama (Local)',
            'endpoint': 'http://localhost:11434',
        },
        'custom': {
            'name': 'Private Model',
            'endpoint': '',
        },
    }

    name = fields.Char(string='Provider Name', required=True)
    provider_type = fields.Selection([
        ('openai_compat', 'OpenAI Compatible'),
        ('qwen', 'Tongyi Qianwen'),
        ('ernie', 'Wenxin Yiyan'),
        ('deepseek', 'DeepSeek'),
        ('ollama', 'Ollama (Local)'),
        ('custom', 'Private / Custom'),
    ], string='Provider Type', required=True, default='openai_compat')
    endpoint = fields.Char(string='API Endpoint')
    api_key = fields.Char(
        string='API Key', copy=False, groups='ai_base.group_manager')
    api_secret = fields.Char(
        string='API Secret', copy=False, groups='ai_base.group_manager',
        help='Used by Ernie (Wenxin) as the secret key.')
    timeout = fields.Integer(string='Timeout (seconds)', default=60)
    proxy = fields.Char(string='HTTP Proxy')
    sequence = fields.Integer(string='Sequence', default=10)
    is_active = fields.Boolean(
        string='Active', default=True,
        help='Master switch for this provider. Disabled providers are skipped '
             'even if a model under them is active or marked preferred.')
    note = fields.Text(string='Notes')
    company_id = fields.Many2one(
        'res.company', string='Company', index=True,
        help='Empty means the provider is available to every company.')
    model_ids = fields.One2many('ai.model', 'provider_id', string='Models')
    model_count = fields.Integer(compute='_compute_model_count', string='Models')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            preset = self._TYPE_PRESETS.get(vals.get('provider_type') or 'openai_compat')
            if preset:
                for field, value in preset.items():
                    vals.setdefault(field, value)
            if vals.get('endpoint'):
                vals['endpoint'] = normalize_base_url(vals['endpoint'])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('endpoint'):
            vals['endpoint'] = normalize_base_url(vals['endpoint'])
        return super().write(vals)

    @api.onchange('provider_type')
    def _onchange_provider_type(self):
        preset = self._TYPE_PRESETS.get(self.provider_type)
        if not preset:
            return
        previous = self._origin.provider_type if self._origin else False
        previous_preset = self._TYPE_PRESETS.get(previous, {})
        if not self.name or self.name == previous_preset.get('name'):
            self.name = preset['name']
        self.endpoint = preset['endpoint']

    @api.depends('model_ids')
    def _compute_model_count(self):
        data = self.env['ai.model']._read_group(
            [('provider_id', 'in', self.ids)],
            ['provider_id'], ['provider_id:count'])
        count_map = {provider.id: count for provider, count in data}
        for provider in self:
            provider.model_count = count_map.get(provider.id, 0)

    def _get_client(self):
        self.ensure_one()
        return get_provider(self)

    def action_test_connection(self):
        """Health-check the provider, sync listed models, and probe thinking."""
        self.ensure_one()
        if not self.is_active:
            raise UserError(_('Provider "%s" is disabled.') % self.name)
        client = self._get_client()
        try:
            listed = client.list_models()
        except AiError as exc:
            return self._notify(False, _('Connection test failed: %s') % exc)
        created, updated, thinking_checked, thinking_supported = (
            self._sync_listed_models(listed, client))
        if created and updated:
            message = _(
                'Connection successful. Created %s model(s), updated %s.') % (
                    created, updated)
        elif created:
            message = _('Connection successful. Created %s model(s).') % created
        elif updated:
            message = _('Connection successful. Updated %s existing model(s).') % updated
        else:
            message = _('Connection successful, but the API returned no models.')
        if thinking_checked:
            message = '%s %s' % (message, _(
                'Thinking supported on %s of %s chat model(s).') % (
                    thinking_supported, thinking_checked))
        return self._notify(True, message, reload=True)

    def _sync_listed_models(self, listed, client=None):
        self.ensure_one()
        client = client or self._get_client()
        existing = {
            model.model_name_remote: model for model in self.model_ids
            if model.model_name_remote
        }
        created = 0
        updated = 0
        thinking_checked = 0
        thinking_supported = 0
        for info in listed:
            remote = info.get('remote_name')
            if not remote:
                continue
            vals = self._listed_model_vals(info)
            current = existing.get(remote)
            if current:
                if current._name_tracks_remote():
                    vals['name'] = pretty_model_name(remote)
                current.write(vals)
                model = current
                updated += 1
            else:
                display = info.get('name') or ''
                if not display or display == remote:
                    display = pretty_model_name(remote)
                vals.update({
                    'name': display,
                    'code': self._unique_model_code(remote),
                    'provider_id': self.id,
                    'model_name_remote': remote,
                    'model_kind': info.get('model_kind') or 'chat',
                })
                model = self.env['ai.model'].create(vals)
                existing[remote] = model
                created += 1
            if model.model_kind == 'chat':
                thinking_checked += 1
                if model._probe_thinking(client):
                    thinking_supported += 1
        return created, updated, thinking_checked, thinking_supported

    def _listed_model_vals(self, info):
        vals = {
            'vendor_info': info.get('vendor_info') or {},
            'supports_streaming': bool(info.get('supports_streaming')),
        }
        if info.get('max_context_tokens'):
            vals['max_context_tokens'] = info['max_context_tokens']
        if info.get('max_tokens_default'):
            vals['max_tokens_default'] = info['max_tokens_default']
        return vals

    def _unique_model_code(self, remote_name):
        return self.env['ai.model']._unique_code_for_remote(
            remote_name, provider_id=self.id)

    def _notify(self, ok, message, reload=False):
        params = {
            'type': 'success' if ok else 'warning',
            'title': _('Connection Test Successful') if ok else _(
                'Connection Test Failed'),
            'message': message,
            'sticky': not ok,
        }
        if reload:
            params['next'] = {
                'type': 'ir.actions.act_window',
                'res_model': 'ai.provider',
                'res_id': self.id,
                'view_mode': 'form',
                'views': [(False, 'form')],
                'target': 'current',
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': params,
        }
