# -*- coding: utf-8 -*-
# Part of Bizople Solutions Pvt. Ltd.
# Licensed under the Bizople Proprietary License v1.0.
# Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

from odoo import models
from odoo.http import request

class Http(models.AbstractModel):
    _inherit = 'ir.http'

    def session_info(self):
        # Show company change option even if single company available
        res = super().session_info()
        company = self.env.company
        # Do not embed image_1920 here. It is a large binary and the
        # backend already loads the avatar through /web/image.
        res.update({
            'bg_color': request.session.get('bg_color'),
            'spiffy_installed': True,
        })

        if self.env.user.has_group('base.group_user'):
            res.update({
                "display_switch_company_menu": True,
                "prevent_auto_save_warning_msg": company.prevent_auto_save_warning or '',
                "prevent_auto_save": company.prevent_auto_save,
                "enable_right_click_menu": company.enable_right_click_menu,
            })
        return res