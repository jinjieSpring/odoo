# -*- coding: utf-8 -*-
# Part of Bizople Solutions Pvt. Ltd.
# Licensed under the Bizople Proprietary License v1.0.
# Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

from odoo import models, fields

class MailFirebase(models.Model):
    _name = "mail.firebase"
    _description = "Mail Firebase"

    user_id = fields.Many2one('res.users', string="User", readonly=True)
    os = fields.Char(string="Device OS", readonly=True)
    token = fields.Char(string="Device firebase token", readonly=True)

    _uniq_token = models.Constraint(
        'unique(token, os, user_id)',
        'Token must be unique per user!',
    )
    _uniq_token_not_false = models.Constraint(
        'CHECK (token IS NOT NULL)',
        'Token must be not null!',
    )

    def remove_firebase_record(self,device_token,userid):
        firebase_obj = self.env['mail.firebase'].search([('token','=',device_token),('user_id','=',int(userid))])
        if firebase_obj:
            firebase_obj.unlink()