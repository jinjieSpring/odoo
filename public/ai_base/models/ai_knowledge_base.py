# -*- coding: utf-8 -*-
import io
import json
import logging
import re
import zipfile
from xml.etree import ElementTree as ET

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ai_base.models.ai_vector_store import get_vector_store

_logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r'(?m)^(#{1,6}\s+.+$|.+\n[=-]{3,}\s*$)')


def _split_fixed(text, size=800, overlap=120):
    text = (text or '').strip()
    if not text:
        return []
    chunks = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + size, length)
        chunks.append(text[start:end].strip())
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return [chunk for chunk in chunks if chunk]


def _split_semantic(text):
    paragraphs = re.split(r'\n\s*\n', text or '')
    chunks, buffer = [], []
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        buffer.append(paragraph)
        joined = '\n\n'.join(buffer)
        if len(joined) >= 600:
            chunks.append(joined)
            buffer = []
    if buffer:
        chunks.append('\n\n'.join(buffer))
    return chunks or _split_fixed(text)


def _split_heading(text):
    text = text or ''
    positions = [0] + [match.start() for match in _HEADING_RE.finditer(text)] + [len(text)]
    chunks = []
    for index in range(len(positions) - 1):
        piece = text[positions[index]:positions[index + 1]].strip()
        if piece:
            chunks.append(piece)
    return chunks or _split_semantic(text)


def _extract_txt(raw):
    for encoding in ('utf-8', 'utf-8-sig', 'gbk', 'latin-1'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def _extract_docx(raw):
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            xml = archive.read('word/document.xml')
    except Exception as exc:  # noqa: BLE001
        raise UserError(_('Could not read the docx file: %s') % exc) from exc
    tree = ET.fromstring(xml)
    ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    texts = [node.text for node in tree.findall('.//w:t', ns) if node.text]
    return '\n'.join(texts)


def _extract_pdf(raw):
    try:
        from pypdf import PdfReader  # noqa: PLC0415
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # noqa: PLC0415
        except ImportError as exc:
            raise UserError(_(
                'PDF parsing requires the pypdf package on the server.')) from exc
    reader = PdfReader(io.BytesIO(raw))
    pages = []
    for index, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ''
        if text.strip():
            pages.append((index, text))
    return pages


class AiKnowledgeBase(models.Model):
    _name = 'ai.knowledge.base'
    _description = 'AI Knowledge Base'
    _order = 'name'
    _check_company_auto = True

    name = fields.Char(string='Name', required=True)
    description = fields.Text(string='Description')
    embedding_model_id = fields.Many2one(
        'ai.model', string='Embedding Model',
        domain="[('model_kind', '=', 'embedding'), ('is_active', '=', True)]")
    vector_store_type = fields.Selection([
        ('pgvector', 'PGVector'),
        ('chroma', 'Chroma'),
    ], string='Vector Store', default='pgvector', required=True)
    chunk_strategy = fields.Selection([
        ('fixed', 'Fixed Length'),
        ('semantic', 'Semantic / Paragraph'),
        ('heading', 'Heading Split'),
    ], string='Chunk Strategy', default='fixed', required=True)
    chunk_size = fields.Integer(string='Chunk Size', default=800)
    chunk_overlap = fields.Integer(string='Chunk Overlap', default=120)
    rerank = fields.Boolean(string='Enable Rerank', default=False)
    is_active = fields.Boolean(string='Active', default=True)
    company_id = fields.Many2one(
        'res.company', string='Company', required=True, index=True,
        default=lambda self: self.env.company)
    document_ids = fields.One2many(
        'ai.knowledge.document', 'knowledge_id', string='Documents')
    document_count = fields.Integer(
        compute='_compute_document_count', string='Documents')

    @api.depends('document_ids')
    def _compute_document_count(self):
        data = self.env['ai.knowledge.document']._read_group(
            [('knowledge_id', 'in', self.ids)],
            ['knowledge_id'], ['knowledge_id:count'])
        count_map = {kb.id: count for kb, count in data}
        for kb in self:
            kb.document_count = count_map.get(kb.id, 0)

    def action_index_all(self):
        for kb in self:
            kb.document_ids.filtered(
                lambda d: d.state in ('pending', 'parsed', 'error')
            ).action_index()
        return True


class AiKnowledgeDocument(models.Model):
    _name = 'ai.knowledge.document'
    _description = 'AI Knowledge Document'
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char(string='Name', required=True)
    knowledge_id = fields.Many2one(
        'ai.knowledge.base', string='Knowledge Base', required=True,
        ondelete='cascade', index=True)
    company_id = fields.Many2one(
        related='knowledge_id.company_id', store=True, readonly=True)
    attachment_id = fields.Many2one(
        'ir.attachment', string='Attachment', ondelete='set null')
    mimetype = fields.Char(related='attachment_id.mimetype', readonly=True)
    content = fields.Text(string='Extracted Text')
    state = fields.Selection([
        ('pending', 'Pending Parse'),
        ('parsed', 'Parsed'),
        ('error', 'Parse Failed'),
        ('ready', 'Vectorized'),
    ], string='Status', default='pending', required=True, index=True)
    error_message = fields.Char(string='Error')
    chunk_ids = fields.One2many(
        'ai.knowledge.chunk', 'document_id', string='Chunks')
    chunk_count = fields.Integer(compute='_compute_chunk_count', string='Chunks')
    active = fields.Boolean(string='Active', default=True)

    @api.depends('chunk_ids')
    def _compute_chunk_count(self):
        data = self.env['ai.knowledge.chunk']._read_group(
            [('document_id', 'in', self.ids)],
            ['document_id'], ['document_id:count'])
        count_map = {doc.id: count for doc, count in data}
        for doc in self:
            doc.chunk_count = count_map.get(doc.id, 0)

    def _extract_text(self):
        self.ensure_one()
        if self.content:
            return [(False, self.content)]
        attachment = self.attachment_id
        if not attachment:
            return []
        raw = attachment.raw or b''
        name = (attachment.name or '').lower()
        mimetype = (attachment.mimetype or '').lower()
        if name.endswith(('.txt', '.md', '.markdown')) or mimetype.startswith('text/'):
            return [(False, _extract_txt(raw))]
        if name.endswith('.docx') or 'wordprocessingml' in mimetype:
            return [(False, _extract_docx(raw))]
        if name.endswith('.pdf') or mimetype == 'application/pdf':
            return _extract_pdf(raw)
        raise UserError(_(
            'Unsupported document type. Upload PDF, docx, txt or markdown.'))

    def _chunk_pages(self, pages):
        self.ensure_one()
        kb = self.knowledge_id
        strategy = kb.chunk_strategy or 'fixed'
        pieces = []
        for page, text in pages:
            if strategy == 'semantic':
                chunks = _split_semantic(text)
            elif strategy == 'heading':
                chunks = _split_heading(text)
            else:
                chunks = _split_fixed(text, kb.chunk_size or 800, kb.chunk_overlap or 120)
            for chunk in chunks:
                pieces.append((page, chunk))
        return pieces

    def action_parse(self):
        for document in self:
            try:
                pages = document._extract_text()
                text = '\n\n'.join(page_text for _page, page_text in pages)
                document.write({
                    'content': text,
                    'state': 'parsed' if text.strip() else 'error',
                    'error_message': False if text.strip() else _(
                        'No text could be extracted.'),
                })
            except Exception as exc:  # noqa: BLE001
                _logger.exception('ai_base document parse failed')
                document.write({
                    'state': 'error',
                    'error_message': str(exc)[:500],
                })
        return True

    def action_index(self):
        for document in self:
            document._index_one()
        return True

    def _index_one(self):
        self.ensure_one()
        try:
            if self.state in ('pending', 'error') or not self.content:
                self.action_parse()
                self.invalidate_recordset(['content', 'state'])
            if self.state == 'error':
                return
            pages = self._extract_text() or [(False, self.content or '')]
            pieces = self._chunk_pages(pages)
            self.chunk_ids.unlink()
            if not pieces:
                self.write({
                    'state': 'error',
                    'error_message': _('No chunks were produced.'),
                })
                return
            texts = [text for _page, text in pieces]
            model = self.knowledge_id.embedding_model_id
            vectors = self.env['ai.base.service'].embedding(texts, model=model)
            chunks = self.env['ai.knowledge.chunk']
            for index, ((page, text), vector) in enumerate(zip(pieces, vectors)):
                chunks |= chunks.create({
                    'document_id': self.id,
                    'knowledge_id': self.knowledge_id.id,
                    'sequence': index,
                    'page': page or False,
                    'content': text,
                    'embedding': json.dumps(vector) if vector else False,
                })
            store = get_vector_store(self.env, self.knowledge_id.vector_store_type)
            store.upsert(self.env, chunks)
            self.write({'state': 'ready', 'error_message': False})
        except Exception as exc:  # noqa: BLE001
            _logger.exception('ai_base document index failed')
            self.write({'state': 'error', 'error_message': str(exc)[:500]})

    def unlink(self):
        chunk_ids = self.chunk_ids.ids
        stores = {
            doc.knowledge_id.vector_store_type or 'pgvector'
            for doc in self
        }
        for store_type in stores:
            get_vector_store(self.env, store_type).delete(self.env, chunk_ids)
        return super().unlink()

    @api.model
    def _cron_index_pending(self, batch_size=20):
        pending = self.search([
            ('state', 'in', ('pending', 'parsed')),
            ('active', '=', True),
        ], limit=batch_size)
        pending.action_index()


class AiKnowledgeChunk(models.Model):
    _name = 'ai.knowledge.chunk'
    _description = 'AI Knowledge Chunk'
    _order = 'document_id, sequence, id'
    _check_company_auto = True

    document_id = fields.Many2one(
        'ai.knowledge.document', string='Document', required=True,
        ondelete='cascade', index=True)
    knowledge_id = fields.Many2one(
        'ai.knowledge.base', string='Knowledge Base', required=True,
        ondelete='cascade', index=True)
    company_id = fields.Many2one(
        related='knowledge_id.company_id', store=True, readonly=True)
    sequence = fields.Integer(string='Sequence', default=10)
    page = fields.Integer(string='Page')
    content = fields.Text(string='Content', required=True)
    embedding = fields.Text(string='Embedding JSON')

    def _embedding_vector(self):
        self.ensure_one()
        if not self.embedding:
            return []
        try:
            vector = json.loads(self.embedding)
        except ValueError:
            return []
        if not isinstance(vector, list):
            return []
        return [float(item) for item in vector]
