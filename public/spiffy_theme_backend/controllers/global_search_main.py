# -*- coding: utf-8 -*-
# Part of Bizople Solutions Pvt. Ltd.
# Licensed under the Bizople Proprietary License v1.0.
# Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

from odoo import http
from odoo.http import request

class SpiffySpaceSearch(http.Controller):

    @http.route('/spiffy/global/search', type='jsonrpc', auth='user')
    def colon_search(self, search):
        results = []
        search = search.strip().lower()
        installed_models = request.env['ir.model'].sudo().search([])
        for model in installed_models:
            if len(results) >= 10:
                break

            try:
                Model = request.env[model.model]
                if not hasattr(Model, 'name_search'):
                    continue
                Model.check_access('read')
                domain = ['|', ('name', 'ilike', search), ('display_name', 'ilike', search)]
                records = Model.search(domain, limit=5)
                for rec in records:
                    results.append({
                        'model': model.model,
                        'model_name': model.name,
                        'id': rec.id,
                        'display_name': rec.display_name,
                        'action': f"/web#model={model.model}&id={rec.id}&view_type=form",
                    })
                    if len(results) >= 10:
                        break
            except Exception:
                continue
        return results
