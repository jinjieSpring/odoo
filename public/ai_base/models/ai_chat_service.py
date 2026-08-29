# -*- coding: utf-8 -*-
"""Chat service: system + history, tool loop, usage logs.

Example (from another Odoo module)::

    result = self.env['ai.chat.service'].chat(
        prompt_key='sale.email.draft',
        record=self,
        context={'tone': 'formal'},
        model_code='gpt-4o-mini',
    )
    reply = result['reply']

    vectors = self.env['ai.chat.service'].embedding(['hello world'])

RAG lives in the optional ai_knowledge module (inherits this model).
"""

import json
import logging
import re
import time
import traceback

from odoo import _, models
from odoo.exceptions import UserError

from ..tools import AiError, get_provider
from .ai_tool import extract_tool_calls, strip_tool_blocks

_logger = logging.getLogger(__name__)

_INJECTION_RE = re.compile(
    r'(ignore (all|any|previous|above) instructions|you are now|jailbreak)',
    re.IGNORECASE,
)
_SENSITIVE_FIELD_HINTS = (
    'password', 'api_key', 'api_secret', 'credit_card', 'ssn', 'id_number',
)


class AiChatService(models.AbstractModel):
    _name = 'ai.chat.service'
    _description = 'AI Chat Service'

    # ------------------------------------------------------------------
    # Extension hooks
    # ------------------------------------------------------------------

    def on_ai_request_before(self, payload):
        """请求发出前的扩展钩子，可改 payload。其他模块可继承重写。

        入参:
            payload (dict): 即将发给厂商的请求包，常见键 ``content`` / ``session`` /
                ``model`` / ``options`` / ``scenario``。
        返回:
            dict: 原样或修改后的 payload。
        """
        return payload

    def on_ai_request_done(self, payload, result):
        """厂商调用成功后的扩展钩子。其他模块可在此追加副作用。

        入参:
            payload (dict): 请求前的 payload。
            result (dict): 本轮结果，含 ``reply`` / ``usage`` / ``rounds`` 等。
        返回:
            dict: 原样或修改后的 result。
        """
        return result

    def on_ai_request_error(self, payload, error):
        """厂商调用失败时的扩展钩子，默认只回传错误，不吞异常。

        入参:
            payload (dict): 失败时的请求包。
            error: 异常对象，或错误 dict。
        返回:
            原样 error。
        """
        return error

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self, content=None, prompt_key=None, record=None, context=None,
        stream=False, model_code=None, session=None, options=None,
        history=None, model=None, scenario='chat', persist_user=True,
    ):
        """同步聊天：组 system + 历史，跑工具循环，可选写入 session。

        入参:
            content (str): 用户本轮原文。有 ``prompt_key`` 且模板能渲出 user 时可省略。
            prompt_key (str): ``ai.prompt.template`` 的 code。
            record: 可选业务记录，用来渲染模板 / 拼记录快照。
            context (dict): 模板额外变量。
            stream (bool): 此处不用；流式走 ``stream_chat``。
            model_code (str): ``ai.model.code``，用来解析模型。
            session: 可选 ``ai.chat.session``；有则落库历史并带会话选项。
            options (dict): 调用选项，如 ``system_prompt`` / ``max_rounds`` / ``skip_memory``。
            history (list): 无 session 时的消息列表 ``[{role, content}, ...]``。
            model: 已解析的 ``ai.model`` 记录。
            scenario (str): 场景键，默认 ``chat``，影响选模型和日志。
            persist_user (bool): 有 session 时是否先写入一条 user 消息。
        返回:
            dict: ``reply`` 最终回复；``usage`` token 累计；``rounds`` 工具循环各轮；
            ``latency_ms`` 耗时。失败时可能带 ``error``。空内容会抛 ``UserError``。
        """
        options = dict(options or {})
        context = dict(context or {})
        if prompt_key:
            template = self.env['ai.prompt.template']._get_by_code(prompt_key)
            if not template:
                raise UserError(_('Unknown prompt key "%s".') % prompt_key)
            parts = template.render_parts(context, record=record)
            if parts.get('system') and not options.get('system_prompt'):
                options['system_prompt'] = parts['system']
            if not content:
                content = parts.get('user') or ''
        content = (content or '').strip()
        if not content:
            raise UserError(_('Message content cannot be empty.'))
        content = self._guard_input(content)
        if model_code and not model:
            model = self.env['ai.model']._get_by_code(model_code)
        model = self._resolve_model(
            model or (session.model_id if session else None), scenario)
        payload = {
            'content': content, 'session': session, 'model': model,
            'options': options, 'scenario': scenario,
        }
        payload = self.on_ai_request_before(payload) or payload
        self._check_rate_limit()
        try:
            if session:
                self._prepare_session_turn(
                    session, model, content, persist_user=persist_user)
                history = session._build_history()
                options = session._call_options(options)
                options['session'] = session
            else:
                history = list(history or [])
                history.append({'role': 'user', 'content': content})
            messages = self._system_messages(
                session, options, content, record=record) + history
            result = self._run_tool_loop(model, messages, options)
            result['reply'] = self._guard_output(result.get('reply') or '')
            if session:
                self._persist_rounds(session, result)
            else:
                self._log_request(
                    request_type=self._request_type_for_scenario(scenario),
                    scenario_key=scenario,
                    session=session, model=model, result=result,
                    input_summary=content)
            result = self.on_ai_request_done(payload, result) or result
            return result
        except Exception as exc:
            self._log_request_error(scenario, session, model, content, exc)
            self.on_ai_request_error(payload, exc)
            raise

    def rag_chat(self, query, **kwargs):
        """知识库问答入口。本模块只占位；装 ``ai_knowledge`` 后才有实现。

        入参:
            query (str): 用户问题。
            **kwargs: 预留给知识库模块（session、document_ids 等）。
        返回:
            未安装知识库时抛 ``UserError``。安装后由子类返回聊天结果 dict。
        """
        raise UserError(_(
            'Install the AI Knowledge module to use knowledge-base chat.'))

    def retrieve(self, query, top_k=5, document_ids=None, knowledge_ids=None, model=None):
        """检索知识片段。本模块恒返回空列表；``ai_knowledge`` 会重写。

        入参:
            query (str): 检索文本。
            top_k (int): 最多返回条数，默认 5。
            document_ids: 限定文档 id 列表。
            knowledge_ids: 限定知识库 id 列表。
            model: 可选 embedding 模型。
        返回:
            list: 知识片段；未安装知识库时为 ``[]``。
        """
        return []

    def embedding(self, texts, model=None, model_code=None):
        """把文本列表做成向量，并写一条 embed 请求日志。

        入参:
            texts (list[str]): 要向量化的文本。
            model: 可选 ``ai.model``（须是 embedding 场景）。
            model_code (str): 按 code 解析模型；有 ``model`` 时忽略。
        返回:
            list[list[float]]: 与 ``texts`` 等长的向量列表。
            厂商失败时抛 ``UserError``。
        """
        if model_code and not model:
            model = self.env['ai.model']._get_by_code(model_code)
        model = self._resolve_model(model, 'embed')
        started = time.time()
        client = get_provider(model.provider_id)
        try:
            vectors = client.embedding(model, list(texts))
            status = 'success'
            error = False
        except AiError as exc:
            vectors = [[] for _ in texts]
            status = 'error'
            error = str(exc)
        self._log(
            request_type='embed',
            provider_id=model.provider_id.id,
            model_id=model.id,
            model_code=model.code,
            scenario_key='embed',
            latency_ms=int((time.time() - started) * 1000),
            status=status,
            error_message=error,
        )
        if status == 'error':
            raise UserError(error)
        return vectors

    def _prepare_session_turn(self, session, model, content, persist_user=True):
        """给会话补模型、标成进行中，并按需写入本轮用户消息。"""
        if not session.model_id:
            session.write({
                'model_id': model.id,
                'provider_id': model.provider_id.id,
            })
        session.write({'state': 'open'})
        if persist_user:
            self.env['ai.chat.message'].create({
                'session_id': session.id,
                'role': 'user',
                'content': content,
            })
            if session.name == _('New Session'):
                session.name = content[:30]

    def embed(self, texts, model=None, model_code=None):
        """``embedding()`` 的别名，入参返回值相同。

        入参 / 返回: 见 ``embedding``。
        """
        return self.embedding(texts, model=model, model_code=model_code)

    def stream_chat(self, content, session, options=None):
        """流式聊天：在本方法里做完全部 ORM，返回可给 SSE 回放的纯数据事件。

        HTTP 生成器不应再碰 ORM。校验失败不抛异常，而是把 error 放进返回值。

        入参:
            content (str): 用户本轮原文。
            session: 必填 ``ai.chat.session``。
            options (dict): 会话调用选项。
        返回:
            dict:
                ``result``: 与 ``chat`` 类似的结果（含 ``reply`` / ``rounds`` / ``usage``）。
                ``events``: SSE 事件列表，如 ``delta`` / ``tool_call`` / ``usage``。
                ``error``: 失败时为 ``{message, code}``，成功多为 ``result`` 里的 error 或假值。
        """
        events = []
        options = dict(options or {})
        content = (content or '').strip()
        if not content:
            return {'error': {'message': _('Message content cannot be empty.'),
                              'code': 'empty'}, 'events': []}
        try:
            content = self._guard_input(content)
            self._check_rate_limit()
        except UserError as exc:
            return {'error': {'message': str(exc), 'code': 'blocked'}, 'events': []}
        model = session.model_id or self.env['ai.model']._get_model_for_scenario('chat')
        if not model:
            return {
                'error': {
                    'message': _('No default model is configured.'),
                    'code': 'no_model',
                },
                'events': [],
            }
        if not model._allowed_options().get('streaming'):
            return {
                'error': {
                    'message': _('Streaming is disabled for this model.'),
                    'code': 'streaming_disabled',
                },
                'events': [],
            }
        self._prepare_session_turn(session, model, content)
        options = session._call_options(options)
        options['session'] = session
        history = session._build_history()
        messages = self._system_messages(session, options, content) + history
        try:
            result = self._run_tool_loop(
                model, messages, options, emit=lambda event: events.append(event))
            result['reply'] = self._guard_output(result.get('reply') or '')
            self._persist_rounds(session, result)
            return {'result': result, 'events': events, 'error': result.get('error')}
        except Exception as exc:
            self._log_request_error('chat', session, model, content, exc)
            raise

    def invoke_tool(self, tool_name, params=None, context=None):
        """按名称直接调一次已注册工具，不经过模型。

        入参:
            tool_name (str): 工具 name。
            params (dict): 工具参数。
            context (dict): 额外调用上下文。
        返回:
            dict: ``ai.tool.action_invoke_tool`` 的结果，一般含 ``status`` / ``message``。
        """
        return self.env['ai.tool'].action_invoke_tool(tool_name, params, context)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def render_prompt(self, code_or_template, context=None, company=None, record=None):
        """渲染一条提示词模板，得到最终文本。

        入参:
            code_or_template: 模板 code（str），或已有 ``render`` 方法的模板记录。
            context (dict): 模板变量。
            company: 按公司查找模板时用。
            record: 绑定的业务记录。
        返回:
            str: 渲染结果；找不到模板时返回空字符串。
        """
        if hasattr(code_or_template, 'render'):
            return code_or_template.render(context or {}, record=record)
        template = self.env['ai.prompt.template']._get_by_code(
            code_or_template, company=company)
        if not template:
            return ''
        return template.render(context or {}, record=record)

    def _resolve_model(self, model=None, scenario='chat'):
        """选定本次可用的 ``ai.model``：传入的不可用则丢弃，再按场景取默认。

        入参:
            model: 候选 ``ai.model``，可空。
            scenario (str): 场景，如 ``chat`` / ``embed``。
        返回:
            ai.model: 可用模型记录。没有任何默认模型时抛 ``UserError``。
        """
        if model and not model._is_usable():
            model = self.env['ai.model']
        if model:
            return model
        resolved = self.env['ai.model']._get_model_for_scenario(scenario)
        if not resolved:
            raise UserError(_(
                'No default model is configured. Configure a provider and '
                'a model, then test the connection before using AI.'))
        return resolved

    def _param_int(self, key, default):
        """读系统参数并转成 int。

        入参:
            key (str): ``ir.config_parameter`` 的 key，如 ``ai_base.max_tool_rounds``。
            default: 缺省或无法解析时的回退值。
        返回:
            int
        """
        return int(self.env['ir.config_parameter'].sudo().get_param(key, str(default)) or default)

    def _tool_loop_limits(self, options, session=None):
        """工具循环上限：调用选项优先，否则用系统参数。

        入参:
            options (dict): 可含 ``max_rounds`` / ``max_tool_calls_per_round``；>0 优先生效。
            session: 可选会话（本模块不用；其他模块可重写时读取）。
        返回:
            tuple: ``(max_rounds, max_calls_per_round)``，均至少为 1。
        """
        options = options or {}
        explicit_rounds = int(options.get('max_rounds') or 0)
        explicit_calls = int(options.get('max_tool_calls_per_round') or 0)
        max_rounds = explicit_rounds or self._param_int('ai_base.max_tool_rounds', 10)
        max_calls = explicit_calls or self._param_int(
            'ai_base.max_tool_calls_per_round', 10)
        return max(1, max_rounds), max(1, max_calls)

    def _rate_limit_request_types(self):
        """计入限流的无会话 ``ai.request.log.request_type``（向量化等）。"""
        return ('chat', 'rag', 'embed', 'agent')

    def _rate_limit_count(self, start, user_id=None):
        """最近窗口内的模型调用次数：助手消息 + 无会话请求日志。"""
        msg_domain = [
            ('role', '=', 'assistant'),
            ('model_id', '!=', False),
            ('create_date', '>=', start),
        ]
        log_domain = [
            ('request_type', 'in', self._rate_limit_request_types()),
            ('create_date', '>=', start),
        ]
        if user_id:
            msg_domain.append(('session_id.user_id', '=', user_id))
            log_domain.append(('user_id', '=', user_id))
        return (
            self.env['ai.chat.message'].sudo().search_count(msg_domain)
            + self.env['ai.request.log'].sudo().search_count(log_domain)
        )

    def _check_rate_limit(self):
        """按最近 60 秒检查全站 / 当前用户的请求次数。"""
        global_limit = self._param_int('ai_base.rate_limit_global_per_minute', 120)
        user_limit = self._param_int('ai_base.rate_limit_user_per_minute', 30)
        from datetime import timedelta
        from odoo import fields as odoo_fields
        start = odoo_fields.Datetime.now() - timedelta(seconds=60)
        if global_limit > 0 and self._rate_limit_count(start) >= global_limit:
            raise UserError(_('The global AI rate limit has been reached. Retry shortly.'))
        if user_limit > 0 and self._rate_limit_count(
                start, user_id=self.env.user.id) >= user_limit:
            raise UserError(_('You have reached the per-user AI rate limit. Retry shortly.'))

    def _guard_input(self, text):
        """校验用户输入：超长、敏感词拦截；疑似注入只记日志不拦截。

        入参:
            text (str): 用户原文。
        返回:
            str: 原文本。超长或命中敏感词抛 ``UserError``。
        """
        max_len = self._param_int('ai_base.max_input_chars', 20000)
        if max_len and len(text) > max_len:
            raise UserError(_('Input exceeds the maximum length of %s characters.') % max_len)
        blocked = self._sensitive_hits(text, direction='input')
        if blocked:
            raise UserError(_('Input contains blocked sensitive terms: %s') % ', '.join(blocked))
        if _INJECTION_RE.search(text):
            _logger.warning('ai_base possible prompt injection from uid=%s', self.env.uid)
        return text

    def _guard_output(self, text):
        """清洗模型输出：命中敏感词的片段替换成 ``***``。

        入参:
            text (str): 模型回复。
        返回:
            str: 脱敏后的文本。
        """
        hits = self._sensitive_hits(text, direction='output')
        for word in hits:
            text = re.sub(re.escape(word), '***', text, flags=re.IGNORECASE)
        return text

    def _sensitive_hits(self, text, direction='input'):
        """在文本里查找系统参数 ``ai_base.sensitive_words``（逗号分隔）中的词。

        入参:
            text (str): 待扫描文本。
            direction (str): ``input`` / ``output``，当前实现未区分，仅预留。
        返回:
            list[str]: 命中的原词，未命中为空列表。
        """
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'ai_base.sensitive_words', '') or ''
        words = [part.strip() for part in raw.split(',') if part.strip()]
        if not words or not text:
            return []
        hits = []
        lower = text.lower()
        for word in words:
            if word.lower() in lower:
                hits.append(word)
        return hits

    def _request_type_for_scenario(self, scenario, default='chat'):
        """Map a chat scenario key to ``ai.request.log.request_type``."""
        return {
            'rag': 'rag',
            'embed': 'embed',
        }.get(scenario, default)

    def _log_request_error(self, scenario, session, model, content, exc):
        """会话失败写在助手消息上；没有会话才写 ``ai.request.log``。"""
        if session:
            self._persist_error_message(session, model, {
                'message': str(exc),
            })
            return
        vals = {
            'request_type': self._request_type_for_scenario(scenario),
            'scenario_key': scenario or 'chat',
            'status': 'error',
            'error_message': str(exc)[:500],
            'error_traceback': traceback.format_exc()[:8000],
            'input_summary': (content or '')[:4000],
        }
        if model:
            vals['provider_id'] = model.provider_id.id
            vals['model_id'] = model.id
            vals['model_code'] = model.code
        self._log(**vals)

    def _log(self, **vals):
        """写入一条 ``ai.request.log``，自动补当前用户和公司。

        入参:
            **vals: 日志字段，如 ``request_type`` / ``model_id`` / ``status``。
        返回:
            ai.request.log: 新建的日志记录。
        """
        vals.setdefault('user_id', self.env.user.id)
        vals.setdefault('company_id', self.env.company.id)
        return self.env['ai.request.log'].sudo().create(vals)

    def _log_request(self, request_type, scenario_key, session, model, result, input_summary=''):
        """从一次 chat 结果整理字段，再调用 ``_log``。

        入参:
            request_type (str): ``chat`` / ``embed`` 等。
            scenario_key (str): 场景键，写入日志。
            session: ``ai.chat.session`` 或空。
            model: 本次 ``ai.model``。
            result (dict): ``_run_tool_loop`` / ``chat`` 的返回值。
            input_summary (str): 输入摘要，截到 4000 字。
        返回:
            None（副作用是建日志）。
        """
        error = result.get('error') or {}
        request_type = self._request_type_for_scenario(
            scenario_key, request_type)
        self._log(
            request_type=request_type,
            scenario_key=scenario_key,
            session_id=session.id if session else False,
            provider_id=model.provider_id.id,
            model_id=model.id,
            model_code=model.code,
            prompt_tokens=(result.get('usage') or {}).get('prompt_tokens') or 0,
            completion_tokens=(result.get('usage') or {}).get('completion_tokens') or 0,
            total_tokens=(result.get('usage') or {}).get('total_tokens') or 0,
            latency_ms=result.get('latency_ms') or 0,
            status='error' if error else 'success',
            error_message=error.get('message') if error else False,
            input_summary=(input_summary or '')[:4000],
            output_summary=(result.get('reply') or '')[:4000],
        )

    def _knowledge_system_parts(self, session, query):
        """拼进 system prompt 的知识库片段。本模块返回空；``ai_knowledge`` 重写。

        入参:
            session: 当前会话或空。
            query (str): 本轮用户问题，用于检索。
        返回:
            list[str]: 要拼进 system 的文本块。
        """
        return []

    def _system_content_parts(self, session=None, options=None, query=None, record=None):
        """拼 system 正文（不含界面语言指令）。其他模块可追加文本块。

        入参:
            session: 可选会话，取其 ``prompt_id`` / 上下文快照。
            options (dict): 无 session 模板时可用 ``system_prompt``。
            query (str): 本轮用户问题。
            record: 可选业务记录，生成字段快照。
        返回:
            list[str]: 文本块，稍后与语言指令拼成一条 system。
        """
        options = options or {}
        parts = []
        if session and session.prompt_id:
            try:
                parts.append(session.prompt_id.render({
                    'user': self.env.user.name,
                    'company': self.env.company.name,
                    'query': query or '',
                }, record=record))
            except UserError as exc:
                _logger.warning('ai_base prompt render failed: %s', exc)
                parts.append(session.prompt_id._combined_content() or '')
        elif options.get('system_prompt'):
            parts.append(options['system_prompt'])
        if record is not None:
            snapshot = self._record_snapshot(record)
            if snapshot:
                parts.append(_('Current business record:\n%s') % snapshot)
        if session and session.attach_context and session.context_snapshot:
            parts.append(session.context_snapshot)
        elif session and session.res_model and session.res_id and record is None:
            if session.res_model in self.env:
                rec = self.env[session.res_model].browse(session.res_id).exists()
                if rec:
                    snapshot = self._record_snapshot(rec)
                    if snapshot:
                        parts.append(_('Current business record:\n%s') % snapshot)
        parts.extend(self._knowledge_system_parts(session, query))
        return parts

    def _system_messages(self, session=None, options=None, query=None, record=None):
        """组装发给模型的 system 消息：模板、记录快照、知识库、界面语言。

        入参:
            session: 可选会话，取其 ``prompt_id`` / 上下文快照。
            options (dict): 无 session 模板时可用 ``system_prompt``。
            query (str): 本轮用户问题。
            record: 可选业务记录，生成字段快照。
        返回:
            list[dict]: 通常一条 ``{'role': 'system', 'content': '...'}``。
        """
        parts = self._system_content_parts(session, options, query, record)
        parts.append(self._user_language_instruction())
        return [{'role': 'system', 'content': '\n\n'.join(parts)}]

    def _user_language_name(self):
        """当前用户 Odoo 界面语言的显示名。

        入参:
            无（读 ``self.env.lang``）。
        返回:
            str: 如 ``Chinese (Simplified) / 简体中文``；找不到则退回语言代码。
        """
        code = self.env.lang or 'en_US'
        data = self.env['res.lang']._get_data(code=code)
        return data.name or code

    def _user_language_instruction(self):
        """生成「请用用户界面语言作答」的 system 指令。

        入参:
            无。
        返回:
            str: 已填入语言名的英文指令文本。
        """
        name = self._user_language_name()
        return (
            'Always reply in %s, matching the current user\'s Odoo interface '
            'language. Use that language for the entire answer unless the user '
            'explicitly asks otherwise.'
        ) % name

    def _record_snapshot(self, record, max_fields=40):
        """把一条业务记录压成可读文本，供模型当上下文（跳过敏感/二进制/关系列表字段）。

        入参:
            record: 单条 ORM 记录。
            max_fields (int): 最多序列化多少个字段，默认 40。
        返回:
            str: 多行文本，首行是模型名/id/显示名，其后 ``- 字段: 值``。
        """
        record.ensure_one()
        lines = ['%s,%s %s' % (record._name, record.id, record.display_name)]
        count = 0
        for name, field in record._fields.items():
            if count >= max_fields:
                break
            if name in _SENSITIVE_FIELD_HINTS or field.type in (
                    'binary', 'html', 'one2many', 'many2many'):
                continue
            if not field.store:
                continue
            try:
                value = record[name]
            except Exception:  # noqa: BLE001
                continue
            if field.type == 'many2one':
                value = value.display_name if value else ''
            text = str(value or '')
            if not text:
                continue
            lines.append('- %s: %s' % (name, text[:200]))
            count += 1
        return '\n'.join(lines)

    def _complete_with_failover(self, model, history, options, candidates):
        """调当前模型；失败则去掉 tools 重试（思考模式除外），再换候选模型。

        入参:
            model: 本轮起始 ``ai.model``。
            history (list[dict]): 发给厂商的消息。
            options (dict): 厂商选项；无 tools 重试成功时返回去掉 tools 的副本。
            candidates: 可切换的 ``ai.model`` 记录集或列表。
        返回:
            tuple: ``(result, model, options, error)``。全部失败时
            ``result`` 为 ``None``，``error`` 为第一次 ``AiError``。
        """
        options = dict(options or {})
        last_error = None
        try:
            return (
                get_provider(model.provider_id).chat_completion(
                    model, history, options),
                model, options, None)
        except AiError as exc:
            last_error = exc

        # Keep tools when the user asked for thinking: dropping them
        # after a thinking-mode error makes the model look like it
        # cannot call tools.
        if options.get('tools') and not options.get('thinking_enabled'):
            retry = dict(options)
            retry.pop('tools', None)
            retry.pop('tool_choice', None)
            try:
                return (
                    get_provider(model.provider_id).chat_completion(
                        model, history, retry),
                    model, retry, last_error)
            except AiError:
                pass

        for candidate in candidates:
            if candidate.id == model.id:
                continue
            try:
                return (
                    get_provider(candidate.provider_id).chat_completion(
                        candidate, history, options),
                    candidate, options, last_error)
            except AiError:
                continue
        return None, model, options, last_error

    def _run_tool_loop(self, model, history, options=None, emit=None):
        """模型 ↔ 工具 多轮循环：调厂商、执行 tool_call、把结果追加进 history。

        会按当前用户/session 取工具清单；失败时先去掉 tools 重试，再换候选模型。

        入参:
            model: 起始 ``ai.model``。
            history (list[dict]): 已含 system + 会话历史的消息列表，会被原地追加。
            options (dict): 可含 ``session``（取出后不传给厂商）、``max_rounds``、
                以及厂商选项。``session`` 用于过滤工具。
            emit (callable): 可选，流式时接收事件 dict。
        返回:
            dict:
                ``reply`` (str): 最后一轮有正文的助手回复。
                ``usage`` (dict): 累计 token。
                ``rounds`` (list): 每轮 ``content`` / ``reasoning`` / ``cards`` / ``usage``。
                ``latency_ms`` (int): 耗时。
                ``model_id`` (int): 实际用到的模型。
                ``error`` (dict, 可选): 全部厂商调用失败时存在。
        """
        options = dict(options or {})
        session = options.pop('session', None)
        manifest = self.env['ai.tool'].allowed_tools(session=session)
        name_map = {}
        if manifest:
            name_map = self.env['ai.tool']._openai_name_map(manifest)
            options['tools'] = self.env['ai.tool']._function_schemas(manifest)
        candidates = self.env['ai.model']._get_scenario_models('chat') or [model]
        current = model
        history = [dict(msg) for msg in (history or [])]
        cumulative = {
            'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0,
        }
        rounds = []
        started = time.time()
        max_rounds, max_calls = self._tool_loop_limits(options, session)
        for _round in range(max_rounds):
            call_started = time.time()
            result, current, options, last_error = self._complete_with_failover(
                current, history, options, candidates)
            call_ms = int((time.time() - call_started) * 1000)
            if result is None:
                payload = {'model': current, 'history': history}
                self.on_ai_request_error(payload, last_error)
                return {
                    'reply': '',
                    'usage': cumulative,
                    'rounds': rounds,
                    'latency_ms': int((time.time() - started) * 1000),
                    'model_id': current.id,
                    'error': {
                        'message': str(last_error),
                        'code': 'model_call_failed',
                        'traceback': traceback.format_exc(),
                    },
                }
            content = result.get('content') or ''
            reasoning = result.get('reasoning') or ''
            usage = result.get('usage') or {}
            for key in cumulative:
                cumulative[key] = cumulative.get(key, 0) + (usage.get(key) or 0)
            tool_calls = list(result.get('tool_calls') or [])
            text_calls = extract_tool_calls(content)
            if tool_calls or text_calls:
                content = strip_tool_blocks(content)
            if not tool_calls and text_calls:
                tool_calls = text_calls
            if content and emit:
                emit({'type': 'delta', 'delta': content})
            if reasoning and emit:
                emit({'type': 'reasoning_delta', 'delta': reasoning})
            cards = []
            executed = []
            for call in tool_calls[:max_calls]:
                name = name_map.get(
                    call.get('name') or '', call.get('name') or '')
                arguments = call.get('arguments') or {}
                card, status, result_data = self._execute_loop_call(
                    name, arguments, session=session)
                cards.append(card)
                executed.append((call, card, status, result_data))
            openai_calls = []
            for index, (call, _card, status, _result_data) in enumerate(executed):
                if status != 'executed':
                    continue
                openai_calls.append({
                    'id': call.get('id') or 'call_%s' % index,
                    'type': 'function',
                    'function': {
                        'name': call.get('name') or '',
                        'arguments': json.dumps(
                            call.get('arguments') or {}, ensure_ascii=False),
                    },
                })
            if openai_calls:
                assistant = {'role': 'assistant', 'content': content or ''}
                if reasoning:
                    assistant['reasoning_content'] = reasoning
                assistant['tool_calls'] = openai_calls
                history.append(assistant)
            for index, (call, card, status, result_data) in enumerate(executed):
                name = call.get('name') or ''
                if status == 'executed':
                    if emit:
                        emit({'type': 'tool_call', 'name': name, 'card': card})
                    history.append({
                        'role': 'tool',
                        'tool_call_id': call.get('id') or 'call_%s' % index,
                        'content': json.dumps(
                            result_data, ensure_ascii=False)[:4000],
                    })
                else:
                    if emit:
                        emit({'type': 'tool_card', 'card': card})
                    history.append({
                        'role': 'user',
                        'content': _('Tool "%s" failed: %s') % (
                            name, card.get('error', {}).get('message') or ''),
                    })
            rounds.append({
                'content': content, 'reasoning': reasoning,
                'cards': cards, 'usage': usage, 'model_id': current.id,
                'latency_ms': call_ms,
            })
            if not tool_calls:
                break
        else:
            if emit:
                emit({'type': 'limit', 'message': _(
                    'The tool loop reached the maximum number of rounds.')})
        if emit:
            emit({'type': 'usage', 'usage': cumulative})
        reply = ''
        for round_info in reversed(rounds):
            if round_info.get('content'):
                reply = round_info['content']
                break
        return {
            'reply': reply,
            'usage': cumulative,
            'rounds': rounds,
            'latency_ms': int((time.time() - started) * 1000),
            'model_id': current.id,
        }

    def _execute_loop_call(self, name, arguments, session=None):
        """工具循环里真正调一次工具。

        入参:
            name (str): 工具 name。
            arguments (dict): 模型给出的参数。
            session: 当前会话；写入审计并传给工具调用。
        返回:
            tuple: ``(card, status, result_data)``
                card (dict): 前端卡片，含 ``name`` / ``status`` / ``arguments``，失败有 ``error``。
                status (str): ``executed`` 成功，``blocked`` 未知工具或调用失败。
                result_data (dict): 工具原始返回；blocked 时可能是 ``{}`` 或失败 result。
        """
        tool = self.env['ai.tool'].sudo().search(
            [('name', '=', name), ('is_active', '=', True)], limit=1)
        card = {
            'name': name,
            'label': tool._tool_label() if tool else name,
            'status': 'blocked',
            'arguments': arguments,
        }
        if not tool:
            card['error'] = {'message': _('Unknown tool "%s".') % name}
            self.env['ai.audit.log']._record_tool(
                'tool_blocked', name, params=arguments, status='blocked',
                error_code=404, message=card['error']['message'],
                session=session)
            return card, 'blocked', {}
        tool_env = self.env['ai.tool']
        if session:
            tool_env = tool_env.with_context(ai_session_id=session.id)
        result = tool_env.action_invoke_tool(name, arguments)
        if result.get('status') == 'success':
            card['status'] = 'done'
            card['summary'] = result.get('message') or _('Done')
            return card, 'executed', result
        card['error'] = {
            'message': result.get('message') or _('Tool failed'),
            'code': result.get('code'),
        }
        return card, 'blocked', result

    def _message_model_vals(self, model):
        if not model:
            return {}
        return {
            'model_id': model.id,
            'provider_id': model.provider_id.id,
            'model_code': model.code,
        }

    def _persist_error_message(self, session, model, error):
        """会话上落一条失败的助手消息（带用量字段）。"""
        message = (error or {}).get('message') or ''
        self.env['ai.chat.message'].create({
            'session_id': session.id,
            'role': 'assistant',
            'content': message,
            'status': 'error',
            'error_message': message[:500],
            **self._message_model_vals(model),
        })

    def _persist_rounds(self, session, result):
        """把工具循环每一轮写成助手消息，用量字段写在同一条上。

        入参:
            session: ``ai.chat.session``。
            result (dict): ``_run_tool_loop`` 的返回值，读 ``rounds`` / ``error``。
        返回:
            None。空轮（无正文、无卡片、无推理）会跳过；循环失败会再补一条错误消息。
        """
        fallback = self.env['ai.model'].browse(result.get('model_id') or 0).exists()
        for round_info in result.get('rounds') or []:
            content = round_info.get('content') or ''
            cards = round_info.get('cards') or []
            if not content and not cards and not round_info.get('reasoning'):
                continue
            usage = round_info.get('usage') or {}
            model = self.env['ai.model'].browse(
                round_info.get('model_id') or 0).exists() or fallback
            self.env['ai.chat.message'].create({
                'session_id': session.id,
                'role': 'assistant',
                'content': self._guard_output(content),
                'reasoning_content': round_info.get('reasoning') or '',
                'tool_cards': cards,
                'prompt_tokens': usage.get('prompt_tokens') or 0,
                'completion_tokens': usage.get('completion_tokens') or 0,
                'total_tokens': usage.get('total_tokens') or 0,
                'latency_ms': round_info.get('latency_ms') or 0,
                'status': 'success',
                **self._message_model_vals(model),
            })
        error = result.get('error') or {}
        if error:
            self._persist_error_message(session, fallback, error)
