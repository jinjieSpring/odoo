# -*- coding: utf-8 -*-
"""Vector store ABC with a PGVector backend and a cosine fallback."""

import logging
import math

from odoo import models

_logger = logging.getLogger(__name__)


def cosine_similarity(left, right):
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = math.sqrt(sum(a * a for a in left))
    norm_right = math.sqrt(sum(b * b for b in right))
    if not norm_left or not norm_right:
        return 0.0
    return dot / (norm_left * norm_right)


class VectorStore:
    """Abstract vector index. Implementations receive an ``env``."""

    def upsert(self, env, chunks):
        raise NotImplementedError

    def search(self, env, embedding, top_k=5, document_ids=None, knowledge_ids=None):
        raise NotImplementedError

    def delete(self, env, chunk_ids):
        raise NotImplementedError


class CosineFallbackStore(VectorStore):
    """In-Python cosine over the JSON ``embedding`` field (dev / tests)."""

    def upsert(self, env, chunks):
        return True

    def delete(self, env, chunk_ids):
        return True

    def search(self, env, embedding, top_k=5, document_ids=None, knowledge_ids=None):
        domain = [('embedding', '!=', False)]
        if document_ids:
            domain.append(('document_id', 'in', list(document_ids)))
        if knowledge_ids:
            domain.append(('knowledge_id', 'in', list(knowledge_ids)))
        chunks = env['ai.knowledge.chunk'].search(domain)
        scored = []
        for chunk in chunks:
            vector = chunk._embedding_vector()
            if not vector:
                continue
            scored.append((cosine_similarity(embedding, vector), chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [{
            'id': chunk.id,
            'content': chunk.content,
            'source_document': chunk.document_id.name,
            'document_id': chunk.document_id.id,
            'page': chunk.page,
            'citation': '[SOURCE:%s]' % chunk.document_id.id,
            'score': score,
        } for score, chunk in scored[:top_k]]


class PgVectorStore(VectorStore):
    """PostgreSQL ``vector`` column when the extension is available."""

    def _has_extension(self, env):
        env.cr.execute(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        return bool(env.cr.fetchone())

    def _ensure_column(self, env):
        if not self._has_extension(env):
            return False
        env.cr.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'ai_knowledge_chunk' "
            "AND column_name = 'embedding_vec'")
        if env.cr.fetchone():
            return True
        env.cr.execute('SAVEPOINT ai_vector_col')
        try:
            env.cr.execute(
                'ALTER TABLE ai_knowledge_chunk '
                'ADD COLUMN embedding_vec vector')
            env.cr.execute('RELEASE SAVEPOINT ai_vector_col')
            return True
        except Exception:  # noqa: BLE001
            env.cr.execute('ROLLBACK TO SAVEPOINT ai_vector_col')
            _logger.warning(
                'ai_base: could not add embedding_vec column; using cosine fallback')
            return False

    def upsert(self, env, chunks):
        if not self._ensure_column(env):
            return False
        for chunk in chunks:
            vector = chunk._embedding_vector()
            if not vector:
                continue
            literal = '[' + ','.join(str(float(v)) for v in vector) + ']'
            env.cr.execute(
                'UPDATE ai_knowledge_chunk SET embedding_vec = %s::vector '
                'WHERE id = %s',
                (literal, chunk.id))
        return True

    def delete(self, env, chunk_ids):
        return True

    def search(self, env, embedding, top_k=5, document_ids=None, knowledge_ids=None):
        if not self._ensure_column(env):
            return CosineFallbackStore().search(
                env, embedding, top_k=top_k, document_ids=document_ids,
                knowledge_ids=knowledge_ids)
        literal = '[' + ','.join(str(float(v)) for v in embedding) + ']'
        clauses = ['embedding_vec IS NOT NULL']
        params = [literal]
        if document_ids:
            clauses.append('document_id = ANY(%s)')
            params.append(list(document_ids))
        if knowledge_ids:
            clauses.append('knowledge_id = ANY(%s)')
            params.append(list(knowledge_ids))
        where = ' AND '.join(clauses)
        env.cr.execute(
            'SELECT id, 1 - (embedding_vec <=> %s::vector) AS score '
            'FROM ai_knowledge_chunk '
            'WHERE ' + where + ' '
            'ORDER BY embedding_vec <=> %s::vector LIMIT %s',
            tuple(params + [literal, top_k]),
        )
        rows = env.cr.fetchall()
        if not rows:
            return []
        chunks = env['ai.knowledge.chunk'].browse([row[0] for row in rows])
        score_map = {row[0]: row[1] for row in rows}
        return [{
            'id': chunk.id,
            'content': chunk.content,
            'source_document': chunk.document_id.name,
            'document_id': chunk.document_id.id,
            'page': chunk.page,
            'citation': '[SOURCE:%s]' % chunk.document_id.id,
            'score': score_map.get(chunk.id) or 0.0,
        } for chunk in chunks]


class ChromaStore(VectorStore):
    """Optional Chroma backend. Falls back to cosine when chroma is missing."""

    def _client(self):
        try:
            import chromadb  # noqa: PLC0415
        except ImportError:
            return None
        return chromadb.Client()

    def upsert(self, env, chunks):
        client = self._client()
        if client is None:
            return CosineFallbackStore().upsert(env, chunks)
        collection = client.get_or_create_collection('ai_base')
        ids, embeddings, documents, metadatas = [], [], [], []
        for chunk in chunks:
            vector = chunk._embedding_vector()
            if not vector:
                continue
            ids.append(str(chunk.id))
            embeddings.append(vector)
            documents.append(chunk.content or '')
            metadatas.append({
                'document_id': chunk.document_id.id,
                'knowledge_id': chunk.knowledge_id.id,
            })
        if ids:
            collection.upsert(
                ids=ids, embeddings=embeddings,
                documents=documents, metadatas=metadatas)
        return True

    def delete(self, env, chunk_ids):
        client = self._client()
        if client is None:
            return True
        collection = client.get_or_create_collection('ai_base')
        collection.delete(ids=[str(cid) for cid in chunk_ids])
        return True

    def search(self, env, embedding, top_k=5, document_ids=None, knowledge_ids=None):
        client = self._client()
        if client is None:
            return CosineFallbackStore().search(
                env, embedding, top_k=top_k, document_ids=document_ids,
                knowledge_ids=knowledge_ids)
        collection = client.get_or_create_collection('ai_base')
        where = None
        if document_ids:
            where = {'document_id': {'$in': list(document_ids)}}
        result = collection.query(
            query_embeddings=[embedding], n_results=top_k, where=where)
        ids = (result.get('ids') or [[]])[0]
        docs = (result.get('documents') or [[]])[0]
        distances = (result.get('distances') or [[]])[0]
        metadatas = (result.get('metadatas') or [[]])[0]
        hits = []
        for index, chunk_id in enumerate(ids):
            meta = metadatas[index] if index < len(metadatas) else {}
            hits.append({
                'id': int(chunk_id),
                'content': docs[index] if index < len(docs) else '',
                'source_document': '',
                'document_id': meta.get('document_id'),
                'page': False,
                'citation': '[SOURCE:%s]' % meta.get('document_id'),
                'score': 1 - (distances[index] if index < len(distances) else 0),
            })
        return hits


def get_vector_store(env, store_type='pgvector'):
    if store_type == 'chroma':
        return ChromaStore()
    store = PgVectorStore()
    try:
        if store._has_extension(env):
            return store
    except Exception:  # noqa: BLE001
        _logger.warning(
            'ai_base: pgvector unavailable, using cosine fallback',
            exc_info=True)
    return CosineFallbackStore()


class AiVectorStoreHelper(models.AbstractModel):
    _name = 'ai.vector.store'
    _description = 'AI Vector Store Helper'

    def _get_store(self, store_type='pgvector'):
        return get_vector_store(self.env, store_type)
