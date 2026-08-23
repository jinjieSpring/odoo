# -*- coding: utf-8 -*-
"""Unified AI service facade used by every business module.

Example (from another Odoo module)::

    # Chat with a prompt template and the current record
    result = self.env['ai.base.service'].chat(
        prompt_key='sale.email.draft',
        record=self,
        context={'tone': 'formal'},
        model_code='gpt-4o-mini',
    )
    reply = result['reply']

    # Embeddings
    vectors = self.env['ai.base.service'].embedding(['hello world'])

    # RAG lives in the optional ai_knowledge module.

    # Agent loop (model may call registered tools)
    result = self.env['ai.base.service'].agent_run(
        'How many partners do we have?',
        max_rounds=6,
    )

Override hooks by inheriting ``ai.base.service``::

    def on_ai_request_before(self, payload):
        payload = super().on_ai_request_before(payload)
        # intercept / mutate payload
        return payload
"""

import json
import logging
import re
import time
import traceback

from odoo import _, models
from odoo.exceptions import UserError

from odoo.addons.ai_base.tools import AiError, get_provider
from odoo.addons.ai_base.models.ai_tool import extract_tool_calls, strip_tool_blocks

_logger = logging.getLogger(__name__)

_INJECTION_RE = re.compile(
    r'(ignore (all|any|previous|above) instructions|you are now|jailbreak)',
    re.IGNORECASE,
)
_SENSITIVE_FIELD_HINTS = (
    'password', 'api_key', 'api_secret', 'credit_card', 'ssn', 'id_number',
)


class AiBaseService(models.AbstractModel):
    _name = 'ai.base.service'
    _description = 'AI Base Service'

    # ------------------------------------------------------------------
    # Extension hooks
    # ------------------------------------------------------------------

    def on_ai_request_before(self, payload):
        """Called before every vendor request. Return the (possibly mutated) payload."""
        return payload

    def on_ai_request_done(self, payload, result):
        """Called after a successful vendor request."""
        return result

    def on_ai_request_error(self, payload, error):
        """Called when a vendor request fails. ``error`` is an exception or dict."""
        return error

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def chat(
        self, content=None, prompt_key=None, record=None, context=None,
        stream=False, model_code=None, session=None, options=None,
        history=None, model=None, scenario='chat', persist_user=True,
    ):
        """Synchronous chat.

        :param str content: user message (optional when ``prompt_key`` renders a user turn)
        :param str prompt_key: ``ai.prompt.template`` code
        :param record: optional ORM record used to render the prompt
        :param dict context: extra template variables
        :param bool stream: unused here; use ``stream_chat`` / SSE for streaming
        :param str model_code: ``ai.model.code``
        :param session: optional ``ai.chat.session``
        :returns: dict with ``reply``, ``usage``, ``rounds``, ``latency_ms``
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
                history = session._build_history()
                options = session._call_options(options)
            else:
                history = list(history or [])
                history.append({'role': 'user', 'content': content})
            messages = self._system_messages(
                session, options, content, record=record) + history
            result = self._run_tool_loop(model, messages, options)
            result['reply'] = self._guard_output(result.get('reply') or '')
            if session:
                self._persist_rounds(session, result)
            self._log_request(
                request_type='chat', scenario_key=scenario,
                session=session, model=model, result=result,
                input_summary=content)
            result = self.on_ai_request_done(payload, result) or result
            return result
        except Exception as exc:
            self.on_ai_request_error(payload, exc)
            raise

    def rag_chat(self, query, **kwargs):
        """RAG entry point. Implemented by ``ai_knowledge`` when installed."""
        raise UserError(_(
            'Install the AI Knowledge module to use knowledge-base chat.'))

    def retrieve(self, query, top_k=5, document_ids=None, knowledge_ids=None, model=None):
        """Return knowledge snippets. Empty unless ``ai_knowledge`` is installed."""
        return []

    def embedding(self, texts, model=None, model_code=None):
        """Return a list of embedding vectors for ``texts``.

        Alias of the first.md API name; ``embed()`` is also provided.
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

    def embed(self, texts, model=None, model_code=None):
        return self.embedding(texts, model=model, model_code=model_code)

    def agent_run(
        self, content, session=None, max_rounds=10, prompt_key=None,
        record=None, context=None, model_code=None, options=None,
    ):
        """Chat with the tool loop enabled (registered tools only)."""
        options = dict(options or {})
        options['max_rounds'] = max_rounds
        result = self.chat(
            content, prompt_key=prompt_key, record=record, context=context,
            model_code=model_code, session=session, options=options,
            scenario='agent')
        if result.get('rounds'):
            log = self.env['ai.request.log'].sudo().search([], limit=1)
            if log:
                log.request_type = 'agent'
        return result

    def stream_chat(self, content, session, options=None):
        """Run the tool loop and return plain-data events for SSE replay.

        All ORM work happens here. The HTTP generator must not touch the ORM.
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
        if not session.model_id:
            session.write({
                'model_id': model.id,
                'provider_id': model.provider_id.id,
            })
        session.write({'state': 'open'})
        self.env['ai.chat.message'].create({
            'session_id': session.id,
            'role': 'user',
            'content': content,
        })
        if session.name == _('New Session'):
            session.name = content[:30]
        options = session._call_options(options)
        history = session._build_history()
        messages = self._system_messages(session, options, content) + history
        result = self._run_tool_loop(
            model, messages, options, emit=lambda event: events.append(event))
        result['reply'] = self._guard_output(result.get('reply') or '')
        self._persist_rounds(session, result)
        self._log_request(
            request_type='chat', scenario_key='chat',
            session=session, model=model, result=result,
            input_summary=content)
        return {'result': result, 'events': events, 'error': result.get('error')}

    def invoke_tool(self, tool_name, params=None, context=None):
        return self.env['ai.tool'].action_invoke_tool(tool_name, params, context)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def render_prompt(self, code_or_template, context=None, company=None, record=None):
        if hasattr(code_or_template, 'render'):
            return code_or_template.render(context or {}, record=record)
        template = self.env['ai.prompt.template']._get_by_code(
            code_or_template, company=company)
        if not template:
            return ''
        return template.render(context or {}, record=record)

    def _resolve_model(self, model=None, scenario='chat'):
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
        return int(self.env['ir.config_parameter'].sudo().get_param(key, str(default)) or default)

    def _check_rate_limit(self):
        global_limit = self._param_int('ai_base.rate_limit_global_per_minute', 120)
        user_limit = self._param_int('ai_base.rate_limit_user_per_minute', 30)
        since = self.env['ai.request.log'].sudo()
        from datetime import timedelta
        from odoo import fields as odoo_fields
        start = odoo_fields.Datetime.now() - timedelta(seconds=60)
        if global_limit > 0:
            total = since.search_count([
                ('request_type', 'in', ('chat', 'rag', 'agent', 'embed')),
                ('create_date', '>=', start),
            ])
            if total >= global_limit:
                raise UserError(_('The global AI rate limit has been reached. Retry shortly.'))
        if user_limit > 0:
            mine = since.search_count([
                ('user_id', '=', self.env.user.id),
                ('request_type', 'in', ('chat', 'rag', 'agent', 'embed')),
                ('create_date', '>=', start),
            ])
            if mine >= user_limit:
                raise UserError(_('You have reached the per-user AI rate limit. Retry shortly.'))

    def _guard_input(self, text):
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
        hits = self._sensitive_hits(text, direction='output')
        for word in hits:
            text = re.sub(re.escape(word), '***', text, flags=re.IGNORECASE)
        return text

    def _sensitive_hits(self, text, direction='input'):
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

    def _log(self, **vals):
        vals.setdefault('user_id', self.env.user.id)
        vals.setdefault('company_id', self.env.company.id)
        return self.env['ai.request.log'].sudo().create(vals)

    def _log_request(self, request_type, scenario_key, session, model, result, input_summary=''):
        error = result.get('error') or {}
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
            tool_calls=json.dumps([
                card for round_info in (result.get('rounds') or [])
                for card in (round_info.get('cards') or [])
            ], ensure_ascii=False)[:4000],
        )

    def _knowledge_system_parts(self, session, query):
        """Override in ``ai_knowledge`` to inject retrieved snippets."""
        return []

    def _system_messages(self, session=None, options=None, query=None, record=None):
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
        if not parts:
            return []
        return [{'role': 'system', 'content': '\n\n'.join(parts)}]

    def _record_snapshot(self, record, max_fields=40):
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

    def _run_tool_loop(self, model, history, options=None, emit=None):
        options = dict(options or {})
        manifest = self.env['ai.tool'].action_get_manifest_for_user()
        if manifest:
            options['tools'] = self.env['ai.tool']._function_schemas(manifest)
        candidates = self.env['ai.model']._get_scenario_models('chat') or [model]
        current = model
        history = [dict(msg) for msg in (history or [])]
        cumulative = {
            'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0,
        }
        rounds = []
        started = time.time()
        max_rounds = int(options.get('max_rounds') or self._param_int(
            'ai_base.max_tool_rounds', 10))
        max_calls = self._param_int('ai_base.max_tool_calls_per_round', 10)
        last_error = None
        for _round in range(max_rounds):
            client = get_provider(current.provider_id)
            try:
                result = client.chat_completion(current, history, options)
            except AiError as exc:
                last_error = exc
                result = None
                if options.get('tools'):
                    retry = dict(options)
                    retry.pop('tools', None)
                    retry.pop('tool_choice', None)
                    try:
                        result = client.chat_completion(current, history, retry)
                        options = retry
                    except AiError:
                        result = None
                if result is None:
                    for candidate in candidates:
                        if candidate.id == current.id:
                            continue
                        try:
                            result = get_provider(candidate.provider_id).chat_completion(
                                candidate, history, options)
                            current = candidate
                            break
                        except AiError:
                            continue
                if result is None:
                    payload = {'model': current, 'history': history}
                    self.on_ai_request_error(payload, last_error)
                    return {
                        'reply': '',
                        'usage': cumulative,
                        'rounds': rounds,
                        'latency_ms': int((time.time() - started) * 1000),
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
            for call in tool_calls[:max_calls]:
                name = call.get('name') or ''
                arguments = call.get('arguments') or {}
                card, status, result_data = self._execute_loop_call(name, arguments)
                cards.append(card)
                if status == 'executed':
                    if emit:
                        emit({'type': 'tool_call', 'name': name, 'card': card})
                    history.append({
                        'role': 'assistant',
                        'content': content,
                    })
                    history.append({
                        'role': 'tool',
                        'content': json.dumps(result_data, ensure_ascii=False)[:4000],
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

    def _execute_loop_call(self, name, arguments):
        tool = self.env['ai.tool'].sudo().search(
            [('name', '=', name), ('is_active', '=', True)], limit=1)
        card = {'name': name, 'status': 'blocked', 'arguments': arguments}
        if not tool:
            card['error'] = {'message': _('Unknown tool "%s".') % name}
            return card, 'blocked', {}
        result = self.env['ai.tool'].action_invoke_tool(name, arguments)
        if result.get('status') == 'success':
            card['status'] = 'done'
            card['summary'] = result.get('message') or _('Done')
            return card, 'executed', result
        card['error'] = {
            'message': result.get('message') or _('Tool failed'),
            'code': result.get('code'),
        }
        return card, 'blocked', result

    def _persist_rounds(self, session, result):
        for round_info in result.get('rounds') or []:
            content = round_info.get('content') or ''
            cards = round_info.get('cards') or []
            if not content and not cards and not round_info.get('reasoning'):
                continue
            usage = round_info.get('usage') or {}
            self.env['ai.chat.message'].create({
                'session_id': session.id,
                'role': 'assistant',
                'content': self._guard_output(content),
                'reasoning_content': round_info.get('reasoning') or '',
                'tool_cards': cards,
                'prompt_tokens': usage.get('prompt_tokens') or 0,
                'completion_tokens': usage.get('completion_tokens') or 0,
                'total_tokens': usage.get('total_tokens') or 0,
            })
