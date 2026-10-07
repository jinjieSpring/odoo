# -*- coding: utf-8 -*-
# Part of Bizople Solutions Pvt. Ltd.
# Licensed under the Bizople Proprietary License v1.0.
# Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

from odoo import models, fields, api

class FavoriteApps(models.Model):
    _name = "favorite.apps"
    _description = "Favourite Apps"

    name = fields.Char("Name")
    app_id = fields.Char("App Id")
    app_xmlid = fields.Char("App XML Id")
    app_actionid = fields.Char("App Action Id")
    user_id = fields.Many2one('res.users')