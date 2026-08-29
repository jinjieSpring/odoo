# -*- coding: utf-8 -*-
import json

from odoo import _, models

from odoo.addons.ai_knowledge.models.ai_vector_store import get_vector_store


class AiBaseService(models.AbstractModel):
    _inherit = 'ai.chat.service'

    def rag_chat(
        self, query, knowledge_ids=None, document_ids=None, top_k=5,
        rerank=None, prompt_key='rag.context', **kwargs
    ):
        retrieved = self.retrieve(
            query, top_k=top_k, document_ids=document_ids,
            knowledge_ids=knowledge_ids)
        options = dict(kwargs.pop('options', None) or {})
        rag_text = self._format_rag(retrieved, query, prompt_key)
        if rag_text:
            options['system_prompt'] = '\n\n'.join(
                part for part in (options.get('system_prompt'), rag_text) if part)
        result = self.chat(query, options=options, scenario='rag', **kwargs)
        result['rag_sources'] = retrieved
        session = kwargs.get('session')
        if session:
            last = session.message_ids.filtered(
                lambda m: m.role == 'assistant')[-1:]
            if last:
                last.rag_sources = retrieved
        log = self.env['ai.request.log'].sudo().search([
            ('user_id', '=', self.env.user.id),
            ('scenario_key', '=', 'rag'),
        ], order='id desc', limit=1)
        if log:
            log.write({
                'request_type': 'rag',
                'rag_snippets': json.dumps(retrieved, ensure_ascii=False)[:4000],
            })
        return result

    def retrieve(self, query, top_k=5, document_ids=None, knowledge_ids=None, model=None):
        query = (query or '').strip()
        if not query:
            return []
        kbs = self.env['ai.knowledge.base']
        kb_ids = list(knowledge_ids or [])
        if kb_ids:
            kbs = self.env['ai.knowledge.base'].browse(kb_ids).exists()
            if kbs and not model:
                model = kbs[0].embedding_model_id
        try:
            vectors = self.embedding([query], model=model)
        except Exception:  # noqa: BLE001
            return []
        if not vectors or not vectors[0]:
            return []
        domain_ids = list(document_ids or [])
        store_type = 'pgvector'
        if kbs:
            store_type = kbs[0].vector_store_type or 'pgvector'
            if not domain_ids:
                domain_ids = self.env['ai.knowledge.document'].search([
                    ('knowledge_id', 'in', kbs.ids),
                    ('state', '=', 'ready'),
                    ('active', '=', True),
                ]).ids
        hits = get_vector_store(self.env, store_type).search(
            self.env, vectors[0], top_k=top_k or 5,
            document_ids=domain_ids or None,
            knowledge_ids=kb_ids or None)
        if kbs and kbs[0].rerank and len(hits) > 1:
            hits = sorted(hits, key=lambda item: item.get('score') or 0, reverse=True)
        return hits

    def _format_rag(self, retrieved, query, prompt_key):
        if not retrieved:
            return ''
        rag = self.render_prompt(prompt_key, {'items': retrieved, 'query': query})
        if rag:
            return rag
        lines = [_('Relevant knowledge:')]
        lines += [
            '- %s p.%s [%s] %s' % (
                item.get('citation') or '',
                item.get('page') or '-',
                item.get('source_document') or '',
                item.get('content') or '')
            for item in retrieved
        ]
        return '\n'.join(lines)

    def _knowledge_system_parts(self, session, query):
        if not session or not session.knowledge_enabled or not query:
            return []
        retrieved = self.retrieve(
            query,
            top_k=session.knowledge_top_k or 5,
            document_ids=session.knowledge_document_ids.ids or None,
            knowledge_ids=session.knowledge_ids.ids or None,
        )
        rag = self._format_rag(retrieved, query, 'rag.context')
        return [rag] if rag else []
