# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase


class AiBaseCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.env['ir.config_parameter'].sudo().set_param(
            'ai_base.rate_limit_user_per_minute', '1000')
        self.env['ir.config_parameter'].sudo().set_param(
            'ai_base.rate_limit_global_per_minute', '1000')
        self.provider = self.env['ai.provider'].create({
            'name': 'Test OpenAI',
            'provider_type': 'openai_compat',
            'endpoint': 'https://api.test.openai/v1',
            'api_key': 'sk-abcdef1234567890',
        })
        self.model = self.env['ai.model'].create({
            'name': 'Test Model',
            'code': 'gpt-4o-mini',
            'provider_id': self.provider.id,
            'model_kind': 'chat',
            'model_name_remote': 'gpt-4o-mini',
            'max_context_tokens': 128000,
            'max_tokens_default': 100,
        })
        self.embed_model = self.env['ai.model'].create({
            'name': 'Test Embed',
            'code': 'text-embedding-test',
            'provider_id': self.provider.id,
            'model_kind': 'embedding',
            'model_name_remote': 'text-embedding-3-small',
        })
        self.model.action_set_as_default('chat')
        self.embed_model.action_set_as_default('embed')
