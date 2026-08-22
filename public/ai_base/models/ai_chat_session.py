# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class AiChatSession(models.Model):
    _name = 'ai.chat.session'
    _description = 'AI Chat Session'
    _order = 'write_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Session Name', required=True,
        default=lambda self: _('New Session'))
    company_id = fields.Many2one(
        'res.company', string='Company', index=True,
        default=lambda self: self.env.company)
    user_id = fields.Many2one(
        'res.users', string='User', required=True,
        default=lambda self: self.env.user, ondelete='cascade')
    adapter_id = fields.Many2one('ai.adapter', string='Adapter')
    model_id = fields.Many2one('ai.model', string='Model')
    prompt_id = fields.Many2one(
        'ai.prompt.template', string='Prompt', ondelete='set null')
    res_model = fields.Char(string='Related Model')
    res_id = fields.Integer(string='Related Record')
    res_name = fields.Char(compute='_compute_res_name', string='Related Record')
    message_ids = fields.One2many(
        'ai.chat.message', 'session_id', string='Messages')
    message_count = fields.Integer(
        compute='_compute_message_count', string='Message Count')
    streaming = fields.Boolean(string='Streaming', default=True)
    knowledge_enabled = fields.Boolean(string='Use Knowledge Base', default=False)
    knowledge_top_k = fields.Integer(string='Knowledge Top K', default=5)
    knowledge_ids = fields.Many2many(
        'ai.knowledge.base', string='Knowledge Bases')
    knowledge_document_ids = fields.Many2many(
        'ai.knowledge.document', string='Knowledge Documents')
    compress_strategy = fields.Selection([
        ('trim', 'Drop Oldest'),
        ('summary', 'Summarize Oldest'),
    ], string='Context Compression', default='trim')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'In Progress'),
        ('closed', 'Closed'),
    ], string='Status', default='open')
    active = fields.Boolean(string='Active', default=True)

    @api.depends('res_model', 'res_id')
    def _compute_res_name(self):
        for session in self:
            name = False
            if session.res_model and session.res_id and session.res_model in self.env:
                record = self.env[session.res_model].browse(session.res_id).exists()
                name = record.display_name if record else False
            session.res_name = name

    @api.depends('message_ids')
    def _compute_message_count(self):
        data = self.env['ai.chat.message']._read_group(
            [('session_id', 'in', self.ids)],
            ['session_id'], ['session_id:count'])
        count_map = {session.id: count for session, count in data}
        for session in self:
            session.message_count = count_map.get(session.id, 0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('model_id'):
                model = self.env['ai.model']._get_model_for_scenario('chat')
                if model:
                    vals['model_id'] = model.id
                    vals['adapter_id'] = model.adapter_id.id
        return super().create(vals_list)

    def _build_history(self):
        self.ensure_one()
        messages = []
        for message in self.message_ids.sorted(lambda m: (m.create_date, m.id)):
            if message.role in ('user', 'assistant', 'system', 'tool'):
                messages.append({
                    'role': message.role,
                    'content': message.content or '',
                })
        return self._trim_history(messages)

    def _estimate_tokens(self, text):
        return max(1, len(text or '') // 4)

    def _trim_history(self, messages):
        self.ensure_one()
        model = self.model_id
        budget = (model.max_context_tokens or 8192) if model else 8192
        reserve = (model.max_tokens_default or 1024) if model else 1024
        limit = max(512, budget - reserve)
        total = sum(self._estimate_tokens(msg.get('content')) for msg in messages)
        if total <= limit:
            return messages
        system = [msg for msg in messages if msg.get('role') == 'system']
        rest = [msg for msg in messages if msg.get('role') != 'system']
        if self.compress_strategy == 'summary' and rest:
            dropped = rest[:-6] if len(rest) > 6 else rest[: max(len(rest) - 2, 0)]
            kept = rest[len(dropped):]
            summary = self._summarize_messages(dropped)
            if summary:
                system.append({'role': 'system', 'content': summary})
            rest = kept
        else:
            while rest and sum(
                    self._estimate_tokens(msg.get('content'))
                    for msg in system + rest) > limit:
                rest.pop(0)
        return system + rest

    def _summarize_messages(self, messages):
        if not messages:
            return ''
        blob = '\n'.join(
            '%s: %s' % (msg.get('role'), (msg.get('content') or '')[:400])
            for msg in messages[-12:])
        try:
            result = self.env['ai.base.service'].chat(
                'Summarize the following conversation for later context:\n%s' % blob,
                session=None,
                options={'max_tokens': 256},
                scenario='summary',
            )
            return (result.get('reply') or '')[:1500]
        except Exception:  # noqa: BLE001
            return _('Earlier conversation omitted to stay within the context window.')

    def _call_options(self, extra=None):
        self.ensure_one()
        options = {'streaming': self.streaming}
        if extra:
            options.update(extra)
        return options

    @api.model
    def action_get_defaults(self):
        model = self.env['ai.model']._get_model_for_scenario('chat')
        ready = bool(model)
        return {
            'model_ready': ready,
            'model_id': model.id if model else False,
            'model_status': {
                'code': 'ready' if ready else 'no_model',
                'title': _('Model ready') if ready else _('Model not configured'),
                'message': (
                    _('Using %s') % model.display_name if model
                    else _('No default model is configured.')),
            },
            'model_info': {
                'name': model.display_name if model else '',
                'capabilities': model._allowed_options() if model else {},
            },
            'streaming': True,
        }

    @api.model
    def action_create_from_input(self, content, res_model=None, res_id=None):
        session = self.create({
            'name': (content or _('New Session'))[:30],
            'res_model': res_model or False,
            'res_id': res_id or False,
        })
        return session.id

    def action_get_session(self):
        self.ensure_one()
        return {
            'session': {
                'id': self.id,
                'name': self.name,
                'model_id': self.model_id.id,
                'message_count': self.message_count,
                'streaming': self.streaming,
                'knowledge_enabled': self.knowledge_enabled,
                'res_model': self.res_model,
                'res_id': self.res_id,
                'res_name': self.res_name,
                'capabilities': (
                    self.model_id._allowed_options() if self.model_id else {}),
            },
            'messages': [{
                'id': message.id,
                'role': message.role,
                'content': message.content,
                'tool_cards': message.tool_cards or [],
                'rag_sources': message.rag_sources or [],
            } for message in self.message_ids.sorted(
                lambda m: (m.create_date, m.id))],
        }

    def action_list_sessions(self):
        sessions = self.search([('active', '=', True)], limit=50)
        return [{
            'id': session.id,
            'name': session.name,
            'message_count': session.message_count,
            'write_date': session.write_date,
            'res_name': session.res_name,
        } for session in sessions]

    def action_set_options(self, options):
        self.ensure_one()
        vals = {}
        for field in (
                'streaming', 'knowledge_enabled', 'knowledge_top_k',
                'model_id', 'prompt_id', 'compress_strategy'):
            if field in (options or {}):
                vals[field] = options[field]
        if 'knowledge_ids' in (options or {}):
            vals['knowledge_ids'] = [(6, 0, options['knowledge_ids'] or [])]
        if 'knowledge_document_ids' in (options or {}):
            vals['knowledge_document_ids'] = [
                (6, 0, options['knowledge_document_ids'] or [])]
        if vals:
            self.write(vals)
        return self.action_get_session()

    def action_send_message(self, content, options=None):
        self.ensure_one()
        return self.env['ai.base.service'].chat(
            content, session=self, options=options or {})


class AiChatMessage(models.Model):
    _name = 'ai.chat.message'
    _description = 'AI Chat Message'
    _order = 'create_date, id'

    session_id = fields.Many2one(
        'ai.chat.session', string='Session', required=True,
        ondelete='cascade', index=True)
    role = fields.Selection([
        ('user', 'User'),
        ('assistant', 'Assistant'),
        ('system', 'System'),
        ('tool', 'Tool'),
    ], string='Role', required=True, default='user')
    content = fields.Text(string='Content')
    tool_cards = fields.Json(string='Tool Cards', default=list)
    rag_sources = fields.Json(string='RAG Sources', default=list)
    prompt_tokens = fields.Integer(string='Input Tokens', default=0)
    completion_tokens = fields.Integer(string='Output Tokens', default=0)
    total_tokens = fields.Integer(string='Total Tokens', default=0)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for session in records.session_id:
            session.write({'state': session.state or 'open'})
        return records
