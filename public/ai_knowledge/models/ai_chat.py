# -*- coding: utf-8 -*-
from odoo import models


class AiChat(models.AbstractModel):
    _inherit = 'ai.chat'

    def defaults(self):
        values = super().defaults()
        values['has_knowledge'] = True
        values['knowledge_documents'] = self.knowledge_documents()
        return values

    def user_settings(self):
        values = super().user_settings()
        values['has_knowledge'] = True
        return values

    def session_payload(self, session):
        payload = super().session_payload(session)
        payload['session'].update({
            'knowledge_enabled': session.knowledge_enabled,
            'knowledge_top_k': session.knowledge_top_k,
            'knowledge_document_ids': session.knowledge_document_ids.ids,
        })
        return payload

    def set_options(self, session, options):
        options = options or {}
        if session:
            vals = {}
            if 'knowledge_enabled' in options:
                vals['knowledge_enabled'] = bool(options['knowledge_enabled'])
            if 'knowledge_top_k' in options:
                vals['knowledge_top_k'] = int(options['knowledge_top_k'] or 5)
            if 'knowledge_document_ids' in options:
                vals['knowledge_document_ids'] = [(6, 0, self._parse_document_ids(
                    options['knowledge_document_ids']))]
            if vals:
                session.write(vals)
        return super().set_options(session, options)
