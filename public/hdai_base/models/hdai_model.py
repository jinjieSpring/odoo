# -*- coding: utf-8 -*-
from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.hdai_base.models.llm_service import LLMService


class HdaiModel(models.Model):
    _name = 'hdai.model'
    _description = 'AI Model'
    _order = 'provider_id, sequence, name'

    _CAPABILITY_FIELDS = (
        'supports_reasoning',
        'supports_web_search',
        'supports_streaming',
    )

    _SCENARIOS = (
        ('chat', 'Chat'),
        ('channel', 'Channel / Livechat'),
        ('summary', 'Summary / Drafting'),
        ('suggest', 'Decision Suggestions'),
        ('embed', 'Embedding / Vectorization'),
    )

    name = fields.Char(string='Model Name', required=True, translate=True)
    code = fields.Char(
        string='Model Code', required=True,
        help='Model identifier used by the provider API, e.g. gpt-4o-mini, '
             'deepseek-chat, qwen-max, llama3.1:8b')
    sequence = fields.Integer(string='Sequence', default=10)
    provider_id = fields.Many2one(
        'hdai.provider', string='Provider', required=True,
        ondelete='cascade')
    context_length = fields.Integer(
        string='Context Length', default=128000,
        help='Context window size (tokens), used to compute the context '
             'usage ratio.')
    max_output_tokens = fields.Integer(string='Max Output Tokens', default=8192)
    # Sampling parameters (administrator-only model settings, applied to
    # every conversation using this model). Recommended values are filled
    # per provider on create and can be adjusted here; providers that fix
    # or reject a parameter ignore it at request time.
    temperature = fields.Float(
        string='Temperature', default=0.7,
        help='Sampling temperature (0-2). Configured by the administrator '
             'in the model settings and applied to conversations using '
             'this model.')
    top_p = fields.Float(
        string='Top P', default=1.0,
        help='Nucleus sampling probability (0-1). Configured by the '
             'administrator in the model settings; providers that fix or '
             'reject the parameter ignore it.')
    top_k = fields.Integer(
        string='Top K', default=0,
        help='Top-K sampling (number of candidate tokens; 0 means the '
             'provider default). Local providers accept it; cloud '
             'providers generally ignore it.')
    thinking_strength = fields.Selection([
        ('none', 'Off'),
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ], string='Thinking Strength', default='none',
        help='Default reasoning strength for new conversations using this '
             'model. Sampling parameters (temperature / top P / top K) are '
             'configured by the administrator here as well and applied to '
             'every conversation. Users can still adjust reasoning per '
             'conversation when it is allowed.')
    # Capability layer (model-inherent, detected, readonly in the UI) and
    # permission layer (administrator controlled).
    supports_reasoning = fields.Boolean(
        string='Supports Reasoning',
        help='Whether the model supports a step-by-step reasoning (thinking '
             'chain). Detected automatically when testing the connection.')
    allow_reasoning = fields.Boolean(
        string='Allow Users to Use Reasoning', default=True)
    supports_web_search = fields.Boolean(
        string='Supports Web Search',
        help='Whether the model can query the web when enabled per request. '
             'Detected automatically when testing the connection.')
    supports_streaming = fields.Boolean(
        string='Supports Streaming',
        default=True,
        help='Whether the model can stream its response token by token. '
             'Detected automatically when testing the connection.')
    allow_web_search = fields.Boolean(
        string='Allow Users to Use Web Search', default=True)
    allow_streaming = fields.Boolean(
        string='Allow Streaming', default=True)
    active = fields.Boolean(string='Active', default=True)

    @api.model_create_multi
    def create(self, vals_list):
        """Capabilities are detected programmatically only: creating a
        record with capability values requires the internal probe flag.
        Recommended parameter defaults (context / max output / sampling)
        are filled from the provider profile and the model code when not
        explicitly provided."""
        if not self.env.context.get('hdai_capability_probe'):
            for vals in vals_list:
                if any(field in vals for field in self._CAPABILITY_FIELDS):
                    raise UserError(_(
                        'Model capabilities cannot be set manually: they '
                        'are detected automatically when testing the '
                        'connection.'))
        for vals in vals_list:
            provider_id = vals.get('provider_id')
            provider = (
                self.env['hdai.provider'].browse(provider_id)
                if provider_id else self.env['hdai.provider'])
            defaults = LLMService._defaults_for_model(
                provider, vals.get('code'))
            for field in ('context_length', 'max_output_tokens',
                          'temperature', 'top_p', 'top_k'):
                if field not in vals and defaults.get(field) is not None:
                    vals[field] = defaults[field]
        return super().create(vals_list)

    @api.model
    def _get_default_model(self):
        params = self.env['ir.config_parameter'].sudo()
        model_id = int(params.get_param('hdai.default_model_id', '0') or 0)
        return self.browse(model_id).exists()

    @api.model
    def _get_model_for_scenario(self, scenario):
        """Return the model routed to a scenario (design 2.4).

        Scenario defaults are stored as ``hdai.route.<scenario>`` config
        parameters and can be overridden on the settings page; an unset
        scenario falls back to the global default model. Switching the
        routing only changes configuration, never business code."""
        params = self.env['ir.config_parameter'].sudo()
        model_id = int(params.get_param(
            'hdai.route.%s' % scenario, '0') or 0)
        model = self.browse(model_id).exists()
        if model:
            return model
        return self._get_default_model()

    @api.model
    def _get_scenario_models(self, scenario):
        """Ordered candidate models for a scenario (failover by priority).

        Order: scenario default -> global default -> every active model
        ordered by provider priority then model sequence, deduplicated.
        ``_run_tool_loop`` walks this list when a provider call fails."""
        candidates = []
        seen = set()
        def add(model):
            if model and model.id not in seen:
                seen.add(model.id)
                candidates.append(model)
        add(self._get_model_for_scenario(scenario))
        add(self._get_default_model())
        models = self.search([('active', '=', True)])
        models = models.sorted(
            key=lambda m: (m.provider_id.priority, m.provider_id.sequence,
                           m.sequence, m.id))
        for model in models:
            add(model)
        return candidates

    def _allowed_options(self):
        self.ensure_one()
        return {
            'reasoning': bool(self.supports_reasoning and self.allow_reasoning),
            'web_search': bool(
                self.supports_web_search and self.allow_web_search),
            'streaming': bool(
                self.supports_streaming and self.allow_streaming),
        }

    def action_test_connection(self):
        self.ensure_one()
        result = LLMService.probe_model_capabilities(self)
        if not result.get('ok'):
            return self._test_notification(
                False, result.get('error', _('Unknown error')))
        # Capability values are persisted programmatically (internal flag);
        # the permission fields are never touched by the probe.
        self.with_context(hdai_capability_probe=True).write({
            'supports_reasoning': bool(result.get('supports_reasoning')),
            'supports_web_search': bool(result.get('supports_web_search')),
            'supports_streaming': bool(result.get('supports_streaming')),
            'context_length': (
                result.get('context_length')
                or self.context_length
                or LLMService.DEFAULT_CONTEXT_LENGTH),
            'max_output_tokens': (
                result.get('max_output_tokens')
                or self.max_output_tokens
                or LLMService.DEFAULT_MAX_OUTPUT_TOKENS),
        })
        reasoning = (_('supported by the model')
                     if result['supports_reasoning']
                     else _('not supported by the model'))
        web_search = (_('supported by the model')
                      if result['supports_web_search']
                      else _('not supported by the model'))
        streaming = (_('supported by the model')
                     if result['supports_streaming']
                     else _('not supported by the model'))
        message = _(
            'Capabilities detected for %s: reasoning %s, web search %s, '
            'streaming %s. Connection latency: %.1f seconds.') % (
                self.display_name, reasoning, web_search, streaming,
                result.get('latency', 0))
        if (not result.get('context_length_detected')
                or not result.get('max_output_tokens_detected')):
            message = '%s %s' % (
                message,
                _('The provider did not expose the context length and max '
                  'output tokens; recommended defaults %s / %s were used, '
                  'adjust them in the model settings.') % (
                    result.get('context_length')
                    or LLMService.DEFAULT_CONTEXT_LENGTH,
                    result.get('max_output_tokens')
                    or LLMService.DEFAULT_MAX_OUTPUT_TOKENS))
        action = self._test_notification(True, message)
        # Reload the form so the capability fields and the disabled state
        # of the permission toggles reflect the freshly detected values.
        action['params']['next'] = {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
        return action

    def _test_notification(self, ok, message):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success' if ok else 'warning',
                'title': (_('Model test successful')
                          if ok else _('Model test failed')),
                'message': message,
                'sticky': not ok,
            },
        }

    def write(self, vals):
        if any(field in vals for field in self._CAPABILITY_FIELDS) \
                and not self.env.context.get('hdai_capability_probe'):
            raise UserError(_(
                'Model capabilities cannot be set manually: they are '
                'detected automatically when testing the connection.'))
        for record in self:
            supports_reasoning = vals.get(
                'supports_reasoning', record.supports_reasoning)
            if not supports_reasoning:
                vals['allow_reasoning'] = False
            supports_web_search = vals.get(
                'supports_web_search', record.supports_web_search)
            if not supports_web_search:
                vals['allow_web_search'] = False
            supports_streaming = vals.get(
                'supports_streaming', record.supports_streaming)
            if not supports_streaming:
                vals['allow_streaming'] = False
        return super().write(vals)
