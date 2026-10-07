# -*- coding: utf-8 -*-
# Part of Bizople Solutions Pvt. Ltd.
# Licensed under the Bizople Proprietary License v1.0.
# Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

from odoo import models, fields, api

class Bookmarklink(models.Model):
	_name = 'bookmark.link'
	_description = "Bookmark Link"

	name = fields.Char("Name")
	title = fields.Char("Title")
	url = fields.Char("URL")
	user_id = fields.Many2one('res.users')