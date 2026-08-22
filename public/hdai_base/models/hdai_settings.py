# -*- coding: utf-8 -*-
"""User-facing settings helper for hdai_base (default provider/model)."""

from odoo import api, models


class HdaiSettings(models.Model):
    _name = 'hdai.settings'
    _description = 'HD AI Settings'

    @api.model
    def _get_defaults(self):
        params = self.env['ir.config_parameter'].sudo()
        provider_id = int(params.get_param(
            'hdai.default_provider_id', '0') or 0)
        model_id = int(params.get_param(
            'hdai.default_model_id', '0') or 0)
        # Stale parameters may survive module uninstalls and point at
        # records that no longer exist; never feed them back into the UI
        # (a dangling id would break res.config.settings creation).
        if provider_id and not self.env['hdai.provider'].browse(
                provider_id).exists():
            provider_id = 0
        if model_id and not self.env['hdai.model'].browse(
                model_id).exists():
            model_id = 0
        return {
            'provider_id': provider_id,
            'model_id': model_id,
        }

    @api.model
    def _set_defaults(self, provider_id, model_id):
        params = self.env['ir.config_parameter'].sudo()
        params.set_param('hdai.default_provider_id', str(int(provider_id or 0)))
        params.set_param('hdai.default_model_id', str(int(model_id or 0)))

    @api.model
    def action_set_defaults(self, provider_id, model_id):
        """Public entry point used by the web client to pick the default
        provider/model."""
        self._set_defaults(provider_id, model_id)
        return True
