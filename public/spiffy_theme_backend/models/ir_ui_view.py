# -*- coding: utf-8 -*-
# Part of Bizople Solutions Pvt. Ltd.
# Licensed under the Bizople Proprietary License v1.0.
# Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

from odoo import models


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    def _get_view_info(self):
        # call parent dict first
        view_info = super()._get_view_info()
        # update only selected
        view_info.update({
            'list': {'icon': 'ri ri-list-unordered'},
            'graph': {'icon': 'ri ri-line-chart-line'},
            'pivot': {'icon': 'ri ri-layout-3-line'},
            'kanban': {'icon': 'ri ri-bar-chart-horizontal-line rotate-kanban-icon'},
            'calendar': {'icon': 'ri ri-calendar-line'},
            'search': {'icon': 'ri ri-search-2-line'},
            'activity': {'icon': 'ri ri-timer-line'},
            'hierarchy': {'icon': 'oi oi-search'},
        })
        return view_info

