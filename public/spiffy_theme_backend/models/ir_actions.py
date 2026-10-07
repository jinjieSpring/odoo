# -*- coding: utf-8 -*-
# Part of Bizople Solutions Pvt. Ltd.
# Licensed under the Bizople Proprietary License v1.0.
# Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

from odoo import models, api


class IrActionsActions(models.Model):
    _inherit = 'ir.actions.actions'

    @api.model
    def get_bindings(self, model_name):
        result = super().get_bindings(model_name)

        if not result.get('report'):
            return result

        report_ids = [a['id'] for a in result['report']]
        reports = self.env['ir.actions.report'].sudo().search_read(
            [('id', 'in', report_ids)],
            ['report_name', 'report_type'],
        )
        report_map = {r['id']: r for r in reports}

        enriched = []
        for action in result['report']:
            extra = report_map.get(action['id'], {})
            enriched.append(dict(
                action,
                report_name=extra.get('report_name', ''),
                report_type=extra.get('report_type', ''),
            ))
        result['report'] = enriched
        return result
