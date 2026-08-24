# -*- coding: utf-8 -*-
"""Chat-facing helpers used by the OWL dialog.

Session records stay on ``ai.chat.session``. Later product actions (edit /
regenerate, Discuss, mail compose, user layout) live here so the service
layer stays a model-call engine.
"""

import logging

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.ai_base.tools import markdown_to_html

_logger = logging.getLogger(__name__)

_SESSION_OPTION_FIELDS = (
    'model_id', 'prompt_id', 'compress_strategy',
    'attach_context', 'thinking_enabled',
)

_LAYOUT_BOOL_FIELDS = (
    'sidebar_collapsed', 'grid_sessions_collapsed', 'grid_knowledge_collapsed',
)
_LAYOUT_HEIGHT_FIELDS = (
    'grid_sessions_height', 'grid_knowledge_height',
)
_USER_BOOL_FIELDS = ('attach_context',) + _LAYOUT_BOOL_FIELDS


class AiUserSettings(models.Model):
    _name = 'ai.user.settings'
    _description = 'AI Assistant User Settings'
    _rec_name = 'user_id'

    user_id = fields.Many2one(
        'res.users', string='User', required=True,
        ondelete='cascade', index=True)
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
        """取该用户的助手设置；没有就新建一条。

        入参:
            user: ``res.users``，默认当前用户。
        返回:
            ai.user.settings: 该用户唯一的设置记录。
        """
        user = user or self.env.user
        settings = self.search([('user_id', '=', user.id)], limit=1)
        if settings:
            return settings
        return self.create({'user_id': user.id})


class AiChat(models.AbstractModel):
    _name = 'ai.chat'
    _description = 'AI Chat Facade'

    def empty_capabilities(self):
        """无可用模型时的能力占位，给前端关掉流式等开关。

        入参:
            无。
        返回:
            dict: ``streaming`` / ``thinking``，无模型时均为 ``False``。
        """
        return {
            'streaming': False,
            'thinking': False,
        }

    def model_status(self, model):
        """检查聊天模型是否就绪（提供商、地址、API Key）。

        入参:
            model: ``ai.model`` 或空。
        返回:
            tuple: ``(ready: bool, status: dict)``。
            status 含 ``code`` / ``title`` / ``message``，
            code 如 ``ready`` / ``no_model`` / ``invalid_config`` / ``missing_api_key``。
        """
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
        """列出已就绪的知识库文档，供聊天侧栏选用。未装知识库模块则空列表。

        入参:
            无。
        返回:
            list[dict]: 每项含 ``id`` / ``name``。
        """
        if 'ai.knowledge.document' not in self.env:
            return []
        return self.env['ai.knowledge.document'].search_read(
            [('state', '=', 'ready'), ('active', '=', True)],
            ['id', 'name'], order='name')

    def prompt_choices(self):
        """列出当前可用的提示词模板，给下拉框。

        入参:
            无。
        返回:
            list[dict]: 每项含 ``id`` / ``name``。
        """
        return self.env['ai.prompt.template'].search_read(
            [('is_active', '=', True)],
            ['id', 'name'], order='name')

    def defaults(self):
        """打开聊天窗时的初始状态：模型、布局、提示词、知识库、agent 占位。

        入参:
            无（读当前用户设置和默认 chat 模型）。
        返回:
            dict: 前端 OWL 用的 defaults，含 ``model_id`` / ``model_ready`` /
            ``prompts`` / ``agents``（本模块恒为 ``[]``，``ai_agent`` 会覆盖）等。
        """
        model = self.env['ai.model']._get_model_for_scenario('chat')
        model_ready, model_status = self.model_status(model)
        settings = self.env['ai.user.settings']._get_for_user()
        values = self._settings_view(settings, model)
        values.update({
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
            'agents': [],
            'default_agent_id': False,
            'knowledge_documents': self.knowledge_documents(),
        })
        return values

    def user_settings(self):
        """读当前用户的助手偏好（布局、是否附带记录上下文、默认提示词）。

        入参:
            无。
        返回:
            dict: 设置页 / 聊天窗可编辑的字段，不含 session 列表。
        """
        settings = self.env['ai.user.settings']._get_for_user()
        model = self.env['ai.model']._get_model_for_scenario('chat')
        return self._settings_view(settings, model)

    def _settings_view(self, settings, model):
        """设置页和 defaults 共用的用户偏好字段。"""
        return {
            'capabilities': (
                model._allowed_options() if model else self.empty_capabilities()),
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

    def _user_settings_vals(self, options):
        """从 options 抽出可写入 ``ai.user.settings`` 的字段。

        入参:
            options (dict): 可含 ``attach_context``、布局、``default_prompt_id``；
            会话侧 ``prompt_id`` 会落到 ``default_prompt_id``。
        返回:
            dict: 只含实际出现在 options 里的设置字段。
        """
        options = options or {}
        vals = {}
        for field in _USER_BOOL_FIELDS:
            if field in options:
                vals[field] = bool(options[field])
        for field in _LAYOUT_HEIGHT_FIELDS:
            if field in options:
                vals[field] = max(0, min(int(options[field] or 0), 10000))
        if 'sidebar_width' in options:
            vals['sidebar_width'] = max(
                180, min(int(options['sidebar_width'] or 0), 800))
        if 'default_prompt_id' in options:
            vals['default_prompt_id'] = options['default_prompt_id'] or False
        elif 'prompt_id' in options:
            vals['default_prompt_id'] = options['prompt_id'] or False
        return vals

    def save_user_settings(self, options):
        """把前端提交的用户偏好写进 ``ai.user.settings``。

        入参:
            options (dict): 可含 ``attach_context``、侧栏折叠/高度/宽度、
            ``default_prompt_id``。宽度限制 180–800，高度 0–10000。
        返回:
            bool: 恒为 ``True``。
        """
        vals = self._user_settings_vals(options)
        if vals:
            self.env['ai.user.settings']._get_for_user().write(vals)
        return True

    def messages(self, session):
        """把会话消息序列化成前端气泡列表。

        入参:
            session: 单条 ``ai.chat.session``。
        返回:
            list[dict]: ``id`` / ``role`` / ``content`` / ``reasoning_content`` /
            ``tool_cards`` / ``rag_sources`` / ``feedback`` 等。
        """
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
                'feedback': message.feedback or False,
            })
        return result

    def session_payload(self, session):
        """组装打开/刷新一个会话时前端需要的整包数据。

        入参:
            session: 单条 ``ai.chat.session``。
        返回:
            dict: ``messages`` 加 ``session``（token、prompt、是否已附上下文等）。
            ``ai_agent`` 会再往 ``session`` 里补 ``agent_id``。
        """
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
                'prompt_id': session.prompt_id.id or False,
                'attach_context': session.attach_context,
                'context_attached': bool(
                    session.context_model and (
                        session.context_res_id or session.context_snapshot)),
                'context_display_name': snapshot.splitlines()[0] if snapshot else '',
                'capabilities': (
                    model._allowed_options()
                    if model else self.empty_capabilities()),
                'thinking_enabled': session._effective_thinking(),
            },
        }

    def result(self, session, error=False, action=False):
        """在 ``session_payload`` 上附带本次操作的错误或客户端 action。

        入参:
            session: 当前会话。
            error: 失败信息 dict 或假值。
            action: 可选 ``ir.actions.*``，给前端弹窗/跳转。
        返回:
            dict: payload，含 ``error``，有 action 时多 ``action`` 键。
        """
        payload = self.session_payload(session)
        payload['error'] = error
        if action:
            payload['action'] = action
        return payload

    def _parse_document_ids(self, raw):
        """把前端传来的文档 id（列表或逗号/空格字符串）解析成 int 列表。

        入参:
            raw: ``list`` / ``tuple`` / 字符串 / 空。
        返回:
            list[int]: 合法数字 id；空输入返回 ``[]``。
        """
        if raw in (None, False, ''):
            return []
        if isinstance(raw, (list, tuple)):
            return [int(item) for item in raw if str(item).isdigit() or isinstance(item, int)]
        text = str(raw).replace('[', ' ').replace(']', ' ').replace(',', ' ')
        return [int(part) for part in text.split() if part.isdigit()]

    def set_options(self, session, options):
        """同时写会话选项和用户默认偏好。不含 ``agent_id``，聊天窗不能换 agent。

        入参:
            session: ``ai.chat.session`` 或空（只改用户设置）。
            options (dict): 会话字段如 ``model_id`` / ``prompt_id`` /
            ``compress_strategy`` / ``attach_context``，以及布局类用户字段。
        返回:
            bool: 恒为 ``True``。
        """
        options = options or {}
        if session:
            vals = {
                field: options[field]
                for field in _SESSION_OPTION_FIELDS
                if field in options
            }
            if 'thinking_enabled' in vals:
                vals['thinking_enabled'] = session._effective_thinking(
                    vals['thinking_enabled'])
            if vals:
                session.write(vals)
        user_vals = self._user_settings_vals(options)
        if user_vals:
            self.env['ai.user.settings']._get_for_user().write(user_vals)
        return True

    def send_message(self, session, content, options=None):
        """发送一轮用户消息：交给 ``ai.base.service.chat``，再返回刷新后的会话。

        入参:
            session: 单条 ``ai.chat.session``（多轮历史在这个 session 上）。
            content (str): 用户原文。
            options (dict): 透传给 service，如 ``max_rounds``。
        返回:
            dict: ``result()`` 结构（messages + session + error）。
            ``ai_agent`` 在 goal 模式下会覆盖本方法，改走后台 run。
        """
        session.ensure_one()
        result = self.env['ai.base.service'].chat(
            content, session=session, options=options or {})
        error = result.get('error') if isinstance(result, dict) else False
        return self.result(session, error=error)

    def edit_and_resend(self, session, message_id, content):
        """改一条用户消息，删掉它后面的回复，用新内容重新问模型。

        入参:
            session: 当前会话。
            message_id (int): 必须是本 session 的 user 消息。
            content (str): 编辑后的原文。
        返回:
            dict: ``result()``。空内容或角色不对抛 ``UserError``。
        """
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
        """删掉某条助手回复及其后消息，用前一条用户问题再生成一次。

        入参:
            session: 当前会话。
            message_id (int): 必须是本 session 的 assistant 消息。
        返回:
            dict: ``result()``。找不到对应 user 消息抛 ``UserError``。
        """
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
        """取出本会话的一条助手消息，供反馈 / 发邮件 / 记笔记使用。

        入参:
            session: 当前会话。
            message_id (int): 消息 id。
        返回:
            ai.chat.message: 角色必须是 assistant。否则抛 ``UserError``。
        """
        message = self.env['ai.chat.message'].browse(message_id).exists()
        if message.session_id != session or message.role != 'assistant':
            raise UserError(_('Only assistant messages of this session can be used.'))
        return message

    def submit_feedback(self, session, message_id, rating):
        """给助手消息点赞或点踩。

        入参:
            session: 当前会话。
            message_id (int): assistant 消息 id。
            rating (str): 只接受 ``up`` / ``down``。
        返回:
            bool: 成功为 ``True``。非法 rating 抛 ``UserError``。
        """
        session.ensure_one()
        if rating not in ('up', 'down'):
            raise UserError(_('Feedback must be thumbs up or thumbs down.'))
        message = self._assistant_message(session, message_id)
        message.write({'feedback': rating})
        return True

    def send_as_message(self, session, message_id):
        """把助手回复填进邮件撰写窗，发到当前附带的业务记录。

        入参:
            session: 须已 attach 单条记录上下文（``context_model`` + ``context_res_id``）。
            message_id (int): assistant 消息。
        返回:
            dict: ``mail.compose.message`` 的 act_window；没有记录上下文则是警告通知。
        """
        session.ensure_one()
        message = self._assistant_message(session, message_id)
        missing = self._missing_record_context(
            session,
            _('Attach the current record context first to '
              'send this response as a message.'))
        if missing:
            return missing
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
                'default_body': Markup(markdown_to_html(message.content)),
                'default_subject': _('AI assistant response'),
            },
        }

    def log_as_note(self, session, message_id):
        """把助手回复作为内部备注贴到当前业务记录的 chatter。

        入参:
            session: 须已 attach 单条记录。
            message_id (int): assistant 消息。
        返回:
            dict: 成功/失败的 client 通知 action。
        """
        session.ensure_one()
        message = self._assistant_message(session, message_id)
        missing = self._missing_record_context(
            session,
            _('Attach the current record context first to '
              'log this response as a note.'))
        if missing:
            return missing
        record = self.env[session.context_model].browse(
            session.context_res_id).exists()
        if not record:
            return self._notify(
                'warning', _('Record not found'),
                _('The context record no longer exists.'))
        record.message_post(
            body=Markup(markdown_to_html(message.content)),
            message_type='comment',
            subtype_xmlid='mail.mt_note')
        return self._notify(
            'success', _('Note logged'),
            _('The response was logged as a note on %s.') % (
                record.display_name),
            sticky=False)

    def _missing_record_context(self, session, message):
        if session.context_model and session.context_res_id:
            return False
        return self._notify('warning', _('No record context'), message)

    def _notify(self, ntype, title, message, sticky=True):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': ntype,
                'title': title,
                'message': message,
                'sticky': sticky,
            },
        }

    def _later_stub(self, title, message=None):
        """尚未实现功能的占位：弹出警告通知。

        入参:
            title (str): 通知标题。
            message (str): 正文，默认「后续版本提供」。
        返回:
            dict: ``ir.actions.client`` / ``display_notification``。
        """
        return self._notify(
            'warning', title,
            message or _(
                'This feature is not implemented yet and will '
                'be available in a future release.'))

    def build_tool_card(self, payload):
        """原样回传工具卡片数据，给前端展示用。

        入参:
            payload (dict): 卡片内容。
        返回:
            dict: ``payload`` 或 ``{}``。
        """
        return payload or {}

    def execute_tool(self, payload):
        """按卡片上的工具名直接调用 ``ai.tool``，不经过模型。

        入参:
            payload (dict): 含 ``tool`` 或 ``name``，以及 ``params``。
        返回:
            dict: 成功为成功通知；缺名或失败为 ``_later_stub`` 警告。
        """
        name = (payload or {}).get('tool') or (payload or {}).get('name')
        if not name:
            return self._later_stub(_('Tool cannot run'))
        result = self.env['ai.tool'].action_invoke_tool(
            name, (payload or {}).get('params') or {})
        if result.get('status') == 'success':
            return self._notify(
                'success', _('Tool executed'),
                result.get('message') or _('Done'), sticky=False)
        return self._later_stub(
            _('Tool cannot run'), result.get('message'))

    def whitelist_add(self, model_name):
        """预留：把模型加入白名单。当前未实现。

        入参:
            model_name (str): 技术名，如 ``res.partner``。
        返回:
            dict: 「功能不可用」通知。
        """
        return self._later_stub(_('Whitelist unavailable'))

    def install_module(self, module_name):
        """预留：从聊天里安装模块。当前未实现。

        入参:
            module_name (str): 模块技术名。
        返回:
            dict: 「功能不可用」通知。
        """
        return self._later_stub(_('Module install unavailable'))

    def notify_admins(self, payload):
        """预留：通知管理员。当前未实现。

        入参:
            payload: 通知内容，未使用。
        返回:
            dict: 「功能不可用」通知。
        """
        return self._later_stub(_('Admin notify unavailable'))

    def open_in_discuss(self, session):
        """预留：把会话开到 Discuss。当前未实现。

        入参:
            session: ``ai.chat.session``。
        返回:
            dict: 「功能不可用」通知。
        """
        return self._later_stub(_('Open in Discuss unavailable'))

    def record_context(self, model_name, res_id):
        """读取一条业务记录的显示名和最近 chatter，供附到会话上下文。

        入参:
            model_name (str): 模型技术名。
            res_id (int): 记录 id。
        返回:
            dict: ``model`` / ``res_id`` / ``display_name`` / ``chatter``（最多 10 条）。
            模型或记录不存在时字段为空。
        """
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
        """把当前表单记录快照写到会话，后续提问会带进 system prompt。

        入参:
            session: 当前会话。
            model_name (str): 业务模型。
            res_id (int): 记录 id。
        返回:
            dict: 成功 ``{attached: True, snapshot}``；记录无效 ``{attached: False}``。
        """
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
        """清掉会话上附带的记录/列表上下文快照。

        入参:
            session: 当前会话。
        返回:
            bool: 恒为 ``True``。
        """
        session.ensure_one()
        session.write({
            'context_model': False,
            'context_res_id': False,
            'context_snapshot': False,
        })
        return True

    def list_context(self, model_name, res_ids=None, total_count=None):
        """描述当前列表视图（模型 + 可见 id），不读记录正文。

        入参:
            model_name (str): 列表模型。
            res_ids (list): 当前页记录 id，最多用 200 个。
            total_count (int): 列表总条数；缺省用 ``len(res_ids)``。
        返回:
            dict: ``model`` / ``count`` / ``res_ids`` / ``display_name``。
        """
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
        """把列表视图摘要写成会话上下文（无单条 ``context_res_id``）。

        入参:
            session: 当前会话。
            model_name / res_ids / total_count: 同 ``list_context``。
        返回:
            dict: ``{attached, snapshot}``。模型无效时清空上下文并 ``attached=False``。
        """
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
