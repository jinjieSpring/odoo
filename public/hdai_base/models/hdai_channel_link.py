# -*- coding: utf-8 -*-
"""Link between a Discuss channel (including Livechat channels) and the AI
session used to answer inside it."""

from odoo import fields, models


class HdaiChannelLink(models.Model):
    _name = 'hdai.channel.link'
    _description = 'AI Channel Link'
    _order = 'write_date desc, id desc'

    channel_id = fields.Many2one(
        'discuss.channel', string='Channel', required=True,
        ondelete='cascade', index=True)
    session_id = fields.Many2one(
        'hdai.session', string='AI Session', ondelete='cascade')
    agent_id = fields.Many2one('hdai.agent', string='AI Agent')
    bot_partner_id = fields.Many2one(
        'res.partner', string='Bot Partner', required=True)
    active = fields.Boolean(string='Active', default=True)
    last_message_id = fields.Integer(
        string='Last Processed Message',
        help='Highest mail.message id already processed on the channel.')
    last_processed_dt = fields.Datetime(string='Last Processed')
    turn_count = fields.Integer(string='Turn Count', default=0)
    state = fields.Selection([
        ('idle', 'Idle'),
        ('running', 'Running'),
    ], string='State', default='idle')
