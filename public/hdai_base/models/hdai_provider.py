import re

from odoo import _, api, fields, models

from odoo.addons.hdai_base.models.llm_service import LLMError, LLMService


class HdaiProvider(models.Model):
    _name = 'hdai.provider'
    _description = 'HD AI Model Provider'
    _order = 'priority, sequence, name'

    # Recommended default settings per provider type. ``name`` / ``base_url``
    # / ``api_type`` are filled when the type is chosen (or on create) and
    # can be adjusted by the administrator afterwards.
    _TYPE_PRESETS = {
        'deepseek': {
            'name': 'DeepSeek',
            'base_url': 'https://api.deepseek.com/v1',
            'api_type': 'responses',
        },
        'vllm': {
            'name': 'vLLM (Local)',
            'base_url': 'http://localhost:8000/v1',
            'api_type': 'chat_completions',
        },
        'ollama': {
            'name': 'Ollama (Local)',
            'base_url': 'http://localhost:11434',
            'api_type': 'chat_completions',
        },
        'llamacpp': {
            'name': 'llama.cpp (Local)',
            'base_url': 'http://localhost:8080/v1',
            'api_type': 'chat_completions',
        },
        'openai': {
            'name': 'OpenAI',
            'base_url': 'https://api.openai.com/v1',
            'api_type': 'chat_completions',
        },
        'openai_compatible': {
            'name': 'OpenAI Compatible',
            'base_url': '',
            'api_type': 'chat_completions',
        },
    }

    name = fields.Char(string='Provider Name', required=True)
    provider_type = fields.Selection([
        ('deepseek', 'DeepSeek (Cloud)'),
        ('vllm', 'vLLM (Local)'),
        ('ollama', 'Ollama (Local)'),
        ('llamacpp', 'llama.cpp (Local)'),
        ('openai', 'OpenAI Compatible'),
        ('openai_compatible', 'OpenAI Compatible'),
    ], string='Provider Type', required=True, default='deepseek',
        help='DeepSeek: cloud API. vLLM: local inference server exposing the '
             'OpenAI-compatible protocol. Ollama / llama.cpp: local services '
             'with an OpenAI-compatible endpoint. Selecting a type fills the '
             'recommended Base URL and API protocol; adjust them as needed.')
    api_type = fields.Selection([
        ('chat_completions', 'Chat Completions'),
        ('responses', 'Responses API'),
    ], string='API Protocol', default='chat_completions', required=True,
        help='Chat Completions works with vLLM, Ollama and most OpenAI-'
             'compatible services. Responses API is the DeepSeek-native '
             'protocol and is selected automatically for DeepSeek.')
    base_url = fields.Char(
        string='Base URL', required=True,
        help='Base URL of the API, e.g. https://api.deepseek.com/v1 or '
             'http://localhost:8080/v1 (llama.cpp / vLLM). The scheme '
             '(http:// or https://) is added automatically when missing. '
             'Filled with the recommended address for the provider type '
             'when the type is selected; customize it freely.')
    api_key = fields.Char(
        string='API Key', groups='hdai_base.hdai_group_manager',
        copy=False,
        help='Provider API key; only administrators can read it. Not '
             'required for local models without authentication.')
    priority = fields.Integer(
        string='Priority', default=10,
        help='Lower values are tried first when multiple providers are '
             'configured (failover order).')
    sequence = fields.Integer(string='Sequence', default=10)
    model_ids = fields.One2many('hdai.model', 'provider_id', string='Models')
    model_count = fields.Integer(
        compute='_compute_model_count', string='Model Count')
    active = fields.Boolean(string='Active', default=True)
    notes = fields.Text(string='Notes')
    api_key_required = fields.Boolean(
        compute='_compute_api_key_state', string='API Key Required')
    api_key_valid = fields.Boolean(
        compute='_compute_api_key_state', string='API Key Valid')
    api_key_hint = fields.Char(
        compute='_compute_api_key_state', string='API Key Format Hint')

    @staticmethod
    def _normalize_base_url(url):
        """Ensure the base URL carries an explicit scheme.

        ``requests`` refuses URLs without a scheme ("No connection adapters
        were found for '127.0.0.1:8080/models'"), so a missing scheme is
        treated as plain http."""
        url = (url or '').strip()
        if not url:
            return url
        if '://' not in url:
            return 'http://' + url
        return url

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            preset = self._TYPE_PRESETS.get(vals.get('provider_type'))
            if preset:
                for field, value in preset.items():
                    vals.setdefault(field, value)
            if vals.get('base_url'):
                vals['base_url'] = self._normalize_base_url(vals['base_url'])
        return super().create(vals_list)

    @api.onchange('provider_type')
    def _onchange_provider_type(self):
        """Fill the recommended name / Base URL / API protocol for the
        selected provider type (design: best-effort defaults, editable)."""
        preset = self._TYPE_PRESETS.get(self.provider_type)
        if not preset:
            return
        previous = self._origin.provider_type if self._origin else False
        previous_preset = self._TYPE_PRESETS.get(previous, {})
        if not self.name or self.name == previous_preset.get('name'):
            self.name = preset['name']
        self.base_url = preset['base_url']
        self.api_type = preset['api_type']

    def write(self, vals):
        if vals.get('base_url'):
            vals['base_url'] = self._normalize_base_url(vals['base_url'])
        return super().write(vals)

    @api.depends('model_ids')
    def _compute_model_count(self):
        data = self.env['hdai.model']._read_group(
            [('provider_id', 'in', self.ids)],
            ['provider_id'], ['provider_id:count'])
        count_map = {provider.id: count for provider, count in data}
        for provider in self:
            provider.model_count = count_map.get(provider.id, 0)

    def _api_key_required(self):
        """Whether this provider needs an API key (cloud providers do;
        local llama.cpp/Ollama/vLLM endpoints usually do not)."""
        return not LLMService._is_local(self)

    @api.depends('provider_type', 'base_url', 'api_key')
    def _compute_api_key_state(self):
        for provider in self:
            if not provider._api_key_required():
                provider.api_key_required = False
                provider.api_key_valid = True
                provider.api_key_hint = _(
                    'Local model: no API key required.')
                continue
            provider.api_key_required = True
            key = provider.api_key or ''
            base = (provider.base_url or '').lower()
            if 'bigmodel' in base or 'zhipu' in base:
                fmt = _('Zhipu key format: <id>.<secret> (two parts '
                        'separated by a dot)')
                valid = bool(re.match(r'^[A-Za-z0-9]+\.[A-Za-z0-9]+$', key))
            elif ('dashscope' in base or 'moonshot' in base
                    or 'deepseek' in base or 'openai' in base):
                fmt = _('Key format: starts with "sk-" followed by at '
                        'least 10 characters')
                valid = bool(re.match(r'^sk-[A-Za-z0-9_-]{10,}$', key))
            else:
                fmt = _('Key format: at least 8 characters, no spaces')
                valid = bool(re.match(r'^[A-Za-z0-9_.-]{8,}$', key))
            provider.api_key_valid = valid
            provider.api_key_hint = '%s - %s' % (
                fmt, _('API key format is valid.')
                if valid else _('API key format is invalid.'))

    def action_test_provider(self):
        """Test the provider API and fill the model list on success."""
        self.ensure_one()
        # Capability values come from the provider probe (programmatic
        # path): the flag lets the hdai.model guard accept them.
        self = self.with_context(hdai_capability_probe=True)
        try:
            models_info = LLMService.list_models(self)
        except LLMError as exc:
            return self._notify(
                False, _('Connection test failed: %s') % exc)
        existing = {model.code: model for model in self.model_ids}
        created = 0
        missing_metadata = 0
        for info in models_info:
            code = info.get('code')
            if not code:
                continue
            if (not info.get('context_length')
                    or not info.get('max_output_tokens')):
                missing_metadata += 1
            defaults = LLMService._defaults_for_model(self, code)
            capability_vals = {
                'supports_reasoning': bool(info.get('supports_reasoning')),
                'supports_web_search': bool(info.get('supports_web_search')),
                'supports_streaming': bool(
                    info.get('supports_streaming', True)),
            }
            if code in existing:
                capability_vals['context_length'] = (
                    info.get('context_length')
                    or (existing[code].context_length
                        or defaults['context_length']))
                capability_vals['max_output_tokens'] = (
                    info.get('max_output_tokens')
                    or (existing[code].max_output_tokens
                        or defaults['max_output_tokens']))
                existing[code].write(capability_vals)
                continue
            capability_vals['context_length'] = (
                info.get('context_length')
                or defaults['context_length'])
            capability_vals['max_output_tokens'] = (
                info.get('max_output_tokens')
                or defaults['max_output_tokens'])
            self.model_ids = [(0, 0, dict({
                'name': info.get('name') or code,
                'code': code,
            }, **capability_vals))]
            created += 1
        if created:
            message = _('Connection successful. Fetched %s models.') % created
        elif models_info:
            message = _('Connection successful. All models are already known.')
        else:
            message = _('Connection successful, but the API returned no models.')
        if missing_metadata:
            message = '%s %s' % (
                message,
                _('%s model(s) did not expose the context length and max '
                  'output tokens; provider-specific recommended defaults '
                  'were applied, adjust them in the model settings.') % (
                    missing_metadata))
        return self._notify(True, message, reload=True)

    def _notify(self, ok, message, reload=False):
        params = {
            'type': 'success' if ok else 'warning',
            'title': _('Connection Test Successful') if ok else _('Connection Test Failed'),
            'message': message,
            'sticky': not ok,
        }
        if reload:
            params['next'] = {
                'type': 'ir.actions.client',
                'tag': 'hdai_refresh_systray',
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': params,
        }

    def action_save_and_return(self):
        """Save the provider and return to the AI settings screen."""
        self.ensure_one()
        if self.env.context.get('hdai_return_to_settings'):
            default_model = self.model_ids[:1]
            if default_model:
                self.env['hdai.settings']._set_defaults(
                    self.id, default_model.id)
        return {
            'type': 'ir.actions.client',
            'tag': 'hdai_open_settings',
        }

    @api.model
    def action_open_settings(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.config.settings',
            'name': _('HD AI Settings'),
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'inline',
            'context': {'module': 'hdai_base'},
        }
