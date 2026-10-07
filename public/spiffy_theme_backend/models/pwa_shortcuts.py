# -*- coding: utf-8 -*-
# Part of Bizople Solutions Pvt. Ltd.
# Licensed under the Bizople Proprietary License v1.0.
# Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

from odoo import api, fields, models, _

class PWAshortcuts(models.Model):
    _name = 'pwa.shortcuts'
    _description = "PWA Shortcuts"

    name = fields.Char("Name", required=True)
    short_name = fields.Char("Short Name", required=True)
    url = fields.Char("URL", required=True, default='/')
    description = fields.Char("Description", required=True)
    image_192_shortcut = fields.Binary('Image 192px', readonly=False)