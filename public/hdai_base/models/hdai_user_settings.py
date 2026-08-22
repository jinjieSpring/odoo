# -*- coding: utf-8 -*-
"""Per-user AI assistant preferences (separate table)."""

from odoo import api, fields, models


class HdaiUserSettings(models.Model):
    _name = 'hdai.user.settings'
    _description = 'AI Assistant User Settings'
    _rec_name = 'user_id'

    user_id = fields.Many2one(
        'res.users', string='User', required=True,
        ondelete='cascade', index=True)
    language_mode = fields.Selection([
        ('auto', 'Auto-detect'),
        ('system', 'Follow System Language'),
        ('specific', 'Specific Language'),
    ], string='AI Assistant Language', default='auto')
    language = fields.Char(string='AI Assistant Specific Language')
    reasoning_strength = fields.Selection([
        ('none', 'Off'),
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ], string='Thinking Strength', default='none')
    web_search_enabled = fields.Boolean(
        string='Enable Web Search by Default', default=False)
    streaming = fields.Boolean(string='Streaming by Default', default=True)
    default_prompt_id = fields.Many2one(
        'hdai.prompt', string='Default Prompt', ondelete='set null')
    attach_context = fields.Boolean(
        string='Attach Current Record Context by Default', default=True)
    # Chat window layout preferences (persisted with the user settings).
    sidebar_collapsed = fields.Boolean(
        string='Collapse the AI Assistant Sidebar', default=False)
    grid_sessions_collapsed = fields.Boolean(
        string='Collapse the Session History Grid', default=False)
    grid_knowledge_collapsed = fields.Boolean(
        string='Collapse the Knowledge Base Grid', default=False)
    grid_sessions_height = fields.Integer(
        string='Session History Grid Height', default=0,
        help='Height in pixels of the session history grid; 0 means auto.')
    grid_knowledge_height = fields.Integer(
        string='Knowledge Base Grid Height', default=0,
        help='Height in pixels of the knowledge base grid; 0 means auto.')
    sidebar_width = fields.Integer(
        string='AI Assistant Sidebar Width', default=260,
        help='Width in pixels of the chat sidebar.')

    _unique_user = models.Constraint(
        'unique(user_id)',
        'Each user can only have one AI assistant settings record.')

    @api.model
    def _get_for_user(self, user=None):
        user = user or self.env.user
        settings = self.search([('user_id', '=', user.id)], limit=1)
        if settings:
            return settings
        default_model = self.env['hdai.model']._get_default_model()
        return self.create({
            'user_id': user.id,
            'reasoning_strength': (
                default_model.thinking_strength if default_model else 'none'),
        })
