# -*- coding: utf-8 -*-
"""Chat-facing helpers used by the OWL dialog.

Session records stay on ``ai.chat.session``. Later product actions (edit /
regenerate, Discuss, mail compose, user layout) live here so the service
layer stays a model-call engine.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_LANGUAGE_NAMES = {
    'en_US': 'English',
    'zh_CN': '简体中文',
    'zh_TW': '繁體中文',
    'ja_JP': '日本語',
    'ko_KR': '한국어',
    'fr_FR': 'Français',
    'de_DE': 'Deutsch',
    'es_ES': 'Español',
    'pt_BR': 'Português',
    'ru_RU': 'Русский',
}

_SESSION_OPTION_FIELDS = (
    'model_id', 'prompt_id', 'compress_strategy',
    'reasoning_strength', 'attach_context',
)

_USER_OPTION_FIELDS = {
    'reasoning_strength': 'reasoning_strength',
    'attach_context': 'attach_context',
    'prompt_id': 'default_prompt_id',
}

_LAYOUT_BOOL_FIELDS = (
    'sidebar_collapsed', 'grid_sessions_collapsed', 'grid_knowledge_collapsed',
)
_LAYOUT_HEIGHT_FIELDS = (
    'grid_sessions_height', 'grid_knowledge_height',
)


class AiUserSettings(models.Model):
    _name = 'ai.user.settings'
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
    default_prompt_id = fields.Many2one(
        'ai.prompt.template', string='Default Prompt', ondelete='set null')
    attach_context = fields.Boolean(
        string='Attach Current Record Context by Default', default=True)
    sidebar_collapsed = fields.Boolean(
        string='Collapse the AI Assistant Sidebar', default=False)
    grid_sessions_collapsed = fields.Boolean(
        string='Collapse the Session History Grid', default=False)
    grid_knowledge_collapsed = fields.Boolean(
        string='Collapse the Knowledge Base Grid', default=False)
    grid_sessions_height = fields.Integer(
        string='Session History Grid Height', default=0)
    grid_knowledge_height = fields.Integer(
        string='Knowledge Base Grid Height', default=0)
    sidebar_width = fields.Integer(
        string='AI Assistant Sidebar Width', default=260)

    _unique_user = models.Constraint(
        'unique(user_id)',
        'Each user can only have one AI assistant settings record.')

    @api.model
    def _get_for_user(self, user=None):
        user = user or self.env.user
        settings = self.search([('user_id', '=', user.id)], limit=1)
        if settings:
            return settings
        return self.create({'user_id': user.id})


class AiChat(models.AbstractModel):
    _name = 'ai.chat'
    _description = 'AI Chat Facade'

    def empty_capabilities(self):
        return {
            'reasoning': False,
            'streaming': False,
        }

    def model_status(self, model):
        if not model:
            return False, {
                'code': 'no_model',
                'title': _('Model not configured'),
                'message': _('No default model is configured.'),
            }
        provider = model.provider_id
        if not provider or not provider.is_active:
            return False, {
                'code': 'invalid_config',
                'title': _('Model not ready'),
                'message': _('The provider is disabled.'),
            }
        if not (provider.endpoint or '').strip():
            return False, {
                'code': 'invalid_config',
                'title': _('Model not ready'),
                'message': _(
                    'The provider URL is not configured. Open the '
                    'provider form and set the API Endpoint.'),
            }
        if provider.provider_type != 'ollama' and not provider.sudo().api_key:
            return False, {
                'code': 'missing_api_key',
                'title': _('Model not ready'),
                'message': _(
                    'The provider "%s" requires an API key.') % (
                        provider.display_name),
            }
        return True, {
            'code': 'ready',
            'title': _('Model ready'),
            'message': model.display_name,
        }

    def knowledge_documents(self):
        if 'ai.knowledge.document' not in self.env:
            return []
        return self.env['ai.knowledge.document'].search_read(
            [('state', '=', 'ready'), ('active', '=', True)],
            ['id', 'name'], order='name')

    def prompt_choices(self):
        return self.env['ai.prompt.template'].search_read(
            [('is_active', '=', True)],
            ['id', 'name'], order='name')

    def defaults(self):
        model = self.env['ai.model']._get_model_for_scenario('chat')
        model_ready, model_status = self.model_status(model)
        settings = self.env['ai.user.settings']._get_for_user()
        return {
            'model_id': model.id if model else False,
            'model_ready': model_ready,
            'model_status': model_status,
            'model_info': {
                'name': model.display_name,
                'provider': model.provider_id.display_name,
                'context_length': model.max_context_tokens,
                'max_output_tokens': model.max_tokens_default,
                'capabilities': model._allowed_options(),
            } if model else {},
            'reasoning_strength': settings.reasoning_strength,
            'attach_context': settings.attach_context,
            'sidebar_collapsed': settings.sidebar_collapsed,
            'grid_sessions_collapsed': settings.grid_sessions_collapsed,
            'grid_knowledge_collapsed': settings.grid_knowledge_collapsed,
            'grid_sessions_height': settings.grid_sessions_height,
            'grid_knowledge_height': settings.grid_knowledge_height,
            'sidebar_width': settings.sidebar_width or 260,
            'default_prompt_id': settings.default_prompt_id.id or False,
            'prompts': self.prompt_choices(),
            'capabilities': (
                model._allowed_options() if model else self.empty_capabilities()),
            'agents': [],
            'default_agent_id': False,
            'has_knowledge': 'ai.knowledge.base' in self.env,
            'knowledge_documents': self.knowledge_documents(),
        }

    def user_settings(self):
        settings = self.env['ai.user.settings']._get_for_user()
        model = self.env['ai.model']._get_model_for_scenario('chat')
        return {
            'capabilities': (
                model._allowed_options() if model else self.empty_capabilities()),
            'language_mode': settings.language_mode or 'auto',
            'language': settings.language or '',
            'languages': [
                {'code': code, 'name': name}
                for code, name in sorted(
                    _LANGUAGE_NAMES.items(), key=lambda item: item[1])
            ],
            'reasoning_strength': settings.reasoning_strength,
            'attach_context': settings.attach_context,
            'sidebar_collapsed': settings.sidebar_collapsed,
            'grid_sessions_collapsed': settings.grid_sessions_collapsed,
            'grid_knowledge_collapsed': settings.grid_knowledge_collapsed,
            'grid_sessions_height': settings.grid_sessions_height,
            'grid_knowledge_height': settings.grid_knowledge_height,
            'sidebar_width': settings.sidebar_width or 260,
            'has_knowledge': 'ai.knowledge.base' in self.env,
            'default_prompt_id': settings.default_prompt_id.id or False,
            'prompts': self.prompt_choices(),
        }

    def save_user_settings(self, options):
        options = options or {}
        settings = self.env['ai.user.settings']._get_for_user()
        vals = {}
        if options.get('language_mode') in ('auto', 'system', 'specific'):
            vals['language_mode'] = options['language_mode']
        language = (options.get('language') or '').strip()
        if options.get('language_mode') == 'specific':
            if language not in _LANGUAGE_NAMES:
                raise UserError(_('Please select a valid language.'))
            vals['language'] = language
        elif 'language_mode' in options:
            vals['language'] = False
        if options.get('reasoning_strength') in ('none', 'low', 'medium', 'high'):
            vals['reasoning_strength'] = options['reasoning_strength']
        for field in ('attach_context',):
            if field in options:
                vals[field] = bool(options[field])
        for field in _LAYOUT_BOOL_FIELDS:
            if field in options:
                vals[field] = bool(options[field])
        for field in _LAYOUT_HEIGHT_FIELDS:
            if field in options:
                vals[field] = max(0, min(int(options[field] or 0), 10000))
        if 'sidebar_width' in options:
            vals['sidebar_width'] = max(180, min(int(options['sidebar_width'] or 0), 800))
        if 'default_prompt_id' in options:
            vals['default_prompt_id'] = options['default_prompt_id'] or False
        if vals:
            settings.write(vals)
        return True

    def messages(self, session):
        session.ensure_one()
        result = []
        for message in session.message_ids.sorted(lambda m: (m.create_date, m.id)):
            result.append({
                'id': message.id,
                'role': message.role,
                'content': message.content,
                'reasoning_content': message.reasoning_content,
                'total_tokens': message.total_tokens,
                'create_date': message.create_date,
                'tool_cards': message.tool_cards or [],
                'rag_sources': message.rag_sources or [],
            })
        return result

    def session_payload(self, session):
        session.ensure_one()
        session.invalidate_recordset([
            'input_tokens', 'output_tokens', 'context_tokens',
            'context_usage', 'message_count',
        ])
        model = session.model_id
        snapshot = session.context_snapshot or ''
        return {
            'messages': self.messages(session),
            'session': {
                'id': session.id,
                'name': session.name,
                'context_tokens': session.context_tokens,
                'context_usage': session.context_usage,
                'input_tokens': session.input_tokens,
                'output_tokens': session.output_tokens,
                'message_count': session.message_count,
                'reasoning_strength': session.reasoning_strength,
                'prompt_id': session.prompt_id.id or False,
                'attach_context': session.attach_context,
                'context_attached': bool(
                    session.context_model and (
                        session.context_res_id or session.context_snapshot)),
                'context_display_name': snapshot.splitlines()[0] if snapshot else '',
                'capabilities': (
                    model._allowed_options()
                    if model else self.empty_capabilities()),
            },
        }

    def result(self, session, error=False, action=False):
        payload = self.session_payload(session)
        payload['error'] = error
        if action:
            payload['action'] = action
        return payload

    def _parse_document_ids(self, raw):
        if raw in (None, False, ''):
            return []
        if isinstance(raw, (list, tuple)):
            return [int(item) for item in raw if str(item).isdigit() or isinstance(item, int)]
        text = str(raw).replace('[', ' ').replace(']', ' ').replace(',', ' ')
        return [int(part) for part in text.split() if part.isdigit()]

    def set_options(self, session, options):
        options = options or {}
        if (options.get('reasoning_strength')
                and options['reasoning_strength'] not in
                ('none', 'low', 'medium', 'high')):
            raise UserError(_('Invalid thinking strength.'))
        if session:
            vals = {
                field: options[field]
                for field in _SESSION_OPTION_FIELDS
                if field in options
            }
            if vals:
                session.write(vals)
        user_vals = {}
        for field, user_field in _USER_OPTION_FIELDS.items():
            if field in options:
                user_vals[user_field] = options[field]
        if 'prompt_id' in options:
            user_vals['default_prompt_id'] = options['prompt_id'] or False
        for field in _LAYOUT_BOOL_FIELDS:
            if field in options:
                user_vals[field] = bool(options[field])
        for field in _LAYOUT_HEIGHT_FIELDS:
            if field in options:
                user_vals[field] = max(0, min(int(options[field] or 0), 10000))
        if 'sidebar_width' in options:
            user_vals['sidebar_width'] = max(
                180, min(int(options['sidebar_width'] or 0), 800))
        if user_vals:
            self.env['ai.user.settings']._get_for_user().write(user_vals)
        return True

    def send_message(self, session, content, options=None):
        session.ensure_one()
        result = self.env['ai.base.service'].chat(
            content, session=session, options=options or {})
        error = result.get('error') if isinstance(result, dict) else False
        return self.result(session, error=error)

    def edit_and_resend(self, session, message_id, content):
        session.ensure_one()
        content = (content or '').strip()
        if not content:
            raise UserError(_('Message content cannot be empty.'))
        message = self.env['ai.chat.message'].browse(message_id).exists()
        if message.session_id != session or message.role != 'user':
            raise UserError(_('Only user messages of this session can be edited.'))
        message.write({'content': content})
        ordered = session.message_ids.sorted(lambda m: (m.create_date, m.id))
        index = next((i for i, msg in enumerate(ordered) if msg.id == message.id), -1)
        if index >= 0 and index + 1 < len(ordered):
            ordered[index + 1:].unlink()
        if session.name == _('New Session'):
            session.name = content[:30]
        result = self.env['ai.base.service'].chat(
            content, session=session, persist_user=False)
        return self.result(session, error=result.get('error'))

    def regenerate(self, session, message_id):
        session.ensure_one()
        message = self.env['ai.chat.message'].browse(message_id).exists()
        if message.session_id != session or message.role != 'assistant':
            raise UserError(_(
                'Only assistant messages of this session can be regenerated.'))
        ordered = session.message_ids.sorted(lambda m: (m.create_date, m.id))
        index = next((i for i, msg in enumerate(ordered) if msg.id == message.id), -1)
        query = ''
        if index > 0:
            previous = ordered[index - 1]
            if previous.role == 'user':
                query = previous.content or ''
        if index >= 0:
            ordered[index:].unlink()
        if not query:
            raise UserError(_('No user message found to regenerate from.'))
        result = self.env['ai.base.service'].chat(
            query, session=session, persist_user=False)
        return self.result(session, error=result.get('error'))

    def _assistant_message(self, session, message_id):
        message = self.env['ai.chat.message'].browse(message_id).exists()
        if message.session_id != session or message.role != 'assistant':
            raise UserError(_('Only assistant messages of this session can be used.'))
        return message

    def send_as_message(self, session, message_id):
        session.ensure_one()
        message = self._assistant_message(session, message_id)
        if not session.context_model or not session.context_res_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('No record context'),
                    'message': _(
                        'Attach the current record context first to '
                        'send this response as a message.'),
                    'sticky': True,
                },
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send as Message'),
            'res_model': 'mail.compose.message',
            'view_mode': 'form',
            'views': [[False, 'form']],
            'target': 'new',
            'context': {
                'default_composition_mode': 'comment',
                'default_model': session.context_model,
                'default_res_ids': [session.context_res_id],
                'default_body': message.content,
                'default_subject': _('AI assistant response'),
            },
        }

    def log_as_note(self, session, message_id):
        session.ensure_one()
        message = self._assistant_message(session, message_id)
        if not session.context_model or not session.context_res_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'warning',
                    'title': _('No record context'),
                    'message': _(
                        'Attach the current record context first to '
                        'log this response as a note.'),
                    'sticky': True,
                },
            }
        record = self.env[session.context_model].browse(
            session.context_res_id).exists()
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
        record.message_post(
            body=message.content, message_type='comment',
            subtype_xmlid='mail.mt_note')
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

    def _later_stub(self, title, message=None):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'warning',
                'title': title,
                'message': message or _(
                    'This feature is not implemented yet and will '
                    'be available in a future release.'),
                'sticky': True,
            },
        }

    def build_tool_card(self, payload):
        return payload or {}

    def execute_tool(self, payload):
        name = (payload or {}).get('tool') or (payload or {}).get('name')
        if not name:
            return self._later_stub(_('Tool cannot run'))
        result = self.env['ai.tool'].action_invoke_tool(
            name, (payload or {}).get('params') or {})
        if result.get('status') == 'success':
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'success',
                    'title': _('Tool executed'),
                    'message': result.get('message') or _('Done'),
                },
            }
        return self._later_stub(
            _('Tool cannot run'), result.get('message'))

    def whitelist_add(self, model_name):
        return self._later_stub(_('Whitelist unavailable'))

    def install_module(self, module_name):
        return self._later_stub(_('Module install unavailable'))

    def notify_admins(self, payload):
        return self._later_stub(_('Admin notify unavailable'))

    def open_in_discuss(self, session):
        return self._later_stub(_('Open in Discuss unavailable'))

    def record_context(self, model_name, res_id):
        empty = {
            'model': False, 'res_id': False, 'display_name': '', 'chatter': [],
        }
        if not model_name or not res_id:
            return empty
        try:
            record = self.env[model_name].browse(int(res_id)).exists()
        except KeyError:
            return empty
        if not record:
            return {
                'model': model_name, 'res_id': int(res_id),
                'display_name': '', 'chatter': [],
            }
        chatter = []
        if 'message_ids' in record._fields:
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

    def attach_context(self, session, model_name, res_id):
        session.ensure_one()
        context = self.record_context(model_name, res_id)
        if not context.get('res_id'):
            return {'attached': False}
        lines = [
            'Current record: %s (%s)' % (context['display_name'], context['model']),
        ]
        for item in context['chatter']:
            lines.append('- %s: %s' % (item['author'], item['body']))
        session.write({
            'attach_context': True,
            'context_model': context['model'],
            'context_res_id': context['res_id'],
            'context_snapshot': '\n'.join(lines),
            'res_model': context['model'],
            'res_id': context['res_id'],
        })
        return {'attached': True, 'snapshot': session.context_snapshot}

    def clear_context(self, session):
        session.ensure_one()
        session.write({
            'context_model': False,
            'context_res_id': False,
            'context_snapshot': False,
        })
        return True

    def list_context(self, model_name, res_ids=None, total_count=None):
        if not model_name:
            return {'model': False, 'count': 0, 'res_ids': []}
        try:
            model = self.env[model_name]
        except KeyError:
            return {
                'model': False, 'count': 0, 'res_ids': [],
                'display_name': model_name,
            }
        res_ids = [int(rid) for rid in (res_ids or []) if rid]
        count = int(total_count) if total_count is not None else len(res_ids)
        return {
            'model': model_name,
            'count': max(0, count),
            'res_ids': res_ids[:200],
            'display_name': model._description or model_name,
        }

    def attach_list_context(self, session, model_name, res_ids=None, total_count=None):
        session.ensure_one()
        info = self.list_context(model_name, res_ids, total_count)
        if not info['model']:
            session.write({
                'context_model': False,
                'context_res_id': False,
                'context_snapshot': False,
            })
            return {'attached': False, 'snapshot': ''}
        label = info.get('display_name') or info['model']
        if info['count']:
            snapshot = 'Viewing %s %s records (ids: %s)' % (
                info['count'], label, ', '.join(map(str, info['res_ids'])))
        else:
            snapshot = 'Viewing the %s list' % label
        session.write({
            'attach_context': True,
            'context_model': info['model'],
            'context_res_id': False,
            'context_snapshot': snapshot,
            'res_model': info['model'],
        })
        return {'attached': True, 'snapshot': snapshot}
