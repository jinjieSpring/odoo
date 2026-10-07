# -*- coding: utf-8 -*-
# Part of Bizople Solutions Pvt. Ltd.
# Licensed under the Bizople Proprietary License v1.0.
# Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

from odoo import models, fields, api

class User(models.Model):
    _inherit = "res.users"

    app_ids = fields.One2many('favorite.apps', 'user_id',string="Favourite Apps")
    bookmark_ids = fields.One2many('bookmark.link', 'user_id',string="Bookmark Links")
    dark_mode = fields.Boolean(string="Is dark Mode Active", default=False)
    vertical_sidebar_pinned = fields.Boolean(string="Pinned Sidebar", default=True)
    backend_theme_config = fields.Many2one('backend.config', string="Backend Config", copy=False)
    enable_todo_list = fields.Boolean(string="Enable To Do List", default=True)
    todo_list_ids = fields.One2many('todo.list', 'user_id', string="To Do List")
    mail_firebase_tokens = fields.One2many("mail.firebase", "user_id", string="Android device(tokens)")
    bookmark_panel = fields.Boolean(string="Show right bookmark panel", default=True)
    #Unused Fields
    table_color = fields.Boolean(string="Is Body Color")
    tool_color_id = fields.Char(string="Tool Color")

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + ['enable_todo_list']

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ['enable_todo_list']

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('backend_theme_config'):

                backend_config = self.env['backend.config'].create({
                    'light_primary_bg_color': '#0097a7',
                    'light_primary_text_color': '#ffffff',
                })
                vals['backend_theme_config'] = backend_config.id
        return super().create(vals_list)