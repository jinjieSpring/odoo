# -*- coding: utf-8 -*-
# Part of Bizople Solutions Pvt. Ltd.
# Licensed under the Bizople Proprietary License v1.0.
# Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

from odoo import models, fields

class GoogleFontlink(models.Model):
	_name = 'google.font.family'
	_description = "Google Font Link"

	name = fields.Char("Name")
	url = fields.Char("URL")
	config_id = fields.Many2one('backend.config', string="Backend Config")
	is_selected = fields.Boolean("Is Selected", default=False)
	user_id = fields.Many2one('res.users')