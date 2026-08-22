# -*- coding: utf-8 -*-
import json
from unittest.mock import patch

from odoo.addons.ai_base.models.ai_vector_store import (
    CosineFallbackStore,
    PgVectorStore,
    cosine_similarity,
    get_vector_store,
)
from odoo.addons.ai_base.tests.common import AiBaseCase


class TestKnowledge(AiBaseCase):
    def _document(self, text='Expense policy: meals are reimbursed.'):
        knowledge = self.env['ai.knowledge.base'].create({
            'name': 'Policies',
            'embedding_model_id': self.embed_model.id,
        })
        return self.env['ai.knowledge.document'].create({
            'name': 'Policy',
            'knowledge_id': knowledge.id,
            'content': text,
        })

    def test_empty_kb_returns_nothing(self):
        items = self.env['ai.base.service'].retrieve('anything')
        self.assertEqual(items, [])

    def test_chunk_strategies(self):
        from odoo.addons.ai_base.models.ai_knowledge_base import (
            _split_fixed, _split_heading, _split_semantic,
        )
        text = '# Title\n\nHello world.\n\n## Two\n\nMore text here.'
        self.assertTrue(_split_fixed(text, size=20, overlap=4))
        self.assertTrue(_split_semantic(text))
        self.assertGreaterEqual(len(_split_heading(text)), 2)

    def test_cosine_scoped_search(self):
        document = self._document()
        other = self._document('Unrelated weather notes.')
        document.chunk_ids.unlink()
        other.chunk_ids.unlink()
        self.env['ai.knowledge.chunk'].create({
            'document_id': document.id,
            'knowledge_id': document.knowledge_id.id,
            'content': document.content,
            'embedding': json.dumps([1.0, 0.0, 0.0]),
        })
        self.env['ai.knowledge.chunk'].create({
            'document_id': other.id,
            'knowledge_id': other.knowledge_id.id,
            'content': other.content,
            'embedding': json.dumps([0.0, 1.0, 0.0]),
        })
        store = CosineFallbackStore()
        hits = store.search(
            self.env, [1.0, 0.0, 0.0], top_k=1,
            document_ids=[document.id])
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['document_id'], document.id)
        self.assertGreater(hits[0]['score'], 0.9)

    def test_index_uses_embed_and_fallback(self):
        document = self._document()
        with patch.object(
                type(self.env['ai.base.service']), 'embedding',
                return_value=[[0.1, 0.2, 0.3]]):
            document.action_index()
        self.assertEqual(document.state, 'ready')
        self.assertTrue(document.chunk_ids)
        self.assertTrue(document.chunk_ids[0].embedding)

    def test_missing_extension_uses_cosine(self):
        store = PgVectorStore()
        with patch.object(PgVectorStore, '_has_extension', return_value=False):
            self.assertFalse(store._ensure_column(self.env))
            self.assertIsInstance(get_vector_store(self.env), CosineFallbackStore)
        self.assertEqual(cosine_similarity([1, 0], [1, 0]), 1.0)
        self.assertEqual(cosine_similarity([1, 0], [0, 1]), 0.0)

    def test_retrieve_injects_into_chat(self):
        document = self._document()
        self.env['ai.knowledge.chunk'].create({
            'document_id': document.id,
            'knowledge_id': document.knowledge_id.id,
            'content': document.content,
            'embedding': json.dumps([1.0, 0.0]),
        })
        session = self.env['ai.chat.session'].create({
            'name': 'KB',
            'knowledge_enabled': True,
            'knowledge_document_ids': [(6, 0, [document.id])],
        })
        captured = {}

        def fake_chat(this, model, messages, options=None):
            captured['messages'] = messages
            return {
                'content': 'meals are reimbursed',
                'reasoning': '',
                'tool_calls': [],
                'usage': {
                    'prompt_tokens': 1,
                    'completion_tokens': 1,
                    'total_tokens': 2,
                },
            }

        with patch.object(
                type(self.env['ai.base.service']), 'embedding',
                return_value=[[1.0, 0.0]]), patch(
                'odoo.addons.ai_base.models.ai_provider.OpenAICompatibleAdapter.chat_completion',
                fake_chat):
            self.env['ai.base.service'].chat(
                'What about meals?', session=session)
        system = ' '.join(
            msg['content'] for msg in captured['messages']
            if msg['role'] == 'system')
        self.assertIn('meals', system.lower())
