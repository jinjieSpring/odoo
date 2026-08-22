# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    hdai_default_provider_id = fields.Many2one(
        'hdai.provider', string='HD AI Default Provider')
    hdai_default_model_id = fields.Many2one(
        'hdai.model', string='HD AI Default Model',
        domain="[('provider_id', '=', hdai_default_provider_id)]")
    hdai_default_model_code = fields.Char(
        related='hdai_default_model_id.code', readonly=True,
        string='HD AI Default Model Code')
    hdai_default_model_context_length = fields.Integer(
        related='hdai_default_model_id.context_length', readonly=True,
        string='HD AI Default Model Context Length')
    hdai_default_model_max_output_tokens = fields.Integer(
        related='hdai_default_model_id.max_output_tokens', readonly=True,
        string='HD AI Default Model Max Output Tokens')
    hdai_context_prompt = fields.Text(
        string='HD AI Record Context Prompt',
        help='Template injected as a system message when a record context '
             'is attached; use the {snapshot} placeholder.')
    hdai_max_successive_calls = fields.Integer(
        string='HD AI Max Tool Rounds',
        default=10,
        help='Maximum number of successive model calls in the server-side '
             'tool loop before the assistant must stop.')
    hdai_max_tool_calls_per_call = fields.Integer(
        string='HD AI Max Tool Calls per Round',
        default=10,
        help='Maximum number of tool calls executed in a single loop round.')
    hdai_route_chat = fields.Many2one(
        'hdai.model', string='Chat Model',
        help='Default model for the system tray chat (scenario routing).')
    hdai_route_channel = fields.Many2one(
        'hdai.model', string='Channel / Livechat Model',
        help='Default model for channel replies and livechat.')
    hdai_route_summary = fields.Many2one(
        'hdai.model', string='Summary / Drafting Model',
        help='Default model for summaries, drafting and Composer output.')
    hdai_route_suggest = fields.Many2one(
        'hdai.model', string='Suggestion Model',
        help='Default model for decision suggestions.')
    hdai_route_embed = fields.Many2one(
        'hdai.model', string='Embedding Model',
        help='Default model for embedding/vectorization requests.')

    @api.onchange('hdai_default_provider_id')
    def _onchange_hdai_default_provider_id(self):
        """Keep the default model in sync with the chosen provider:
        clearing it when the provider is empty, otherwise pre-selecting the
        provider's first model (error_reference 6.4)."""
        provider = self.hdai_default_provider_id
        if provider:
            # Assign the recordset (not the raw id): Odoo 19's onchange
            # diff web_reads Many2one values and crashes on a bare int
            # ('int' object has no attribute 'origin').
            self.hdai_default_model_id = provider.model_ids[:1]
        else:
            self.hdai_default_model_id = False

    def hdai_action_open_provider(self):
        """Open the provider form (with the currently selected provider)."""
        provider = self.hdai_default_provider_id
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hdai.provider',
            'view_mode': 'form',
            'res_id': provider.id if provider else False,
            'target': 'current',
            'views': [[False, 'form']],
        }

    def get_values(self):
        result = super().get_values()
        defaults = self.env['hdai.settings']._get_defaults()
        params = self.env['ir.config_parameter'].sudo()
        result.update({
            # Many2one fields must be False (never the integer 0): a raw 0
            # in the cache makes the web client onchange web_read produce a
            # {'id': 0} row and crash ('int' object has no attribute
            # 'origin').
            'hdai_default_provider_id': defaults['provider_id'] or False,
            'hdai_default_model_id': defaults['model_id'] or False,
            'hdai_context_prompt': params.get_param(
                    'hdai_base.context_prompt',
                    'You are a helpful Odoo assistant. The user is currently '
                    'viewing the following business record; use it as context '
                    'when answering:\n{snapshot}'),
            'hdai_max_successive_calls': int(
                params.get_param('hdai.max_successive_calls', '10') or 10),
            'hdai_max_tool_calls_per_call': int(
                params.get_param('hdai.max_tool_calls_per_call', '10') or 10),
            'hdai_route_chat': int(
                params.get_param('hdai.route.chat', '0') or 0) or False,
            'hdai_route_channel': int(
                params.get_param('hdai.route.channel', '0') or 0) or False,
            'hdai_route_summary': int(
                params.get_param('hdai.route.summary', '0') or 0) or False,
            'hdai_route_suggest': int(
                params.get_param('hdai.route.suggest', '0') or 0) or False,
            'hdai_route_embed': int(
                params.get_param('hdai.route.embed', '0') or 0) or False,
        })
        return result

    def set_values(self):
        super().set_values()
        self.env['hdai.settings']._set_defaults(
            self.hdai_default_provider_id.id,
            self.hdai_default_model_id.id)
        if self.hdai_context_prompt:
            self.env['ir.config_parameter'].sudo().set_param(
                'hdai_base.context_prompt', self.hdai_context_prompt)
        params = self.env['ir.config_parameter'].sudo()
        params.set_param(
            'hdai.max_successive_calls',
            str(max(1, self.hdai_max_successive_calls or 10)))
        params.set_param(
            'hdai.max_tool_calls_per_call',
            str(max(1, self.hdai_max_tool_calls_per_call or 10)))
        for scenario, field_name in (
                ('chat', 'hdai_route_chat'),
                ('channel', 'hdai_route_channel'),
                ('summary', 'hdai_route_summary'),
                ('suggest', 'hdai_route_suggest'),
                ('embed', 'hdai_route_embed')):
            params.set_param(
                'hdai.route.%s' % scenario,
                str(int(self[field_name].id or 0)))
