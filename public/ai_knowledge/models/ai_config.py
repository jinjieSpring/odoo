# -*- coding: utf-8 -*-
from odoo import api, fields, models


class AiConfig(models.TransientModel):
    _inherit = 'ai.config'

    embed_model_id = fields.Many2one(
        'ai.model', string='Default Embedding Model',
        domain="[('model_kind', '=', 'embedding'), ('is_active', '=', True), "
               "('provider_id.is_active', '=', True)]")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        params = self.env['ir.config_parameter'].sudo()
        model_id = int(params.get_param('ai.route.embed', '0') or 0)
        values['embed_model_id'] = (
            model_id if model_id and self.env['ai.model'].browse(model_id).exists()
            else False)
        return values

    def action_save(self):
        result = super().action_save()
        self.ensure_one()
        embed_id = int(self.embed_model_id.id or 0)
        self.env['ir.config_parameter'].sudo().set_param(
            'ai.route.embed', str(embed_id))
        if self.embed_model_id:
            self.embed_model_id.action_set_as_default('embed')
        return result
