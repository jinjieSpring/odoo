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
    provider_id = fields.Many2one('ai.provider', string='Provider')
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
    reasoning_strength = fields.Selection([
        ('none', 'Off'),
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ], string='Thinking Strength', default='none')
    web_search_enabled = fields.Boolean(string='Web Search', default=False)
    attach_context = fields.Boolean(string='Attach Record Context', default=True)
    context_model = fields.Char(string='Context Model')
    context_res_id = fields.Integer(string='Context Record')
    context_snapshot = fields.Text(string='Context Snapshot')
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
    input_tokens = fields.Integer(
        compute='_compute_token_stats', store=True, string='Input Tokens')
    output_tokens = fields.Integer(
        compute='_compute_token_stats', store=True, string='Output Tokens')
    context_tokens = fields.Integer(
        compute='_compute_context_usage', string='Context Tokens')
    context_usage = fields.Integer(
        compute='_compute_context_usage', string='Context Usage %')
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

    @api.depends('message_ids.prompt_tokens', 'message_ids.completion_tokens')
    def _compute_token_stats(self):
        for session in self:
            session.input_tokens = sum(session.message_ids.mapped('prompt_tokens'))
            session.output_tokens = sum(
                session.message_ids.mapped('completion_tokens'))

    @api.depends('message_ids.content', 'model_id.max_context_tokens')
    def _compute_context_usage(self):
        for session in self:
            tokens = sum(
                session._estimate_tokens(msg.content)
                for msg in session.message_ids)
            session.context_tokens = tokens
            budget = session.model_id.max_context_tokens or 8192
            session.context_usage = int(tokens * 100 / budget) if budget else 0

    @api.model_create_multi
    def create(self, vals_list):
        settings = self.env['ai.user.settings']._get_for_user()
        for vals in vals_list:
            if not vals.get('model_id'):
                model = self.env['ai.model']._get_model_for_scenario('chat')
                if model:
                    vals['model_id'] = model.id
                    vals['provider_id'] = model.provider_id.id
            if 'streaming' not in vals:
                vals['streaming'] = settings.streaming
            if 'reasoning_strength' not in vals:
                vals['reasoning_strength'] = settings.reasoning_strength
            if 'web_search_enabled' not in vals:
                vals['web_search_enabled'] = settings.web_search_enabled
            if 'attach_context' not in vals:
                vals['attach_context'] = settings.attach_context
            if 'prompt_id' not in vals and settings.default_prompt_id:
                vals['prompt_id'] = settings.default_prompt_id.id
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
        options = {
            'streaming': self.streaming,
            'reasoning_strength': self.reasoning_strength,
            'web_search': self.web_search_enabled,
        }
        if extra:
            options.update(extra)
        return options

    @api.model
    def action_get_defaults(self):
        return self.env['ai.chat'].defaults()

    @api.model
    def action_get_user_settings(self):
        return self.env['ai.chat'].user_settings()

    @api.model
    def action_save_user_settings(self, options):
        return self.env['ai.chat'].save_user_settings(options)

    @api.model
    def action_get_record_context(self, model_name, res_id):
        return self.env['ai.chat'].record_context(model_name, res_id)

    @api.model
    def action_get_list_context(self, model_name, res_ids=None, total_count=None):
        return self.env['ai.chat'].list_context(model_name, res_ids, total_count)

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
        return self.env['ai.chat'].session_payload(self)

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
        return self.env['ai.chat'].set_options(self, options)

    def action_send_message(self, content, options=None):
        self.ensure_one()
        return self.env['ai.chat'].send_message(self, content, options)

    def action_edit_and_resend(self, message_id, content):
        return self.env['ai.chat'].edit_and_resend(self, message_id, content)

    def action_regenerate(self, message_id):
        return self.env['ai.chat'].regenerate(self, message_id)

    def action_send_as_message(self, message_id):
        return self.env['ai.chat'].send_as_message(self, message_id)

    def action_log_as_note(self, message_id):
        return self.env['ai.chat'].log_as_note(self, message_id)

    def action_open_in_discuss(self):
        return self.env['ai.chat'].open_in_discuss(self)

    def action_attach_context(self, model_name, res_id):
        return self.env['ai.chat'].attach_context(self, model_name, res_id)

    def action_attach_list_context(self, model_name, res_ids=None, total_count=None):
        return self.env['ai.chat'].attach_list_context(
            self, model_name, res_ids, total_count)

    def action_clear_context(self):
        return self.env['ai.chat'].clear_context(self)

    @api.model
    def action_build_tool_card(self, payload):
        return self.env['ai.chat'].build_tool_card(payload)

    @api.model
    def action_execute_tool(self, payload):
        return self.env['ai.chat'].execute_tool(payload)

    @api.model
    def action_whitelist_add(self, model_name):
        return self.env['ai.chat'].whitelist_add(model_name)

    @api.model
    def action_install_module(self, module_name):
        return self.env['ai.chat'].install_module(module_name)

    @api.model
    def action_notify_admins(self, payload):
        return self.env['ai.chat'].notify_admins(payload)


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
    reasoning_content = fields.Text(string='Reasoning')
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
