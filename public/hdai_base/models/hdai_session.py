# -*- coding: utf-8 -*-
import json
import logging

from markupsafe import Markup

from odoo import _, api, fields, models

from odoo.addons.hdai_base.models.llm_service import LLMError, LLMService
from odoo.addons.hdai_base.models.hdai_format import markdown_to_html
from odoo.addons.hdai_base.models.hdai_tools import (
    ToolError,
    build_tool_card,
    extract_tool_calls,
    get_tool,
    parse_tool_payload,
    split_tool_content,
    strip_tool_blocks,
    validate_tool_schema,
)

_logger = logging.getLogger(__name__)


class HdaiSession(models.Model):
    _name = 'hdai.session'
    _description = 'AI Chat Session'
    _order = 'write_date desc, id desc'

    _DEFAULT_OPTION_USER_FIELDS = {
        'reasoning_strength': 'reasoning_strength',
        'web_search_enabled': 'web_search_enabled',
        'streaming': 'streaming',
    }
    _END_MESSAGE = '__end_message'

    name = fields.Char(
        string='Session Name', required=True,
        default=lambda self: _('New Session'))
    user_id = fields.Many2one(
        'res.users', string='User', required=True,
        default=lambda self: self.env.user, ondelete='cascade')
    provider_id = fields.Many2one('hdai.provider', string='Model Provider')
    model_id = fields.Many2one('hdai.model', string='Model')
    agent_id = fields.Many2one(
        'hdai.agent', string='AI Agent', ondelete='set null',
        help='Agent whose system prompt and model are used for this session.')
    message_ids = fields.One2many(
        'hdai.message', 'session_id', string='Messages')
    message_count = fields.Integer(
        compute='_compute_message_count', string='Message Count')
    context_tokens = fields.Integer(
        compute='_compute_context_usage', string='Context Usage (tokens)')
    context_usage = fields.Float(
        compute='_compute_context_usage', string='Context Usage Ratio',
        aggregator='avg')
    input_tokens = fields.Integer(
        compute='_compute_context_usage', string='Input Tokens')
    output_tokens = fields.Integer(
        compute='_compute_context_usage', string='Output Tokens')
    total_tokens = fields.Integer(
        compute='_compute_context_usage', string='Total Tokens')
    reasoning_strength = fields.Selection([
        ('none', 'Off'),
        ('low', 'Low'),
        ('medium', 'Medium'),
        ('high', 'High'),
    ], string='Thinking Strength', default='none')
    web_search_enabled = fields.Boolean(string='Web Search', default=False)
    streaming = fields.Boolean(string='Streaming', default=True)
    prompt_id = fields.Many2one(
        'hdai.prompt', string='Prompt', ondelete='set null')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'In Progress'),
        ('closed', 'Closed'),
    ], string='Status', default='open')
    active = fields.Boolean(string='Active', default=True)
    # Ask AI context awareness: the record/chatter snapshot attached to the
    # conversation (used by prompts such as "summarize this chatter thread").
    attach_context = fields.Boolean(
        string='Attach Record Context', default=True)
    context_model = fields.Char(string='Context Model')
    context_res_id = fields.Integer(string='Context Record')
    context_snapshot = fields.Text(string='Context Snapshot')
    # Knowledge retrieval scope (hdai_knowledge is optional: the fields are
    # plain values and the chunk model is looked up lazily).
    knowledge_enabled = fields.Boolean(
        string='Use Knowledge Base', default=False)
    knowledge_top_k = fields.Integer(
        string='Knowledge Top K', default=5)
    knowledge_document_ids = fields.Char(
        string='Knowledge Documents',
        help='Comma-separated ids of the hdai.knowledge.document records '
             'selected as the retrieval scope.')

    # ------------------------------------------------------------------
    # Creation / option defaults
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        settings = self.env['hdai.user.settings']._get_for_user(
            self.env.user)
        for vals in vals_list:
            for field, user_field in self._DEFAULT_OPTION_USER_FIELDS.items():
                if field not in vals:
                    vals[field] = settings[user_field]
            if 'prompt_id' not in vals:
                vals['prompt_id'] = settings.default_prompt_id.id or False
            if 'attach_context' not in vals:
                vals['attach_context'] = settings.attach_context
            if 'agent_id' not in vals:
                agent = self.env['hdai.agent']._get_default_agent()
                if agent:
                    vals['agent_id'] = agent.id
                    model = agent._resolve_model()
                    if model and 'model_id' not in vals:
                        vals['model_id'] = model.id
                        vals['provider_id'] = model.provider_id.id
            if 'model_id' not in vals:
                model = self.env['hdai.model']._get_model_for_scenario(
                    'chat')
                if model:
                    vals['model_id'] = model.id
                    vals['provider_id'] = model.provider_id.id
        records = super().create(vals_list)
        for record in records:
            if record.model_id:
                vals = {field: record[field]
                        for field in self._DEFAULT_OPTION_USER_FIELDS}
                self._clamp_option_values(record.model_id, vals)
                if any(vals[field] != record[field]
                       for field in self._DEFAULT_OPTION_USER_FIELDS):
                    record.write(vals)
        return records

    def _clamp_option_values(self, model, vals):
        allowed = model._allowed_options()
        if not allowed['reasoning'] and 'reasoning_strength' in vals:
            vals['reasoning_strength'] = 'none'
        if not allowed['web_search'] and 'web_search_enabled' in vals:
            vals['web_search_enabled'] = False
        if not allowed['streaming'] and 'streaming' in vals:
            vals['streaming'] = False
        return vals

    # ------------------------------------------------------------------
    # Computed fields
    # ------------------------------------------------------------------

    @api.depends('message_ids')
    def _compute_message_count(self):
        for session in self:
            session.message_count = len(session.message_ids)

    @api.depends('message_ids.total_tokens', 'message_ids.prompt_tokens',
                 'message_ids.completion_tokens', 'model_id.context_length')
    def _compute_context_usage(self):
        for session in self:
            messages = session.message_ids
            session.input_tokens = sum(messages.mapped('prompt_tokens') or [0])
            session.output_tokens = sum(
                messages.mapped('completion_tokens') or [0])
            session.context_tokens = sum(
                messages.mapped('total_tokens') or [0])
            session.total_tokens = session.context_tokens
            length = session.model_id.context_length or 1
            session.context_usage = min(
                100.0, round(session.context_tokens * 100.0 / length, 2))

    # ------------------------------------------------------------------
    # Model status / defaults
    # ------------------------------------------------------------------

    @api.model
    def _get_default_model(self):
        return self.env['hdai.model']._get_default_model()

    @api.model
    def _get_model_status(self, model=None):
        model = model or self._get_default_model()
        if not model:
            return False, {
                'code': 'no_model',
                'title': _('No model configured'),
                'message': _('No default model is configured. Configure a '
                             'model provider and test the connection to fill '
                             'its model list before chatting.'),
            }
        provider = model.provider_id
        if not provider.active:
            return False, {
                'code': 'provider_inactive',
                'title': _('Model not ready'),
                'message': _('The model provider "%s" is inactive. Activate '
                             'it under "Model Providers".') % provider.display_name,
            }
        if not provider.base_url:
            return False, {
                'code': 'invalid_config',
                'title': _('Model not ready'),
                'message': _('The provider URL is not configured. Open the '
                             'provider form and set the Base URL.'),
            }
        if provider._api_key_required() and not provider.sudo().api_key:
            return False, {
                'code': 'missing_api_key',
                'title': _('Model not ready'),
                'message': _('The provider "%s" requires an API key. Open the '
                             'provider form and fill it in.') % provider.display_name,
            }
        return True, {
            'code': 'ready',
            'title': _('Model ready'),
            'message': model.display_name,
        }

    @api.model
    def action_create_from_input(self, content):
        content = (content or '').strip()
        if not content:
            return False
        model = self.env['hdai.model']._get_model_for_scenario('chat')
        agent = self.env['hdai.agent']._get_default_agent()
        return self.create({
            'name': content[:30],
            'model_id': model.id if model else False,
            'provider_id': model.provider_id.id if model else False,
            'agent_id': agent.id if agent else False,
        }).id

    @api.model
    def action_get_defaults(self):
        model = self.env['hdai.model']._get_model_for_scenario('chat')
        model_ready, model_status = self._get_model_status(model)
        settings = self.env['hdai.user.settings']._get_for_user(
            self.env.user)
        agent = self.env['hdai.agent']._get_default_agent()
        return {
            'model_id': model.id if model else False,
            'model_ready': model_ready,
            'model_status': model_status,
            'model_info': {
                'name': model.display_name,
                'provider': model.provider_id.display_name,
                'context_length': model.context_length,
                'max_output_tokens': model.max_output_tokens,
                'thinking_strength': model.thinking_strength,
                'supports_reasoning': model.supports_reasoning,
                'supports_web_search': model.supports_web_search,
                'capabilities': {
                    'reasoning': (
                        model.supports_reasoning and model.allow_reasoning),
                    'web_search': (
                        model.supports_web_search and model.allow_web_search),
                    'streaming': model.allow_streaming,
                },
            } if model else {},
            'reasoning_strength': settings.reasoning_strength,
            'web_search_enabled': settings.web_search_enabled,
            'streaming': settings.streaming,
            'attach_context': settings.attach_context,
            'sidebar_collapsed': settings.sidebar_collapsed,
            'grid_sessions_collapsed': settings.grid_sessions_collapsed,
            'grid_knowledge_collapsed': settings.grid_knowledge_collapsed,
            'grid_sessions_height': settings.grid_sessions_height,
            'grid_knowledge_height': settings.grid_knowledge_height,
            'sidebar_width': settings.sidebar_width or 260,
            'default_prompt_id': settings.default_prompt_id.id or False,
            'prompts': self.env['hdai.prompt'].search_read(
                ['|', ('scope', '=', 'system'), '&',
                 ('scope', '=', 'user'), ('user_id', '=', self.env.user.id)],
                ['id', 'name'], order='scope, sequence, name'),
            'capabilities': (
                model._allowed_options()
                if model else self._empty_capabilities()),
            'agents': self.env['hdai.agent'].search_read(
                [('active', '=', True)],
                ['id', 'name'], order='sequence, name'),
            'default_agent_id': agent.id if agent else False,
            'knowledge_documents': self._knowledge_documents(),
        }

    @api.model
    def _empty_capabilities(self):
        """Capability flags when no model is usable: every option is locked."""
        return {
            'reasoning': False,
            'web_search': False,
            'streaming': False,
        }

    def action_set_options(self, options):
        options = options or {}
        if (options.get('reasoning_strength')
                and options['reasoning_strength'] not in
                ('none', 'low', 'medium', 'high')):
            raise ValueError(_('Invalid thinking strength.'))
        if self and self.model_id:
            self._clamp_option_values(self.model_id, options)
        if self:
            vals = {field: value for field, value in options.items()
                    if field in self._fields}
            if vals:
                self.write(vals)
        user_vals = {}
        for field, user_field in self._DEFAULT_OPTION_USER_FIELDS.items():
            if field in options:
                user_vals[user_field] = options[field]
        if 'attach_context' in options:
            user_vals['attach_context'] = bool(options['attach_context'])
        for field in ('sidebar_collapsed', 'grid_sessions_collapsed',
                      'grid_knowledge_collapsed'):
            if field in options:
                user_vals[field] = bool(options[field])
        for field in ('grid_sessions_height', 'grid_knowledge_height'):
            if field in options:
                height = int(options[field] or 0)
                user_vals[field] = max(0, min(height, 10000))
        if 'sidebar_width' in options:
            width = int(options['sidebar_width'] or 0)
            user_vals['sidebar_width'] = max(180, min(width, 800))
        if user_vals:
            self.env['hdai.user.settings']._get_for_user(
                self.env.user).write(user_vals)
        return True

    @api.model
    def action_get_user_settings(self):
        settings = self.env['hdai.user.settings']._get_for_user(
            self.env.user)
        model = self.env['hdai.model']._get_model_for_scenario('chat')
        capabilities = (
            model._allowed_options() if model else self._empty_capabilities())
        return {
            'capabilities': capabilities,
            'language_mode': settings.language_mode or 'auto',
            'language': settings.language or '',
            'languages': [
                {'code': code, 'name': name}
                for code, name in sorted(
                    LLMService._LANGUAGE_NAMES.items(), key=lambda item: item[1])
            ],
            'reasoning_strength': settings.reasoning_strength,
            'web_search_enabled': settings.web_search_enabled,
            'streaming': settings.streaming,
            'attach_context': settings.attach_context,
            'sidebar_collapsed': settings.sidebar_collapsed,
            'grid_sessions_collapsed': settings.grid_sessions_collapsed,
            'grid_knowledge_collapsed': settings.grid_knowledge_collapsed,
            'grid_sessions_height': settings.grid_sessions_height,
            'grid_knowledge_height': settings.grid_knowledge_height,
            'sidebar_width': settings.sidebar_width or 260,
            'default_prompt_id': settings.default_prompt_id.id or False,
            'prompts': self.env['hdai.prompt'].search_read(
                ['|', ('scope', '=', 'system'), '&',
                 ('scope', '=', 'user'), ('user_id', '=', self.env.user.id)],
                ['id', 'name'], order='scope, sequence, name'),
        }

    @api.model
    def action_save_user_settings(self, options):
        options = options or {}
        settings = self.env['hdai.user.settings']._get_for_user(
            self.env.user)
        vals = {}
        if options.get('language_mode') in ('auto', 'system', 'specific'):
            vals['language_mode'] = options['language_mode']
        language = (options.get('language') or '').strip()
        if options.get('language_mode') == 'specific':
            if language not in LLMService._LANGUAGE_NAMES:
                raise ValueError(_('Please select a valid language.'))
            vals['language'] = language
        else:
            vals['language'] = False
        if (options.get('reasoning_strength') in
                ('none', 'low', 'medium', 'high')):
            vals['reasoning_strength'] = options['reasoning_strength']
        if 'web_search_enabled' in options:
            vals['web_search_enabled'] = bool(options['web_search_enabled'])
        if 'streaming' in options:
            vals['streaming'] = bool(options['streaming'])
        if 'attach_context' in options:
            vals['attach_context'] = bool(options['attach_context'])
        for field in ('sidebar_collapsed', 'grid_sessions_collapsed',
                      'grid_knowledge_collapsed'):
            if field in options:
                vals[field] = bool(options[field])
        for field in ('grid_sessions_height', 'grid_knowledge_height'):
            if field in options:
                height = int(options[field] or 0)
                vals[field] = max(0, min(height, 10000))
        if 'sidebar_width' in options:
            width = int(options['sidebar_width'] or 0)
            vals['sidebar_width'] = max(180, min(width, 800))
        if 'default_prompt_id' in options:
            vals['default_prompt_id'] = options['default_prompt_id'] or False
        model = self.env['hdai.model']._get_model_for_scenario('chat')
        if model:
            self._clamp_option_values(model, vals)
        settings.write(vals)
        return True

    # ------------------------------------------------------------------
    # Context awareness
    # ------------------------------------------------------------------

    @api.model
    def action_get_record_context(self, model_name, res_id):
        """Build a plain-text snapshot of a record and its recent chatter."""
        if not model_name or not res_id:
            return {'model': False, 'res_id': False, 'display_name': '',
                    'chatter': []}
        try:
            record = self.env[model_name].browse(int(res_id)).exists()
        except KeyError:
            return {'model': False, 'res_id': False, 'display_name': '',
                    'chatter': []}
        if not record:
            return {'model': model_name, 'res_id': int(res_id),
                    'display_name': '', 'chatter': []}
        messages = record.message_ids.sorted(
            lambda m: (m.create_date, m.id), reverse=True)[:10]
        chatter = [{
            'author': m.author_id.display_name or _('Unknown'),
            'date': m.create_date,
            'body': (m.body or '')[:1000],
        } for m in messages if (m.body or '').strip()]
        return {
            'model': model_name,
            'res_id': record.id,
            'display_name': record.display_name,
            'chatter': chatter,
        }

    def _build_context_snapshot(self):
        if not self.attach_context or not self.context_model or not self.context_res_id:
            return ''
        record = self.env[self.context_model].browse(
            self.context_res_id).exists()
        if not record:
            return ''
        lines = [
            'Current record: %s (%s)' % (record.display_name, self.context_model),
        ]
        messages = record.message_ids.sorted(
            lambda m: (m.create_date, m.id), reverse=True)[:10]
        if messages:
            lines.append('Recent chatter messages:')
            for m in reversed(messages):
                if not (m.body or '').strip():
                    continue
                lines.append('- %s: %s' % (
                    m.author_id.display_name or _('Unknown'),
                    (m.body or '')[:1000]))
        return '\n'.join(lines)

    def action_attach_context(self, model_name, res_id):
        """Attach the current record/chatter context to the session."""
        self.ensure_one()
        context = self.action_get_record_context(model_name, res_id)
        if not context.get('res_id'):
            return {'attached': False}
        snapshot_lines = [
            'Current record: %s (%s)' % (
                context['display_name'], context['model']),
        ]
        for item in context['chatter']:
            snapshot_lines.append('- %s: %s' % (
                item['author'], item['body']))
        self.write({
            'attach_context': True,
            'context_model': context['model'],
            'context_res_id': context['res_id'],
            'context_snapshot': '\n'.join(snapshot_lines),
        })
        return {'attached': True, 'snapshot': self.context_snapshot}

    def action_clear_context(self):
        """Detach the record context for now without disabling future
        sensing: only the context fields are cleared, ``attach_context``
        stays enabled so the next dialog open re-attaches the current record.
        The "Record Context" toggle is the persistent preference."""
        self.ensure_one()
        self.write({
            'context_model': False,
            'context_res_id': False,
            'context_snapshot': False,
        })
        return True

    # ------------------------------------------------------------------
    # Messages / model calls
    # ------------------------------------------------------------------

    def action_get_messages(self):
        self.ensure_one()
        messages = self.message_ids.sorted(lambda m: (m.create_date, m.id))
        result = []
        for message in messages:
            item = {
                'id': message.id,
                'role': message.role,
                'content': message.content,
                'reasoning_content': message.reasoning_content,
                'total_tokens': message.total_tokens,
                'create_date': message.create_date,
                'tool_cards': message.tool_cards or [],
            }
            if message.role == 'assistant':
                before, payload, after = split_tool_content(message.content)
                if payload:
                    item['tool'] = build_tool_card(self.env, payload)
                    item['content_before_tool'] = before
                    item['content_after_tool'] = after
            result.append(item)
        return result

    def action_get_session(self):
        """Return messages, session stats and per-session options for the
        chat dialog when a specific session is opened."""
        self.ensure_one()
        self.invalidate_recordset(
            ['context_tokens', 'context_usage', 'message_count'])
        model = self.model_id
        return {
            'messages': self.action_get_messages(),
            'session': {
                'id': self.id,
                'name': self.name,
                'context_tokens': self.context_tokens,
                'context_usage': self.context_usage,
                'input_tokens': self.input_tokens,
                'output_tokens': self.output_tokens,
                'message_count': self.message_count,
                'reasoning_strength': self.reasoning_strength,
                'web_search_enabled': self.web_search_enabled,
                'streaming': self.streaming,
                'prompt_id': self.prompt_id.id or False,
                'attach_context': self.attach_context,
                'context_attached': bool(
                    self.context_model and self.context_res_id),
                'context_display_name': self.context_snapshot.splitlines()[0]
                if self.context_snapshot else '',
                'knowledge_enabled': self.knowledge_enabled,
                'knowledge_top_k': self.knowledge_top_k,
                'knowledge_document_ids': self._knowledge_document_ids(),
                'capabilities': (
                    model._allowed_options()
                    if model else self._empty_capabilities()),
            },
        }

    @api.model
    def action_build_tool_card(self, payload):
        """Return the (pre-validated) tool card for a payload; used by the
        streaming flow after the assistant reply completes."""
        return build_tool_card(self.env, payload)

    @api.model
    def action_execute_tool(self, payload):
        """Validate and execute a tool payload; returns an Odoo action.

        Canonical path is ``hdai.tool`` / ``@ai_tool``. Legacy ``BaseTool``
        entries are only used when no registry tool matches.
        """
        if not isinstance(payload, dict):
            payload = {}
        registry_tool = self.env['hdai.tool'].sudo().search(
            [('name', '=', payload.get('tool')),
             ('active', '=', True)], limit=1)
        if registry_tool:
            if registry_tool.suggestive:
                return self.action_confirm_suggestion(payload)
            result = self.env['hdai.tool'].action_invoke_tool(
                registry_tool.name, payload.get('params') or {})
            if result.get('status') == 'error':
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'type': 'warning',
                        'title': _('Tool cannot run'),
                        'message': result.get('message') or _(
                            'The tool returned an error.'),
                        'sticky': True,
                    },
                }
            if isinstance(result.get('action'), dict):
                return result['action']
            if 'suggestion_preview' in result:
                return self._suggestion_open_action(
                    result['suggestion_preview'])
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'success',
                    'title': _('Tool executed'),
                    'message': result.get('message') or _(
                        'The tool executed successfully.'),
                    'sticky': False,
                },
            }
        tool = get_tool(payload.get('tool'))
        if tool:
            try:
                return tool.execute(self.env, payload)
            except ToolError as exc:
                message = exc.message
                if exc.hint:
                    message = '%s %s' % (message, exc.hint)
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'type': 'warning',
                        'title': _('Tool cannot run'),
                        'message': message,
                        'sticky': True,
                    },
                }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'warning',
                'title': _('Tool unavailable'),
                'message': _('The requested tool is not available.'),
                'sticky': True,
            },
        }

    @api.model
    def action_confirm_suggestion(self, payload):
        """Invoke a suggestive tool and open a standard form for the user
        to review/apply (no direct write in hdai_base)."""
        if not isinstance(payload, dict):
            payload = {}
        result = self.env['hdai.tool'].action_invoke_tool(
            payload.get('tool'), payload.get('params') or {})
        if result.get('status') == 'error':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('Suggestion unavailable'),
                    'message': result.get('message') or _(
                        'The suggestion tool returned an error.'),
                    'sticky': True,
                },
            }
        preview = result.get('suggestion_preview') or result.get('data') or {}
        if not preview.get('model'):
            fields_text = ', '.join(
                '%s=%s' % (key, value)
                for key, value in
                (preview.get('fields_to_update') or {}).items())
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'info',
                    'title': _('Suggestion preview'),
                    'message': _(
                        'Proposed update: %s. Reason: %s') % (
                        fields_text or result.get('message') or '-',
                        preview.get('reason') or '-'),
                    'sticky': True,
                },
            }
        return self._suggestion_open_action(preview)

    @api.model
    def _suggestion_open_action(self, preview):
        """Open the target record in a form; defaults carry suggested values."""
        model_name = preview.get('model')
        record_id = preview.get('record_id')
        if not model_name or model_name not in self.env:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('Suggestion unavailable'),
                    'message': _('The suggested model is not available.'),
                    'sticky': True,
                },
            }
        context = {
            'hdai_suggestion_preview': preview,
            'default_%s' % key: value
            for key, value in (preview.get('fields_to_update') or {}).items()
            if isinstance(key, str) and key.isidentifier()
        }
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Review AI suggestion'),
            'res_model': model_name,
            'view_mode': 'form',
            'target': 'current',
            'context': context,
        }
        if record_id:
            action['res_id'] = int(record_id)
        self.env['hdai.action.log'].create({
            'user_id': self.env.user.id,
            'action': 'chat',
            'query': 'suggest:%s' % model_name,
            'model_name': model_name,
            'res_id': int(record_id) if record_id else 0,
            'result': (preview.get('reason') or '')[:500],
        })
        return action

    @api.model
    def action_notify_admins(self, payload, error=None):
        """Send an internal message about a blocked tool to the admins."""
        error = error or {}
        payload = payload or {}
        admins = self.env.ref('base.group_system').users
        partners = admins.mapped('partner_id').filtered(bool)
        channel = self.env['discuss.channel'].sudo().search(
            [('name', '=', _('Linkin AI Tool Notice'))], limit=1)
        if not channel:
            channel = self.env['discuss.channel'].sudo().create({
                'name': _('Linkin AI Tool Notice'),
                'channel_type': 'channel',
                'channel_member_ids': [
                    (0, 0, {'partner_id': partner.id})
                    for partner in partners
                ],
            })
        bot = self.env['hdai.channel.operator']._bot_partner()
        body = _('User %(user)s requested tool %(tool)s (%(label)s) but it '
                 'could not run: %(message)s. Hint: %(hint)s') % {
            'user': self.env.user.display_name,
            'tool': payload.get('tool'),
            'label': payload.get('label') or '',
            'message': error.get('message') or '',
            'hint': error.get('hint') or '',
        }
        channel.sudo().message_post(
            body=body, author_id=bot.id, message_type='comment',
            subtype_xmlid='mail.mt_comment')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Administrators notified'),
                'message': _('The administrators were notified about this '
                             'tool request.'),
                'sticky': False,
            },
        }

    @api.model
    def action_whitelist_add(self, model_name):
        """Administrator helper: add a model to the Open View whitelist."""
        if not self.env.user.has_group('base.group_system'):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('Administrator only'),
                    'message': _('Only administrators can change the Open '
                                 'View Models whitelist.'),
                    'sticky': True,
                },
            }
        ir_model = self.env['ir.model'].search(
            [('model', '=', model_name)], limit=1)
        if not ir_model:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('Model not found'),
                    'message': _('The model %s does not exist in this '
                                 'database.') % model_name,
                    'sticky': True,
                },
            }
        existing = self.env['hdai.nlview.model'].search(
            [('model_id', '=', ir_model.id)], limit=1)
        if existing:
            existing.write({'active': True})
            message = _('%s is already in the Open View Models whitelist.')
        else:
            self.env['hdai.nlview.model'].create(
                {'model_id': ir_model.id})
            message = _('%s was added to the Open View Models whitelist.')
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Whitelist updated'),
                'message': message % model_name,
                'sticky': False,
            },
        }

    @api.model
    def action_install_module(self, module_name):
        """Administrator helper: queue a module for installation."""
        if not self.env.user.has_group('base.group_system'):
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('Administrator only'),
                    'message': _('Only administrators can install modules.'),
                    'sticky': True,
                },
            }
        module = self.env['ir.module.module'].search(
            [('name', '=', module_name)], limit=1)
        if not module:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('Module not found'),
                    'message': _('The module %s was not found.') % module_name,
                    'sticky': True,
                },
            }
        if module.state == 'installed':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'success',
                    'title': _('Module installed'),
                    'message': _('The module %s is already installed.') % (
                        module_name),
                    'sticky': False,
                },
            }
        try:
            # Immediate install mirrors the Apps page behavior: the module is
            # really installed in this request and the returned reload action
            # makes the browser refresh automatically.
            return module.sudo().button_immediate_install()
        except UserError as exc:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('Module install failed'),
                    'message': str(exc),
                    'sticky': True,
                },
            }

    def _build_history(self):
        self.ensure_one()
        messages = self.message_ids.sorted(lambda m: (m.create_date, m.id))
        return [{'role': m.role, 'content': m.content}
                for m in messages if m.role in ('user', 'assistant')]

    def _system_prompt(self):
        agent = self.agent_id or self.env['hdai.agent']._get_default_agent()
        parts = []
        if agent and agent.system_prompt:
            parts.append(agent.system_prompt)
        chat_template = self._prompt_param('hdai.prompt.chat')
        if chat_template:
            parts.append(chat_template)
        if self.prompt_id and self.prompt_id.content:
            parts.append(self.prompt_id.content)
        nlview_prompt = self.env['hdai.nlview.model']._nlview_prompt()
        if nlview_prompt:
            parts.append(nlview_prompt)
        return '\n\n'.join(parts)

    def _prompt_param(self, key, default=''):
        return self.env['ir.config_parameter'].sudo().get_param(
            key, default)

    def _context_prompt(self):
        """Render the record context with the admin-configurable template."""
        if not self.attach_context or not self.context_snapshot:
            return ''
        snapshot = (
            self._build_context_snapshot()
            if self.context_res_id else self.context_snapshot
        )
        if not snapshot:
            return ''
        template = self._prompt_param('hdai.prompt.context')
        if not template:
            return snapshot
        if '{snapshot}' in template:
            return template.replace('{snapshot}', snapshot)
        return '%s\n\n%s' % (template, snapshot)

    def _knowledge_document_ids(self):
        """Selected knowledge document ids (lazy parse of the Char field)."""
        raw = (self.knowledge_document_ids or '').replace(
            '[', ' ').replace(']', ' ').replace("'", ' ').replace(',', ' ')
        return [int(part) for part in raw.split()
                if part.strip().isdigit()]

    def _knowledge_documents(self):
        """Documents retrievable by the current user (hdai_knowledge is
        optional; an empty list is returned when it is not installed)."""
        if 'hdai.knowledge.document' not in self.env:
            return []
        model = self.env['hdai.knowledge.document']
        domain = [('state', '=', 'ready'), ('active', '=', True)]
        is_manager = self.env.user.has_group('hdai_base.hdai_group_manager')
        if not is_manager:
            domain = ['&'] + domain + [
                '|', ('access_level', '=', 'public'),
                ('user_id', '=', self.env.user.id)]
        return model.search_read(
            domain, ['id', 'name'], order='name')

    def _knowledge_context(self, history=None):
        """Retrieve permission-filtered chunks for the last user message,
        scoped to the selected documents, and render them as a plain-text
        system context."""
        if not self.knowledge_enabled:
            return ''
        if 'hdai.knowledge.chunk' not in self.env:
            return ''
        chunk_model = self.env['hdai.knowledge.chunk']
        query = ''
        for msg in reversed(history or []):
            if msg.get('role') == 'user':
                query = (msg.get('content') or '').strip()
                break
        if not query:
            return ''
        try:
            document_ids = self._knowledge_document_ids()
            items = chunk_model.action_search(
                query,
                limit=self.knowledge_top_k or 5,
                document_ids=document_ids or None)
        except Exception:  # noqa: BLE001
            _logger.exception('hdai knowledge retrieval failed')
            return ''
        if not items:
            return ''
        lines = [
            _('Relevant knowledge from the selected knowledge base:'),
        ]
        lines += [
            '- %s [%s] %s' % (
                item.get('citation') or '',
                item['source_document'],
                item['content'])
            for item in items
        ]
        lines.append(
            _('Use it to answer when applicable; otherwise say you do not '
              'know.'))
        lines.append(
            _('When you use a source, cite it inline with its [SOURCE:...] '
              'marker so the reader can open the original document.'))
        return '\n'.join(lines)

    def _call_options(self, history=None):
        settings = self.env['hdai.user.settings']._get_for_user(
            self.env.user)
        language_mode = settings.language_mode or 'auto'
        options = {
            'reasoning_strength': self.reasoning_strength,
            'web_search': self.web_search_enabled,
            'language_mode': language_mode,
            'lang': (settings.language
                     if language_mode == 'specific' else self.env.lang),
            'system_prompt': self._system_prompt(),
            'context_text': self._context_prompt(),
            'language_instruction': self._prompt_param(
                'hdai.prompt.language'),
        }
        if history:
            knowledge = self._knowledge_context(history)
            if knowledge:
                options['context_text'] = '\n\n'.join(
                    [part for part in
                     (options.get('context_text'), knowledge)
                     if part])
        return options

    # Kept as a static alias so the stream controller and tests can call the
    # pure parser without an environment (see hdai_tools).
    _parse_tool_payload = staticmethod(parse_tool_payload)

    # ------------------------------------------------------------------
    # Server-side tool loop (HD-AI-PLAN-003 P1-G6, design 2.3)
    # ------------------------------------------------------------------

    def _tool_manifest(self):
        """Tool definitions the current user is allowed to invoke."""
        return self.env['hdai.tool'].action_get_manifest_for_user()

    def _loop_limits(self):
        return self.env['hdai.tool']._loop_limits()

    def _tool_protocol_prompt(self, manifest, system_prompt=''):
        """Explain the mixed-execution model to the model itself."""
        names = ', '.join(tool['name'] for tool in manifest)
        instruction = (
            'You can call the following tools to gather information: %s.\n'
            'Read-only tools run automatically on the server and their '
            'results are provided back to you in the next message. Tools '
            'that modify data are never executed automatically: only emit a '
            'suggestion for the user to confirm. When you have the final '
            'answer, reply directly without calling more tools; if a tool '
            'call API is unavailable, emit your call as a fenced JSON block '
            '{"tool": "<name>", "params": {...}}.' % names)
        if system_prompt:
            return '%s\n\n%s' % (system_prompt, instruction)
        return instruction

    def _live_stream_tool_loop(self, model, history, options=None,
                               candidates=None, manifest=None,
                               limit_override=None):
        """Yield tool-loop events while streaming the first model tokens.

        Designed for the HTTP stream generator with a dedicated cursor:
        round 1 uses ``LLMService.stream_chat`` (live ``delta`` events);
        further rounds after tool execution use ``chat_tools`` and emit
        one delta per round. Yields the same event shapes as ``emit`` in
        ``_run_tool_loop``, then a final ``{'type': 'result', 'result': ...}``.
        """
        self.ensure_one()
        options = dict(options or self._call_options(history))
        allowed = model._allowed_options()
        if not allowed['reasoning']:
            options['reasoning_strength'] = 'none'
        if not allowed['web_search']:
            options['web_search'] = False
        limits = self._loop_limits()
        if limit_override:
            limits = dict(limits, **{
                key: value for key, value in limit_override.items()
                if key in limits})
        max_rounds = limits['max_rounds']
        max_calls = limits['max_calls_per_round']
        candidates = list(candidates) if candidates else [model]
        current = candidates[0] if candidates else model
        manifest = manifest if manifest is not None \
            else self._tool_manifest()
        if manifest:
            options['tools'] = self.env['hdai.tool']._function_schemas(
                manifest)
            options['system_prompt'] = self._tool_protocol_prompt(
                manifest, options.get('system_prompt') or '')
        history = [dict(msg) for msg in (history or [])]
        cumulative = {
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'total_tokens': 0,
        }
        rounds = []
        tool_events = []
        ended = 'completed'
        limit_message = ''
        first_round = True
        round_index = 0
        while round_index < max_rounds:
            round_index += 1
            if 'hdai.governance.service' in self.env:
                guard = self.env['hdai.governance.service']._pre_call_guard(
                    current, user=self.env.user, agent=self.agent_id)
                if guard is not True:
                    err = self._loop_error(
                        None, cumulative, 'governance_blocked',
                        message=guard)
                    yield {'type': 'result', 'result': err}
                    return
            content = ''
            reasoning = ''
            usage = {}
            tool_calls = []
            if first_round:
                first_round = False
                content_parts = []
                reasoning_parts = []
                stream_error = None
                for chunk in LLMService.stream_chat(
                        current, history, options):
                    if chunk.get('error'):
                        stream_error = chunk['error']
                        break
                    if chunk.get('content'):
                        content_parts.append(chunk['content'])
                        yield {'type': 'delta', 'delta': chunk['content']}
                    if chunk.get('reasoning'):
                        reasoning_parts.append(chunk['reasoning'])
                        yield {
                            'type': 'reasoning_delta',
                            'delta': chunk['reasoning'],
                        }
                    if chunk.get('usage'):
                        usage = chunk['usage']
                    if chunk.get('tool_calls'):
                        tool_calls = list(chunk['tool_calls'])
                if stream_error:
                    # Fallback to non-stream chat_tools on stream failure.
                    try:
                        result = LLMService.chat_tools(
                            current, history, options)
                    except LLMError as exc:
                        err = self._loop_error(
                            exc, cumulative, 'model_call_failed')
                        yield {'type': 'result', 'result': err}
                        return
                    content = result.get('content') or ''
                    reasoning = result.get('reasoning') or ''
                    usage = result.get('usage') or {}
                    tool_calls = list(result.get('tool_calls') or [])
                    if content:
                        yield {'type': 'delta', 'delta': content}
                    if reasoning:
                        yield {
                            'type': 'reasoning_delta', 'delta': reasoning}
                else:
                    content = ''.join(content_parts)
                    reasoning = ''.join(reasoning_parts)
            else:
                try:
                    result = LLMService.chat_tools(
                        current, history, options)
                except LLMError as exc:
                    err = self._loop_error(
                        exc, cumulative, 'model_call_failed')
                    yield {'type': 'result', 'result': err}
                    return
                content = result.get('content') or ''
                reasoning = result.get('reasoning') or ''
                usage = result.get('usage') or {}
                tool_calls = list(result.get('tool_calls') or [])
                if content:
                    yield {'type': 'delta', 'delta': content}
                if reasoning:
                    yield {
                        'type': 'reasoning_delta', 'delta': reasoning}
            if 'hdai.governance.service' in self.env:
                self.env['hdai.governance.service']._record_call_outcome(
                    True)
            for key in cumulative:
                cumulative[key] = cumulative.get(key, 0) + (
                    usage.get(key) or 0)
            text_calls = extract_tool_calls(content)
            if tool_calls:
                content = strip_tool_blocks(content)
            elif text_calls:
                tool_calls = text_calls
                content = strip_tool_blocks(content)
            if self._END_MESSAGE in content:
                content = content.replace(self._END_MESSAGE, '').strip()
                rounds.append(self._round_info(
                    content, reasoning, [], usage, current))
                break
            cards = []
            paused = False
            if tool_calls:
                for call in tool_calls[:max_calls]:
                    name = call.get('name') or ''
                    arguments = call.get('arguments') or {}
                    card, status, result_data = self._execute_loop_call(
                        name, arguments)
                    cards.append(card)
                    if status == 'suggestive':
                        paused = True
                        tool_events.append({
                            'name': name, 'status': 'suggestive',
                            'card': card})
                        yield {'type': 'tool_card', 'card': card}
                        break
                    if status == 'executed':
                        tool_events.append({
                            'name': name, 'status': 'executed',
                            'card': card})
                        yield {
                            'type': 'tool_call', 'name': name,
                            'card': card, 'result': result_data}
                        if (isinstance(result_data, dict)
                                and isinstance(
                                    result_data.get('action'), dict)):
                            yield {
                                'type': 'action',
                                'action': result_data['action']}
                        history.append(self._tool_result_message(
                            name, result_data))
                    else:
                        tool_events.append({
                            'name': name, 'status': 'blocked',
                            'card': card})
                        yield {'type': 'tool_card', 'card': card}
                        history.append(self._tool_error_message(
                            name, card))
            rounds.append(self._round_info(
                content, reasoning, cards, usage, current))
            if paused:
                ended = 'suggestive'
                break
            if not tool_calls:
                break
            if content:
                history.append({
                    'role': 'assistant', 'content': content})
        else:
            ended = 'limit'
            limit_message = _(
                'I have reached the maximum number of tool-calling rounds '
                '(%s) and must stop here. Please rephrase the request or '
                'continue in a new message.') % max_rounds
            yield {'type': 'limit', 'message': limit_message}
        yield {'type': 'usage', 'usage': dict(cumulative)}
        self._record_usage(rounds)
        result = {
            'ended': ended,
            'rounds': rounds,
            'tool_events': tool_events,
            'reply': '\n\n'.join(
                round_info['content'] for round_info in rounds
                if round_info['content']) or '',
            'usage': cumulative,
            'limit_message': limit_message,
        }
        yield {'type': 'result', 'result': result}

    def _run_tool_loop(self, model, history, options=None, emit=None,
                       candidates=None, manifest=None, limit_override=None):
        """Run the server-side mixed-execution tool loop.

        The model is called repeatedly with the tool manifest. Read-only
        tool calls are validated against their JSON Schema and executed as
        the calling user, and their results are fed back for the next round.
        Suggestive tool calls pause the loop with a suggestion card instead
        of executing. The loop stops on ``__end_message``, on an answer
        without tool calls, or when the configured round/call limits are
        reached (default 10 rounds / 10 calls per round).

        ``candidates`` is the ordered failover list (scenario routing,
        design 2.4): when a provider call fails after the no-tools retry,
        the loop retries the same round with the next candidate.
        ``manifest`` optionally restricts the tools offered to the model
        (e.g. to an agent's tool packages); it defaults to the caller's
        permission-filtered manifest. ``limit_override`` optionally replaces
        the loop guardrails (e.g. an agent's max steps). ``emit`` receives
        plain-data dicts so
        streaming consumers can replay the loop: ``delta``/
        ``reasoning_delta`` per round, ``tool_call`` for executed read-only
        tools, ``tool_card`` for suggestion/blocked cards, ``limit``,
        ``usage`` and ``error``. All ORM work happens in the caller's
        request context: the returned generator never touches ORM
        (error_reference 2.3/2.4/2.6).
        """
        self.ensure_one()
        options = dict(options or self._call_options(history))
        allowed = model._allowed_options()
        if not allowed['reasoning']:
            options['reasoning_strength'] = 'none'
        if not allowed['web_search']:
            options['web_search'] = False
        limits = self._loop_limits()
        if limit_override:
            limits = dict(limits, **{
                key: value for key, value in limit_override.items()
                if key in limits})
        max_rounds = limits['max_rounds']
        max_calls = limits['max_calls_per_round']
        candidates = list(candidates) if candidates else [model]
        current = candidates[0] if candidates else model
        manifest = manifest if manifest is not None \
            else self._tool_manifest()
        if manifest:
            options['tools'] = self.env['hdai.tool']._function_schemas(
                manifest)
            options['system_prompt'] = self._tool_protocol_prompt(
                manifest, options.get('system_prompt') or '')
        history = [dict(msg) for msg in (history or [])]
        cumulative = {
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'total_tokens': 0,
        }
        rounds = []
        tool_events = []
        ended = 'completed'
        limit_message = ''
        round_index = 0
        while round_index < max_rounds:
            round_index += 1
            if 'hdai.governance.service' in self.env:
                guard = self.env['hdai.governance.service']._pre_call_guard(
                    current, user=self.env.user, agent=self.agent_id)
                if guard is not True:
                    return self._loop_error(
                        None, cumulative, 'governance_blocked',
                        message=guard)
            try:
                result = LLMService.chat_tools(current, history, options)
            except LLMError as exc:
                if 'hdai.governance.service' in self.env:
                    self.env['hdai.governance.service']._record_call_outcome(
                        False)
                if options.get('tools'):
                    # The provider may reject the native tools parameter;
                    # retry once with the text protocol only.
                    retry_options = dict(options)
                    retry_options.pop('tools', None)
                    retry_options.pop('tool_choice', None)
                    try:
                        result = LLMService.chat_tools(
                            current, history, retry_options)
                        options = retry_options
                    except LLMError:
                        options = retry_options
                        result = None
                    except Exception:  # noqa: BLE001
                        _logger.exception('hdai tool loop retry failed')
                        return self._loop_error(
                            exc, cumulative, 'unexpected')
                else:
                    result = None
                if result is None:
                    # Provider failover: try the remaining candidates in
                    # priority order before giving up (design 2.4).
                    for candidate in candidates:
                        if candidate.id == current.id:
                            continue
                        try:
                            result = LLMService.chat_tools(
                                candidate, history, options)
                            current = candidate
                            break
                        except LLMError:
                            continue
                        except Exception:  # noqa: BLE001
                            _logger.exception(
                                'hdai tool loop failover failed')
                            return self._loop_error(
                                None, cumulative, 'unexpected')
                if result is None:
                    return self._loop_error(
                        exc, cumulative, 'model_call_failed')
            except Exception:  # noqa: BLE001
                _logger.exception('hdai tool loop model call failed')
                return self._loop_error(
                    None, cumulative, 'unexpected')
            if 'hdai.governance.service' in self.env:
                self.env['hdai.governance.service']._record_call_outcome(
                    True)
            content = result.get('content') or ''
            reasoning = result.get('reasoning') or ''
            usage = result.get('usage') or {}
            for key in cumulative:
                cumulative[key] = cumulative.get(key, 0) + (
                    usage.get(key) or 0)
            tool_calls = list(result.get('tool_calls') or [])
            text_calls = extract_tool_calls(content)
            if tool_calls:
                content = strip_tool_blocks(content)
            elif text_calls:
                tool_calls = text_calls
                content = strip_tool_blocks(content)
            if self._END_MESSAGE in content:
                content = content.replace(
                    self._END_MESSAGE, '').strip()
                if content and emit:
                    emit({'type': 'delta', 'delta': content})
                if reasoning and emit:
                    emit({'type': 'reasoning_delta', 'delta': reasoning})
                rounds.append(self._round_info(
                    content, reasoning, [], usage, current))
                break
            if content and emit:
                emit({'type': 'delta', 'delta': content})
            if reasoning and emit:
                emit({'type': 'reasoning_delta', 'delta': reasoning})
            cards = []
            paused = False
            if tool_calls:
                for call in tool_calls[:max_calls]:
                    name = call.get('name') or ''
                    arguments = call.get('arguments') or {}
                    card, status, result_data = self._execute_loop_call(
                        name, arguments)
                    cards.append(card)
                    if status == 'suggestive':
                        paused = True
                        tool_events.append({
                            'name': name, 'status': 'suggestive',
                            'card': card})
                        if emit:
                            emit({'type': 'tool_card', 'card': card})
                        break
                    if status == 'executed':
                        tool_events.append({
                            'name': name, 'status': 'executed',
                            'card': card})
                        if emit:
                            emit({'type': 'tool_call', 'name': name,
                                  'card': card, 'result': result_data})
                        if (isinstance(result_data, dict)
                                and result_data.get('action')
                                and isinstance(result_data['action'], dict)):
                            action_payload = result_data['action']
                            tool_events.append({
                                'name': name, 'status': 'action',
                                'action': action_payload})
                            if emit:
                                emit({'type': 'action',
                                      'action': action_payload})
                        history.append(self._tool_result_message(
                            name, result_data))
                    else:
                        tool_events.append({
                            'name': name, 'status': 'blocked',
                            'card': card})
                        if emit:
                            emit({'type': 'tool_card', 'card': card})
                        history.append(self._tool_error_message(
                            name, card))
                if len(tool_calls) > max_calls:
                    dropped = len(tool_calls) - max_calls
                    message = _('Only %s tool calls are allowed per round; '
                                '%s additional calls were ignored.') % (
                        max_calls, dropped)
                    if emit:
                        emit({'type': 'limit', 'message': message})
            rounds.append(self._round_info(
                content, reasoning, cards, usage, current))
            if paused:
                ended = 'suggestive'
                break
            if not tool_calls:
                break
            if content:
                history.append({
                    'role': 'assistant', 'content': content})
        else:
            ended = 'limit'
            limit_message = _(
                'I have reached the maximum number of tool-calling rounds '
                '(%s) and must stop here. Please rephrase the request or '
                'continue in a new message.') % max_rounds
            if rounds:
                last = dict(rounds[-1])
                last['content'] = (
                    (last['content'] + '\n\n') if last['content'] else ''
                ) + limit_message
                rounds[-1] = last
            else:
                rounds.append(self._round_info(
                    limit_message, '', [], {}, current))
            if emit:
                emit({'type': 'limit', 'message': limit_message})
        if emit:
            emit({'type': 'usage', 'usage': dict(cumulative)})
        self._record_usage(rounds)
        return {
            'ended': ended,
            'rounds': rounds,
            'tool_events': tool_events,
            'reply': '\n\n'.join(
                round_info['content'] for round_info in rounds
                if round_info['content']) or '',
            'usage': cumulative,
            'limit_message': limit_message,
        }

    @staticmethod
    def _round_info(content, reasoning, cards, usage, model=None):
        info = {
            'content': content,
            'reasoning_content': reasoning,
            'tool_cards': cards,
            'prompt_tokens': usage.get('prompt_tokens', 0),
            'completion_tokens': usage.get('completion_tokens', 0),
            'total_tokens': usage.get('total_tokens', 0),
        }
        if model is not None:
            info['model_id'] = model.id
            info['model_code'] = model.code
            info['provider_id'] = model.provider_id.id
        return info

    def _record_usage(self, rounds):
        """Persist one ``hdai.usage`` row per loop round (system-level
        metering: written as superuser, users only have read access)."""
        rows = []
        for round_info in rounds:
            if not round_info.get('total_tokens'):
                continue
            rows.append({
                'session_id': self.id,
                'user_id': self.env.user.id,
                'provider_id': round_info.get('provider_id'),
                'model_id': round_info.get('model_id'),
                'model_code': round_info.get('model_code') or '',
                'request_type': 'chat',
                'prompt_tokens': round_info.get('prompt_tokens', 0),
                'completion_tokens': round_info.get('completion_tokens', 0),
                'total_tokens': round_info.get('total_tokens', 0),
                'status': 'success',
            })
        if rows:
            self.env['hdai.usage'].sudo().create(rows)

    def _loop_error(self, exc, cumulative, code, message=None):
        """Build the error dict returned by the tool loop on failure."""
        if code == 'model_call_failed':
            return {
                'ended': 'error',
                'rounds': [],
                'tool_events': [],
                'reply': '',
                'usage': cumulative,
                'limit_message': '',
                'error': {
                    'code': 'model_call_failed',
                    'title': _('Model call failed'),
                    'message': _('The model could not be reached. Check the '
                                 'provider URL, API key and model '
                                 'configuration, then try again.'),
                    'detail': str(exc) if exc else '',
                },
            }
        if code == 'governance_blocked':
            return {
                'ended': 'error',
                'rounds': [],
                'tool_events': [],
                'reply': '',
                'usage': cumulative,
                'limit_message': '',
                'error': {
                    'code': 'governance_blocked',
                    'title': _('Request blocked'),
                    'message': message or _(
                        'The request was blocked by the governance '
                        'policy.'),
                },
            }
        return {
            'ended': 'error',
            'rounds': [],
            'tool_events': [],
            'reply': '',
            'usage': cumulative,
            'limit_message': '',
            'error': {
                'code': 'unexpected',
                'title': _('Unexpected error'),
                'message': _('An unexpected error occurred while calling the '
                             'model. Check the server logs for details.'),
            },
        }

    def _execute_loop_call(self, tool_name, arguments):
        """Validate and handle a single tool call for the loop.

        Returns ``(card, status, result)`` with status in
        ``suggestive`` / ``executed`` / ``blocked`` / ``invalid``.
        Suggestive tools only produce a card: the write path stays behind an
        explicit user confirmation on the frontend (design 2.3)."""
        tool = self.env['hdai.tool'].sudo().search(
            [('name', '=', tool_name), ('active', '=', True)], limit=1)
        if not tool:
            return (
                self._build_loop_card(tool_name, arguments, 'blocked', error={
                    'code': 'unknown_tool',
                    'message': _('Tool "%s" is not registered.') % tool_name,
                    'hint': _('The tool extension module may not be '
                              'installed.'),
                    'admin_notify': True,
                }),
                'blocked', None)
        if not self.env['hdai.tool']._check_permissions(tool):
            return (
                self._build_loop_card(tool, arguments, 'blocked', error={
                    'code': 'forbidden',
                    'message': _('You do not have permission to call tool '
                                 '"%s".') % tool_name,
                    'hint': '',
                    'admin_notify': False,
                }),
                'blocked', None)
        ok, errors = validate_tool_schema(
            arguments, tool.input_schema or {})
        if not ok:
            return (
                self._build_loop_card(tool, arguments, 'blocked', error={
                    'code': 'invalid_schema',
                    'message': _('The tool call parameters are invalid.'),
                    'hint': errors[0] if errors else '',
                    'admin_notify': False,
                }),
                'invalid', None)
        if tool.suggestive:
            # Suggestive tools with an @ai_tool implementation are invoked for
            # a read-only preview; the write path stays behind user confirm.
            from odoo.addons.hdai_base.models.hdai_tool import AI_TOOL_REGISTRY
            card = self._build_loop_card(tool, arguments, 'ready')
            card['suggestive'] = True
            if tool.name not in AI_TOOL_REGISTRY:
                return card, 'suggestive', None
            preview_result = self.env['hdai.tool'].action_invoke_tool(
                tool.name, arguments, context={'session_id': self.id})
            if isinstance(preview_result, dict):
                preview = preview_result.get('suggestion_preview')
                if preview:
                    card['suggestion_preview'] = preview
                    card['summary'] = preview.get('reason') or card.get(
                        'label')
                elif preview_result.get('message'):
                    card['summary'] = preview_result['message']
            return card, 'suggestive', preview_result
        result = self.env['hdai.tool'].action_invoke_tool(
            tool.name, arguments, context={'session_id': self.id})
        card = self._build_loop_card(
            tool, arguments, 'done', result=result)
        return card, 'executed', result

    def _build_loop_card(self, tool, arguments, status, error=None,
                         result=None):
        """Build a plain tool card (never relies on the BaseTool registry,
        so any ``hdai.tool`` registry entry can render in the chat)."""
        if isinstance(tool, str):
            name = tool
            label = tool
            icon = 'fa-question-circle'
        else:
            name = tool.name
            label = (tool.description or tool.name)[:120]
            icon = self._tool_icon(tool.category)
        card = {
            'tool': name,
            'name': name,
            'icon': icon,
            'label': label or name,
            'status': status,
            'payload': {'tool': name, 'params': arguments or {}},
        }
        if error:
            card['error'] = error
        if result is not None:
            card['summary'] = self._tool_result_summary(result)
        return card

    @staticmethod
    def _tool_icon(category):
        icons = {
            'generic': 'fa-cogs',
            'crm': 'fa-handshake-o',
            'sale': 'fa-shopping-cart',
            'account': 'fa-money',
            'stock': 'fa-cubes',
            'project': 'fa-tasks',
            'hr': 'fa-users',
            'custom': 'fa-puzzle-piece',
        }
        return icons.get(category or '', 'fa-cogs')

    @staticmethod
    def _tool_result_summary(result):
        if not isinstance(result, dict):
            return str(result)[:200]
        if result.get('status') == 'error':
            return result.get('message') or 'error'
        parts = [result.get('message') or '']
        data = result.get('data') or {}
        if not isinstance(data, dict):
            data = {}
        if 'total_count' in data:
            parts.append('%s records' % data['total_count'])
        if 'count' in data:
            parts.append('%s records' % data['count'])
        if 'groups' in data:
            parts.append('%s groups' % len(data['groups']))
        if 'suggestion_preview' in result:
            preview = result['suggestion_preview']
            parts.append('suggestion for %s #%s' % (
                preview.get('model'), preview.get('record_id')))
        return '; '.join(part for part in parts if part) or 'ok'

    @staticmethod
    def _tool_result_message(tool_name, result):
        summary = result if isinstance(result, dict) else {'result': result}
        return {
            'role': 'user',
            'content': 'Tool %s result: %s' % (
                tool_name,
                json.dumps(summary, ensure_ascii=False)[:4000]),
        }

    @staticmethod
    def _tool_error_message(tool_name, card):
        error = card.get('error') or {}
        return {
            'role': 'user',
            'content': 'Tool %s could not run: %s' % (
                tool_name, error.get('message') or 'unknown error'),
        }

    def _call_model(self, model, history, options=None):
        """Call the model and store the assistant reply; return an error dict
        or ``False`` on success. When a natural-language view payload is
        detected and a validator is installed, the returned dict contains
        ``action`` instead."""
        options = dict(options or self._call_options(history))
        allowed = model._allowed_options()
        if not allowed['reasoning']:
            options['reasoning_strength'] = 'none'
        if not allowed['web_search']:
            options['web_search'] = False
        try:
            reply, reasoning, usage = LLMService.chat(model, history, options)
        except LLMError as exc:
            return {
                'code': 'model_call_failed',
                'title': _('Model call failed'),
                'message': _('The model could not be reached. Check the '
                             'provider URL, API key and model configuration, '
                             'then try again.'),
                'detail': str(exc),
            }
        except Exception:  # noqa: BLE001
            _logger.exception('hdai model call failed')
            return {
                'code': 'unexpected',
                'title': _('Unexpected error'),
                'message': _('An unexpected error occurred while calling the '
                             'model. Check the server logs for details.'),
            }
        self.env['hdai.message'].create({
            'session_id': self.id,
            'role': 'assistant',
            'content': reply,
            'reasoning_content': reasoning,
            'prompt_tokens': usage.get('prompt_tokens', 0),
            'completion_tokens': usage.get('completion_tokens', 0),
            'total_tokens': usage.get('total_tokens', 0),
        })
        payload = self._parse_tool_payload(reply)
        if payload:
            return {'tool': build_tool_card(self.env, payload)}
        return False

    def _no_model_error(self):
        return {
            'code': 'no_model',
            'title': _('No model configured'),
            'message': _('No default model is configured. Configure a model '
                         'provider and test the connection to fill its model '
             'list before chatting.'),
        }

    def _mirror_to_channel(self, role, content):
        """Mirror a chat message into the linked Discuss channel (created by
        Open in Discuss) and mark it as processed on the link.

        Advancing ``last_message_id`` prevents the shared channel operator
        from replying a second time to messages that were already answered in
        the chat dialog: the channel keeps a faithful copy of the
        conversation while direct Discuss messages still trigger the bot."""
        if not content:
            return
        link = self.env['hdai.channel.link'].sudo().search(
            [('session_id', '=', self.id), ('active', '=', True)], limit=1)
        if not link or not link.channel_id:
            return
        channel = link.channel_id.sudo()
        author = (self.env.user.partner_id if role == 'user'
                  else link.bot_partner_id)
        channel.message_post(
            body=Markup(markdown_to_html(content)), author_id=author.id,
            message_type='comment',
            subtype_xmlid='mail.mt_comment')
        link.write({'last_message_id': max(channel.message_ids.ids or [0])})

    def _get_result(self, error=False, action=False):
        self.ensure_one()
        self.invalidate_recordset(
            ['context_tokens', 'context_usage', 'message_count'])
        result = {
            'messages': self.action_get_messages(),
            'session': {
                'id': self.id,
                'name': self.name,
                'context_tokens': self.context_tokens,
                'context_usage': self.context_usage,
                'input_tokens': self.input_tokens,
                'output_tokens': self.output_tokens,
                'message_count': self.message_count,
            },
            'error': error,
        }
        if action:
            result['action'] = action
        return result

    def _persist_rounds(self, result):
        """Persist the assistant messages produced by the tool loop."""
        for round_info in result.get('rounds') or []:
            self.env['hdai.message'].create({
                'session_id': self.id,
                'role': 'assistant',
                'content': round_info.get('content') or '',
                'reasoning_content': round_info.get(
                    'reasoning_content') or '',
                'tool_cards': round_info.get('tool_cards') or [],
                'prompt_tokens': round_info.get('prompt_tokens', 0),
                'completion_tokens': round_info.get(
                    'completion_tokens', 0),
                'total_tokens': round_info.get('total_tokens', 0),
            })

    def _prepare_model(self):
        """Resolve and persist the session model, or return an error dict."""
        model = self.model_id or self.env['hdai.model']._get_model_for_scenario(
            'chat')
        if model and not self.model_id:
            self.write({
                'model_id': model.id,
                'provider_id': model.provider_id.id,
            })
        if not model:
            return None, self._no_model_error()
        return model, False

    def action_send_message(self, content, options=None):
        self.ensure_one()
        options = options or {}
        content = (content or '').strip()
        if not content:
            raise ValueError(_('Message content cannot be empty.'))
        self.write({'state': 'open'})
        self.env['hdai.message'].create({
            'session_id': self.id,
            'role': 'user',
            'content': content,
        })
        self._mirror_to_channel('user', content)
        if self.name == _('New Session'):
            self.name = content[:30]
        model, error = self._prepare_model()
        if error:
            return self._get_result(error)
        result = self._run_tool_loop(
            model, self._build_history(), options)
        if result.get('error'):
            return self._get_result(result['error'])
        self._persist_rounds(result)
        reply = result.get('reply') or ''
        if reply:
            self._mirror_to_channel('assistant', reply)
        return self._get_result(False)

    def action_edit_and_resend(self, message_id, content):
        self.ensure_one()
        content = (content or '').strip()
        if not content:
            raise ValueError(_('Message content cannot be empty.'))
        message = self.env['hdai.message'].browse(message_id).exists()
        if message.session_id != self or message.role != 'user':
            raise ValueError(
                _('Only user messages of this session can be edited.'))
        self.write({'state': 'open'})
        message.write({'content': content})
        ordered = self.message_ids.sorted(lambda m: (m.create_date, m.id))
        index = next(
            (i for i, msg in enumerate(ordered) if msg.id == message.id), -1)
        if index >= 0 and index + 1 < len(ordered):
            ordered[index + 1:].unlink()
        if self.name == _('New Session'):
            self.name = content[:30]
        model, error = self._prepare_model()
        if error:
            return self._get_result(error)
        result = self._run_tool_loop(model, self._build_history())
        if result.get('error'):
            return self._get_result(result['error'])
        self._persist_rounds(result)
        reply = result.get('reply') or ''
        if reply:
            self._mirror_to_channel('assistant', reply)
        return self._get_result(False)

    def action_regenerate(self, message_id):
        self.ensure_one()
        message = self.env['hdai.message'].browse(message_id).exists()
        if message.session_id != self or message.role != 'assistant':
            raise ValueError(
                _('Only assistant messages of this session can be '
                  'regenerated.'))
        self.write({'state': 'open'})
        ordered = self.message_ids.sorted(lambda m: (m.create_date, m.id))
        index = next(
            (i for i, msg in enumerate(ordered) if msg.id == message.id), -1)
        if index >= 0:
            ordered[index:].unlink()
        model, error = self._prepare_model()
        if error:
            return self._get_result(error)
        result = self._run_tool_loop(model, self._build_history())
        if result.get('error'):
            return self._get_result(result['error'])
        self._persist_rounds(result)
        reply = result.get('reply') or ''
        if reply:
            self._mirror_to_channel('assistant', reply)
        return self._get_result(False)

    # ------------------------------------------------------------------
    # Ask AI response actions
    # ------------------------------------------------------------------

    def _get_reply(self, message_id):
        message = self.env['hdai.message'].browse(message_id).exists()
        if message.session_id != self or message.role != 'assistant':
            raise ValueError(
                _('Only assistant messages of this session can be used.'))
        return message

    def action_send_as_message(self, message_id):
        self.ensure_one()
        message = self._get_reply(message_id)
        if not self.context_model or not self.context_res_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('No record context'),
                    'message': _('Attach the current record context first to '
                                 'send this response as a message.'),
                    'sticky': True,
                },
            }
        self.env['hdai.action.log'].create({
            'user_id': self.env.user.id,
            'session_id': self.id,
            'action': 'send_message',
            'query': self.context_model,
            'model_name': self.context_model,
            'res_id': self.context_res_id,
            'result': message.content[:500],
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send as Message'),
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
            'context': {
                'default_composition_mode': 'comment',
                'default_model': self.context_model,
                'default_res_ids': [self.context_res_id],
                'default_body': message.content,
                'default_subject': _('AI assistant response'),
            },
        }

    def action_log_as_note(self, message_id):
        self.ensure_one()
        message = self._get_reply(message_id)
        if not self.context_model or not self.context_res_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('No record context'),
                    'message': _('Attach the current record context first to '
                                 'log this response as a note.'),
                    'sticky': True,
                },
            }
        record = self.env[self.context_model].browse(
            self.context_res_id).exists()
        if not record:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('Record not found'),
                    'message': _('The context record no longer exists.'),
                    'sticky': True,
                },
            }
        # Do not skip auto-follow: the posting user must follow the record so
        # the bus notifies the open chatter and the new note appears
        # immediately (no manual refresh needed).
        record.message_post(
            body=message.content, message_type='comment',
            subtype_xmlid='mail.mt_note')
        self.env['hdai.action.log'].create({
            'user_id': self.env.user.id,
            'session_id': self.id,
            'action': 'log_note',
            'query': self.context_model,
            'model_name': self.context_model,
            'res_id': self.context_res_id,
            'result': message.content[:500],
        })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'title': _('Note logged'),
                'message': _('The response was logged as a note on %s.') % (
                    record.display_name),
                'sticky': False,
            },
        }

    # ------------------------------------------------------------------
    # Open in Discuss (stub; extension modules may override)
    # ------------------------------------------------------------------

    def action_open_in_discuss(self):
        """Open the session in Discuss. The feature is not implemented yet;
        a friendly notification is returned until the actual integration is
        added (hdai_base is fully independent of the linkinai modules)."""
        self.ensure_one()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'warning',
                'title': _('Open in Discuss unavailable'),
                'message': _('This feature is not implemented yet and will '
                             'be available in a future release.'),
                'sticky': True,
            },
        }

    @api.model
    def action_get_list_context(self, model_name, res_ids=None,
                                total_count=None):
        """Read-only context info for list/kanban record sets."""
        if not model_name:
            return {'model': False, 'count': 0, 'res_ids': []}
        try:
            model = self.env[model_name]
        except KeyError:
            return {'model': False, 'count': 0, 'res_ids': [],
                    'display_name': model_name}
        res_ids = [int(rid) for rid in (res_ids or []) if rid]
        count = int(total_count) if total_count is not None else len(res_ids)
        return {
            'model': model_name,
            'count': max(0, count),
            'res_ids': res_ids[:200],
            'display_name': model._description or model_name,
        }

    def action_attach_list_context(self, model_name, res_ids=None,
                                   total_count=None):
        """Attach a list/kanban record-set context to the session."""
        self.ensure_one()
        info = self.action_get_list_context(
            model_name, res_ids, total_count)
        if not info['model']:
            self.write({
                'context_model': False,
                'context_res_id': False,
                'context_snapshot': False,
            })
            return {'attached': False, 'snapshot': ''}
        try:
            model = self.env[info['model']]
            label = model._description or info['model']
        except KeyError:
            label = info['model']
        if info['count']:
            snapshot = 'Viewing %s %s records (ids: %s)' % (
                info['count'], label, ', '.join(map(str, info['res_ids'])))
        else:
            snapshot = 'Viewing the %s list' % label
        self.write({
            'attach_context': True,
            'context_model': info['model'],
            'context_res_id': False,
            'context_snapshot': snapshot,
        })
        return {'attached': True, 'snapshot': snapshot}

    def _open_in_discuss(self):
        return False
