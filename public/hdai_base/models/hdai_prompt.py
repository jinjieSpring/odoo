# -*- coding: utf-8 -*-
from odoo import fields, models


class HdaiPrompt(models.Model):
    _name = 'hdai.prompt'
    _description = 'AI Prompt'
    _order = 'scope, sequence, name'

    name = fields.Char(string='Name', required=True, translate=True)
    content = fields.Text(string='Content', required=True)
    description = fields.Text(string='Description')
    sequence = fields.Integer(string='Sequence', default=10)
    sequence = fields.Integer(string='Sequence', default=10)
    version = fields.Integer(string='Version', default=1)
    is_default = fields.Boolean(string='Default Prompt', default=False)
    active = fields.Boolean(string='Active', default=True)

    def write(self, vals):
        """Bump the version when the content changes."""
        if 'content' in vals:
            for record in self:
                record.version += 1
            vals.pop('version', None)
        return super().write(vals)
    scope = fields.Selection([
        ('system', 'Default Prompt'),
        ('user', 'Personal Prompt'),
    ], string='Scope', required=True, default='user',
        help='Default Prompts are maintained by the administrator and '
             'available to every user; Personal Prompts are user-specific.')
    user_id = fields.Many2one(
        'res.users', string='User',
        default=lambda self: self.env.user, ondelete='cascade')
