# -*- coding: utf-8 -*-
"""LLM service for Linkin AI.

Wraps the OpenAI-compatible chat completions protocol, the Ollama native
protocol and the DeepSeek Responses API (used for native web search). The
service only works on plain data: callers may pass either ORM records or
``SimpleNamespace`` snapshots (used by streaming generators that outlive the
request cursor). All network calls are synchronous with a generous timeout;
streaming variants yield dict chunks and never raise ``LLMError``.
"""

import json
import logging
import time
from types import SimpleNamespace

import requests

from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when a provider call cannot be completed."""


class LLMService:
    """Stateless provider adapter (no Odoo dependency)."""

    # Recommended defaults used when the provider does not expose metadata
    # (final fallback when no provider profile matches; mirrors the
    # hdai.model field defaults).
    DEFAULT_CONTEXT_LENGTH = 128000
    DEFAULT_MAX_OUTPUT_TOKENS = 8192

    # Provider profiles: recommended defaults per provider (context window,
    # max output tokens and sampling parameters) plus the sampling
    # parameters the provider actually accepts. ``sampling`` flags prevent
    # sending parameters some providers fix or reject (e.g. Kimi fixes
    # temperature/top_p; OpenAI-compatible endpoints reject top_k).
    # Profiles are matched on provider_type and base_url keywords so
    # ``openai_compatible`` endpoints (DashScope / BigModel / Moonshot /
    # DeepSeek / OpenAI) get provider-specific values.
    _PROVIDER_DEFAULTS = {
        'deepseek': {
            'context_length': 128000,
            'max_output_tokens': 8192,
            'temperature': 1.0,
            'top_p': 1.0,
            'top_k': 0,
            'sampling': {'temperature': True, 'top_p': True, 'top_k': False},
        },
        'openai': {
            'context_length': 128000,
            'max_output_tokens': 16384,
            'temperature': 1.0,
            'top_p': 1.0,
            'top_k': 0,
            'sampling': {'temperature': True, 'top_p': True, 'top_k': False},
        },
        'zhipu': {
            'context_length': 200000,
            'max_output_tokens': 128000,
            'temperature': 1.0,
            'top_p': 0.95,
            'top_k': 0,
            'sampling': {'temperature': True, 'top_p': True, 'top_k': False},
        },
        'moonshot': {
            'context_length': 256000,
            'max_output_tokens': 16384,
            'temperature': 1.0,
            'top_p': 0.95,
            'top_k': 0,
            'sampling': {'temperature': False, 'top_p': False, 'top_k': False},
        },
        'dashscope': {
            'context_length': 131072,
            'max_output_tokens': 8192,
            'temperature': 0.7,
            'top_p': 0.8,
            'top_k': 0,
            'sampling': {'temperature': True, 'top_p': True, 'top_k': False},
        },
        'ollama': {
            'context_length': 32768,
            'max_output_tokens': 8192,
            'temperature': 0.8,
            'top_p': 0.9,
            'top_k': 40,
            'sampling': {'temperature': True, 'top_p': True, 'top_k': True},
        },
        'llamacpp': {
            'context_length': 32768,
            'max_output_tokens': 8192,
            'temperature': 0.8,
            'top_p': 0.95,
            'top_k': 40,
            'sampling': {'temperature': True, 'top_p': True, 'top_k': True},
        },
        'vllm': {
            'context_length': 32768,
            'max_output_tokens': 8192,
            'temperature': 1.0,
            'top_p': 1.0,
            'top_k': 0,
            'sampling': {'temperature': True, 'top_p': True, 'top_k': True},
        },
        'generic': {
            'context_length': 128000,
            'max_output_tokens': 8192,
            'temperature': 0.7,
            'top_p': 1.0,
            'top_k': 0,
            'sampling': {'temperature': True, 'top_p': True, 'top_k': False},
        },
    }
    # Model-code overrides for cloud models whose official specs differ from
    # the provider profile (checked in order). Values come from the official
    # provider documentation (context window / max output tokens).
    _MODEL_PREFIX_DEFAULTS = [
        ('deepseek-v4-', 1000000, 32768),
        ('deepseek-chat', 128000, 8192),
        ('deepseek-reasoner', 128000, 8192),
        ('deepseek-r1', 65536, 8192),
        ('gpt-5', 400000, 128000),
        ('gpt-4.1', 1047576, 32768),
        ('glm-5.2', 1000000, 128000),
        ('glm-5', 200000, 128000),
        ('kimi-k2', 256000, 16384),
        ('moonshot-v1', 128000, 8192),
        ('qwen3-max', 262144, 65536),
        ('qwen-max', 32768, 8192),
    ]

    _LANGUAGE_NAMES = {
        'ar': 'Arabic',
        'bg_BG': 'Bulgarian',
        'ca_ES': 'Catalan',
        'cs_CZ': 'Czech',
        'da_DK': 'Danish',
        'de_DE': 'German',
        'el_GR': 'Greek',
        'en_US': 'English',
        'es_ES': 'Spanish',
        'et_EE': 'Estonian',
        'fi_FI': 'Finnish',
        'fr_FR': 'French',
        'he_IL': 'Hebrew',
        'hi_IN': 'Hindi',
        'hr_HR': 'Croatian',
        'hu_HU': 'Hungarian',
        'id_ID': 'Indonesian',
        'it_IT': 'Italian',
        'ja_JP': 'Japanese',
        'ko_KR': 'Korean',
        'lt_LT': 'Lithuanian',
        'lv_LV': 'Latvian',
        'ms_MY': 'Malay',
        'nb_NO': 'Norwegian',
        'nl_NL': 'Dutch',
        'pl_PL': 'Polish',
        'pt_BR': 'Portuguese (Brazil)',
        'pt_PT': 'Portuguese',
        'ro_RO': 'Romanian',
        'ru_RU': 'Russian',
        'sk_SK': 'Slovak',
        'sl_SI': 'Slovenian',
        'sr_RS': 'Serbian',
        'sv_SE': 'Swedish',
        'th_TH': 'Thai',
        'tr_TR': 'Turkish',
        'uk_UA': 'Ukrainian',
        'vi_VN': 'Vietnamese',
        'zh_CN': 'Chinese',
        'zh_TW': 'Traditional Chinese',
    }
    # Extra native-language reinforcement (ASCII escapes only).
    _LANGUAGE_HINTS = {
        'Chinese': '\u8bf7\u7528\u4e2d\u6587\u601d\u8003\u5e76\u56de\u7b54\u3002',
    }
    _REASONING_PROMPT_TMPL = (
        'You are a helpful assistant. Think through the problem step by step. '
        'Write your thinking process and your final answer in {language}'
        '{same_as}. You must use {language} for the whole thinking process '
        'and for the final answer; do not use any other language. {hint}'
    )
    _DIRECT_PROMPT_TMPL = (
        'You are a helpful assistant. Answer directly and concisely in '
        '{language}{same_as}, without revealing a step-by-step reasoning '
        'process. Keep any internal reasoning in {language} as well. {hint}'
    )
    _LANGUAGE_REINFORCE_TMPL = (
        'Reply and reason in {language}. Do not use any other language.'
    )
    _LANGUAGE_USER_ANCHOR_TMPL = (
        '\n\n(Important instruction: answer in {language}{same_as}. Do not '
        'think or write in any other language.)'
    )
    _WEB_SEARCH_MODEL_PREFIXES = (
        'qwen-plus', 'qwen-max', 'qwen-turbo', 'qwen3',
        'glm-4', 'glm-5',
        'kimi-', 'moonshot-v1',
        'deepseek-v4-flash', 'deepseek-v3.2',
        'gpt-4o', 'gpt-4.1', 'gpt-5',
        'claude-', 'gemini-',
    )
    _REASONING_MODEL_PREFIXES = (
        'deepseek-reasoner', 'deepseek-r1', 'deepseek-v4',
        'gpt-5', 'o1', 'o3', 'o4',
        'qwen3', 'glm-5', 'kimi-k2', 'claude-',
    )

    # ------------------------------------------------------------------
    # Capability helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _model_supports_web_search(code):
        code_lower = (code or '').lower()
        return any(code_lower.startswith(prefix)
                   for prefix in LLMService._WEB_SEARCH_MODEL_PREFIXES)

    @staticmethod
    def _model_supports_reasoning(code):
        code_lower = (code or '').lower()
        return any(code_lower.startswith(prefix)
                   for prefix in LLMService._REASONING_MODEL_PREFIXES)

    @staticmethod
    def _as_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _provider_profile(provider):
        """Pick the provider profile for an ORM record or a snapshot.

        Base URL keywords win over the provider type so custom
        ``openai_compatible`` endpoints (DashScope / BigModel / Moonshot /
        DeepSeek) resolve to their own profile instead of the generic
        OpenAI one.
        """
        provider_type = getattr(provider, 'provider_type', '') or ''
        base = (getattr(provider, 'base_url', '') or '').lower()
        if provider_type == 'deepseek' or 'deepseek' in base:
            return 'deepseek'
        if 'bigmodel' in base or 'zhipu' in base:
            return 'zhipu'
        if 'moonshot' in base or 'kimi' in base:
            return 'moonshot'
        if 'dashscope' in base or 'aliyun' in base:
            return 'dashscope'
        if provider_type == 'ollama' or 'ollama' in base:
            return 'ollama'
        if provider_type == 'llamacpp' or 'llamacpp' in base:
            return 'llamacpp'
        if provider_type == 'vllm' or 'vllm' in base:
            return 'vllm'
        if 'openai' in base or provider_type == 'openai':
            return 'openai'
        return 'generic'

    @staticmethod
    def _defaults_for_model(provider, code=None):
        """Recommended model defaults: the provider profile overridden by
        the model-code specs when the code matches a documented cloud model
        (e.g. deepseek-v4-* 1M context, gpt-5 400K/128K output)."""
        profile = LLMService._PROVIDER_DEFAULTS.get(
            LLMService._provider_profile(provider),
            LLMService._PROVIDER_DEFAULTS['generic'])
        defaults = dict(profile)
        code_lower = (code or '').lower()
        for prefix, context_length, max_output_tokens in \
                LLMService._MODEL_PREFIX_DEFAULTS:
            if code_lower.startswith(prefix):
                defaults['context_length'] = context_length
                defaults['max_output_tokens'] = max_output_tokens
                break
        return defaults

    @staticmethod
    def _sampling_params(model, options=None):
        """Sampling parameters for the request payload.

        Values come from the model configuration (administrator settings),
        unless overridden per request. Only parameters the provider profile
        accepts are sent: providers that fix or reject a parameter (e.g.
        Kimi temperature/top_p, OpenAI-compatible top_k) never receive it.
        Works with ORM records and snapshots alike.
        """
        options = options or {}
        allowed = LLMService._PROVIDER_DEFAULTS.get(
            LLMService._provider_profile(model.provider_id), {}).get(
                'sampling', {})
        params = {}
        for name in ('temperature', 'top_p', 'top_k'):
            value = options.get(name)
            if value is None:
                value = getattr(model, name, None)
            if value is None:
                continue
            if name == 'top_k' and not value:
                continue
            if not allowed.get(name):
                continue
            params[name] = value
        return params

    # ------------------------------------------------------------------
    # Provider addressing / payload adaptation
    # ------------------------------------------------------------------

    @staticmethod
    def _deepseek_responses_url(base_url):
        base = (base_url or '').rstrip('/')
        if base.endswith('/v1'):
            base = base[:-3]
        return base.rstrip('/') + '/responses'

    @staticmethod
    def _uses_responses_api(model, options):
        return bool(
            options.get('web_search') and model.supports_web_search
            and 'deepseek' in (model.provider_id.base_url or '').lower()
        )

    @staticmethod
    def _web_search_payload(model, options):
        """Provider-specific web search payload for chat completions."""
        if not options.get('web_search') or not model.supports_web_search:
            return {}
        base = (model.provider_id.base_url or '').lower()
        code = (model.code or '').lower()
        if 'dashscope' in base:
            return {'enable_search': True}
        if 'bigmodel' in base or 'zhipu' in base:
            return {'tools': [{'type': 'web_search', 'web_search': {'enable': True}}]}
        if 'moonshot' in base or code.startswith('kimi') or code.startswith('moonshot'):
            return {'tools': [{'type': 'builtin_function',
                               'function': {'name': '$web_search'}}]}
        if ('openai' in base or 'azure' in base
                or code.startswith('gpt-4o') or code.startswith('gpt-4.1')
                or code.startswith('gpt-5') or code.startswith('gemini')):
            return {'web_search_options': {}}
        return {'tools': [{'type': 'web_search'}]}

    @staticmethod
    def _uses_reasoning(model, options=None):
        strength = (options or {}).get('reasoning_strength')
        return bool(strength) and strength != 'none'

    @staticmethod
    def _api_key(provider):
        """API key accessor working for ORM records and snapshots alike."""
        sudo = getattr(provider, 'sudo', None)
        if sudo is not None:
            return sudo().api_key
        return provider.api_key

    @staticmethod
    def _base_url(provider):
        """Normalized base URL (scheme ensured) for ORM records and
        snapshots alike; mirrors hdai.provider._normalize_base_url."""
        url = (getattr(provider, 'base_url', '') or '').strip()
        if url and '://' not in url:
            return 'http://' + url
        return url

    @staticmethod
    def _is_local(provider):
        """Local providers never require an API key: native Ollama/llama.cpp
        types plus OpenAI-compatible endpoints bound to localhost (vLLM,
        LiteLLM, local gateways)."""
        if provider.provider_type in ('ollama', 'llamacpp'):
            return True
        base = (provider.base_url or '').lower()
        return ('localhost' in base or '127.0.0.1' in base
                or '0.0.0.0' in base)

    # ------------------------------------------------------------------
    # Prompt assembly
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_language(messages):
        text = ''
        for msg in reversed(messages or []):
            if msg.get('role') == 'user':
                text = msg.get('content') or ''
                break
        for char in text:
            code = ord(char)
            if 0x4E00 <= code <= 0x9FFF:
                return 'Chinese'
            if 0x3040 <= code <= 0x30FF:
                return 'Japanese'
            if 0xAC00 <= code <= 0xD7AF:
                return 'Korean'
        return 'English'

    @staticmethod
    def _language_name(lang):
        return LLMService._LANGUAGE_NAMES.get(lang or '') or 'English'

    @staticmethod
    def _resolve_language(messages, options=None):
        options = options or {}
        mode = options.get('language_mode') or 'auto'
        if mode == 'auto' or (mode == 'specific' and not options.get('lang')):
            return LLMService._detect_language(messages)
        return LLMService._language_name(options.get('lang'))

    @staticmethod
    def _with_system_instruction(messages, model, options=None):
        """Prepend the language/thinking instruction to the message list.

        ``options['system_prompt']`` (agent or prompt content) is kept as the
        leading system message when provided; the generated instruction is
        appended to it so both apply. ``options['context_text']`` is injected
        between them when present.
        """
        options = options or {}
        messages = list(messages or [])
        language = LLMService._resolve_language(messages, options)
        hint = LLMService._LANGUAGE_HINTS.get(language, '')
        mode = options.get('language_mode') or 'auto'
        same_as = (", the same language as the user's latest message"
                   if mode == 'auto' else '')
        reasoning = LLMService._uses_reasoning(model, options)
        language_instruction = options.get('language_instruction')
        if language_instruction:
            instruction = language_instruction.format(
                language=language,
                same_as=same_as,
                hint=hint,
                reasoning=(
                    'step by step, showing your thinking,'
                    if reasoning else 'directly and concisely,'),
            ).strip()
        elif reasoning:
            instruction = LLMService._REASONING_PROMPT_TMPL.format(
                language=language, same_as=same_as, hint=hint).strip()
        else:
            instruction = LLMService._DIRECT_PROMPT_TMPL.format(
                language=language, same_as=same_as, hint=hint).strip()
        system_prompt = options.get('system_prompt') or ''
        context_text = options.get('context_text') or ''
        parts = [part for part in (system_prompt, context_text, instruction) if part]
        if not parts:
            return messages
        leading = {'role': 'system', 'content': '\n\n'.join(parts)}
        if messages and messages[0].get('role') == 'system':
            # Merge into an existing leading system message (session prompt).
            first = dict(messages[0])
            first['content'] = '%s\n\n%s' % (first['content'], '\n\n'.join(
                [part for part in (context_text, instruction) if part]))
            result = [first] + messages[1:]
        else:
            result = [leading] + messages
        if result and result[-1].get('role') == 'user':
            result.insert(-1, {
                'role': 'system',
                'content': LLMService._LANGUAGE_REINFORCE_TMPL.format(
                    language=language),
            })
            last = dict(result[-1])
            last['content'] = (last['content'] or '') + \
                LLMService._LANGUAGE_USER_ANCHOR_TMPL.format(
                    language=language, same_as=same_as)
            result[-1] = last
        return result

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _request_error_message(url, exc):
        """Turn a raw requests error into an actionable message.

        The two most common configuration mistakes get explicit hints:
        a missing scheme (requests: "No connection adapters were found")
        and a service that is not reachable (connection refused / timeout).
        """
        text = str(exc)
        if 'No connection adapters were found' in text:
            return _(
                'The Base URL is missing a scheme: "%s". Add http:// or '
                'https://, e.g. http://127.0.0.1:8080/v1 for llama.cpp or '
                'vLLM.') % url
        if isinstance(exc, requests.ConnectionError):
            return _(
                'Could not connect to "%s". Check that the service is '
                'running, the address and port are correct, and the '
                'firewall allows the connection.') % url
        if isinstance(exc, requests.Timeout):
            return _(
                'The request to "%s" timed out. Check the service status '
                'and network connectivity.') % url
        return _('Request failed: %s') % text

    @staticmethod
    def _http_error_message(url, status, body):
        message = _('The API returned HTTP error %s: %s') % (
            status, body[:500])
        if status == 404 and url.rstrip('/').endswith('/models'):
            message = '%s %s' % (message, _(
                'The model list endpoint was not found. For llama.cpp / '
                'vLLM, set the Base URL to http://<host>:<port>/v1 so the '
                'OpenAI-compatible /v1/models endpoint is used.'))
        return message

    @staticmethod
    def _request(method, url, **kwargs):
        try:
            resp = requests.request(method, url, timeout=120, **kwargs)
        except requests.RequestException as exc:
            raise LLMError(
                LLMService._request_error_message(url, exc)) from exc
        if resp.status_code >= 400:
            raise LLMError(LLMService._http_error_message(
                url, resp.status_code, resp.text))
        # Decode JSON responses as UTF-8: providers such as llama.cpp omit
        # the charset in Content-Type and requests would otherwise fall back
        # to ISO-8859-1 and garble non-ASCII replies (error_reference 8.22).
        resp.encoding = 'utf-8'
        try:
            return resp.json()
        except ValueError as exc:
            raise LLMError(_('The API returned non-JSON data: %s') % (
                resp.text[:500])) from exc

    @staticmethod
    def _request_stream(method, url, **kwargs):
        try:
            resp = requests.request(method, url, stream=True, timeout=120, **kwargs)
        except requests.RequestException as exc:
            raise LLMError(
                LLMService._request_error_message(url, exc)) from exc
        if resp.status_code >= 400:
            raise LLMError(LLMService._http_error_message(
                url, resp.status_code, resp.text))
        # Same UTF-8 policy as _request: streamed lines are decoded
        # explicitly below, never through requests' charset inference.
        resp.encoding = 'utf-8'
        return resp

    @staticmethod
    def _headers(provider):
        api_key = LLMService._api_key(provider)
        return {'Authorization': 'Bearer %s' % api_key} if api_key else {}

    @staticmethod
    def _base_payload(model, messages, options, stream):
        payload = {
            'model': model.code,
            'messages': messages,
            'stream': stream,
        }
        max_tokens = options.get('max_tokens') or model.max_output_tokens
        if max_tokens:
            payload['max_tokens'] = max_tokens
        if model.supports_reasoning:
            strength = options.get('reasoning_strength')
            if strength and strength != 'none':
                payload['reasoning_effort'] = strength
        payload.update(LLMService._sampling_params(model, options))
        tools = options.get('tools')
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = options.get('tool_choice', 'auto')
        payload.update(LLMService._web_search_payload(model, options))
        return payload

    # ------------------------------------------------------------------
    # Model listing
    # ------------------------------------------------------------------

    @staticmethod
    def _ollama_context_length(provider, code):
        try:
            data = LLMService._request(
                'POST', LLMService._base_url(provider) + '/api/show',
                json={'model': code, 'verbose': False},
            )
        except LLMError:
            return None
        model_info = data.get('model_info') or {}
        return LLMService._as_int(model_info.get('llama.context_length'))

    @staticmethod
    def _llamacpp_props_context_length(provider):
        """Best-effort context window from the llama.cpp /props endpoint.

        llama-server exposes ``default_generation_settings.n_ctx``; the
        endpoint lives on the server root (the Base URL may point at the
        OpenAI-compatible /v1 prefix), so both locations are tried. Returns
        ``None`` when the endpoint is unavailable or has no value."""
        base = (LLMService._base_url(provider) or '').rstrip('/')
        root = base[:-3] if base.endswith('/v1') else base
        for url in (root + '/props', base + '/props'):
            try:
                data = LLMService._request('GET', url)
            except LLMError:
                continue
            settings = data.get('default_generation_settings') or {}
            value = LLMService._as_int(settings.get('n_ctx'))
            if value:
                return value
        return None

    @staticmethod
    def list_models(provider):
        """List the models of a provider (dicts with ``code``/``name`` and
        best-effort parameters); used by the provider test connection."""
        base_url = LLMService._base_url(provider)
        if provider.provider_type == 'ollama':
            data = LLMService._request('GET', base_url + '/api/tags')
            models = []
            for entry in data.get('models') or []:
                code = entry.get('name') or entry.get('model')
                if not code:
                    continue
                context_length = (
                    LLMService._as_int(entry.get('context_length'))
                    or LLMService._as_int(
                        (entry.get('details') or {}).get('context_length'))
                )
                if not context_length:
                    context_length = LLMService._ollama_context_length(
                        provider, code)
                models.append({
                    'code': code,
                    'name': code,
                    'context_length': context_length,
                    'max_output_tokens': LLMService._as_int(
                        entry.get('max_tokens')),
                    'supports_web_search': False,
                    'supports_reasoning': (
                        LLMService._model_supports_reasoning(code)),
                    'supports_streaming': True,
                })
            return models
        data = LLMService._request(
            'GET', base_url + '/models', headers=LLMService._headers(provider))
        models = []
        for entry in data.get('data') or []:
            code = entry.get('id')
            if not code:
                continue
            meta = entry.get('meta') if isinstance(entry.get('meta'), dict) else {}
            context_length = (
                LLMService._as_int(entry.get('context_length'))
                or LLMService._as_int(meta.get('context_length')))
            if not context_length and provider.provider_type == 'llamacpp':
                context_length = LLMService._llamacpp_props_context_length(
                    provider)
            models.append({
                'code': code,
                'name': code,
                'context_length': context_length,
                'max_output_tokens': (
                    LLMService._as_int(entry.get('max_tokens'))
                    or LLMService._as_int(meta.get('max_tokens'))),
                'supports_web_search': (
                    LLMService._model_supports_web_search(code)),
                'supports_reasoning': (
                    LLMService._model_supports_reasoning(code)),
                'supports_streaming': True,
            })
        return models

    # ------------------------------------------------------------------
    # Synchronous calls
    # ------------------------------------------------------------------

    @staticmethod
    def _chat_openai_compatible(model, messages, options=None):
        options = options or {}
        provider = model.provider_id
        if not LLMService._api_key(provider) and not LLMService._is_local(provider):
            raise LLMError(_('No API key is configured. Fill it in under '
                             '"Model Providers".'))
        url = LLMService._base_url(provider) + '/chat/completions'
        payload = LLMService._base_payload(model, messages, options, False)
        return LLMService._request(
            'POST', url, headers=LLMService._headers(provider), json=payload)

    @staticmethod
    def _parse_openai_tool_calls(message):
        """Normalize OpenAI-style ``message.tool_calls`` into plain dicts."""
        tool_calls = []
        for call in message.get('tool_calls') or []:
            function = call.get('function') or {}
            name = function.get('name') or ''
            if not name:
                continue
            arguments = function.get('arguments')
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except ValueError:
                    arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            tool_calls.append({
                'id': call.get('id'),
                'name': name,
                'arguments': arguments,
            })
        return tool_calls

    @staticmethod
    def _chat_ollama(model, messages, options=None):
        options = options or {}
        provider = model.provider_id
        url = LLMService._base_url(provider) + '/api/chat'
        payload = {'model': model.code, 'messages': messages, 'stream': False}
        max_tokens = options.get('max_tokens') or model.max_output_tokens
        sampling = LLMService._sampling_params(model, options)
        if max_tokens:
            sampling['num_predict'] = max_tokens
        if sampling:
            payload['options'] = sampling
        return LLMService._request('POST', url, json=payload)

    @staticmethod
    def _chat_responses_api(model, messages, options=None):
        options = options or {}
        provider = model.provider_id
        if not LLMService._api_key(provider):
            raise LLMError(_('No API key is configured. Fill it in under '
                             '"Model Providers".'))
        url = LLMService._deepseek_responses_url(
            LLMService._base_url(provider))
        payload = {
            'model': model.code,
            'input': messages,
            'tools': [{'type': 'web_search'}],
            'stream': False,
        }
        max_tokens = options.get('max_tokens') or model.max_output_tokens
        if max_tokens:
            payload['max_output_tokens'] = max_tokens
        payload.update(LLMService._sampling_params(model, options))
        data = LLMService._request(
            'POST', url, headers=LLMService._headers(provider), json=payload)
        content_parts = []
        reasoning_parts = []
        tool_calls = []
        for item in data.get('output') or []:
            if item.get('type') == 'reasoning':
                for part in item.get('content') or []:
                    if part.get('text'):
                        reasoning_parts.append(part['text'])
            elif item.get('type') == 'message':
                for part in item.get('content') or []:
                    if part.get('type') == 'output_text' and part.get('text'):
                        content_parts.append(part['text'])
            elif item.get('type') == 'function_call':
                arguments = item.get('arguments')
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except ValueError:
                        arguments = {}
                if not isinstance(arguments, dict):
                    arguments = {}
                tool_calls.append({
                    'id': item.get('call_id') or item.get('id'),
                    'name': item.get('name') or '',
                    'arguments': arguments,
                })
        usage = data.get('usage') or {}
        return {
            'content': ''.join(content_parts),
            'reasoning': ''.join(reasoning_parts),
            'tool_calls': tool_calls,
            'usage': {
                'prompt_tokens': usage.get('input_tokens') or 0,
                'completion_tokens': usage.get('output_tokens') or 0,
                'total_tokens': usage.get('total_tokens') or 0,
            },
        }

    @staticmethod
    def chat_tools(model, messages, options=None):
        """Call the model synchronously with optional tool definitions.

        Returns a dict with ``content``, ``reasoning``, ``usage`` and
        ``tool_calls`` (a list of ``{'id', 'name', 'arguments'}`` dicts,
        empty when the model answered without requesting tools). ``chat()``
        delegates here and discards the tool calls for callers that only
        need plain text.
        """
        options = options or {}
        provider = model.provider_id
        messages = LLMService._with_system_instruction(messages, model, options)
        started = time.time()
        if provider.provider_type == 'ollama':
            data = LLMService._chat_ollama(model, messages, options)
            message = data.get('message') or {}
            content = message.get('content') or ''
            reasoning = message.get('reasoning_content') or ''
            tool_calls = []
            for call in message.get('tool_calls') or []:
                function = call.get('function') or {}
                name = function.get('name') or ''
                if not name:
                    continue
                arguments = function.get('arguments')
                if not isinstance(arguments, dict):
                    arguments = {}
                tool_calls.append({
                    'id': call.get('id'),
                    'name': name,
                    'arguments': arguments,
                })
            usage = {
                'prompt_tokens': data.get('prompt_eval_count') or 0,
                'completion_tokens': data.get('eval_count') or 0,
            }
        elif LLMService._uses_responses_api(model, options):
            result = LLMService._chat_responses_api(model, messages, options)
            content = result['content']
            reasoning = result['reasoning']
            tool_calls = result['tool_calls']
            usage = result['usage']
        else:
            data = LLMService._chat_openai_compatible(model, messages, options)
            choice = (data.get('choices') or [{}])[0]
            message = choice.get('message') or {}
            content = message.get('content') or ''
            reasoning = message.get('reasoning_content') or ''
            tool_calls = LLMService._parse_openai_tool_calls(message)
            usage = data.get('usage') or {}
        usage['total_tokens'] = (
            usage.get('prompt_tokens', 0) + usage.get('completion_tokens', 0))
        _logger.info(
            'hdai chat: model=%s latency=%.2fs tokens=%s tools=%s',
            model.code, time.time() - started, usage, len(tool_calls))
        return {
            'content': content,
            'reasoning': reasoning,
            'usage': usage,
            'tool_calls': tool_calls,
        }

    @staticmethod
    def chat(model, messages, options=None):
        """Call the model synchronously; return ``(content, reasoning, usage)``."""
        result = LLMService.chat_tools(model, messages, options)
        return result['content'], result['reasoning'], result['usage']

    # ------------------------------------------------------------------
    # Streaming
    # ------------------------------------------------------------------

    @staticmethod
    def _stream_openai_compatible(model, messages, options=None):
        options = options or {}
        provider = model.provider_id
        if not LLMService._api_key(provider) and not LLMService._is_local(provider):
            raise LLMError(_('No API key is configured. Fill it in under '
                             '"Model Providers".'))
        url = LLMService._base_url(provider) + '/chat/completions'
        payload = LLMService._base_payload(model, messages, options, True)
        payload['stream_options'] = {'include_usage': True}
        resp = LLMService._request_stream(
            'POST', url, headers=LLMService._headers(provider), json=payload)
        for raw_line in resp.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            line = raw_line.decode('utf-8', errors='replace')
            if not line or not line.startswith('data:'):
                continue
            data_text = line[5:].strip()
            if not data_text or data_text == '[DONE]':
                continue
            try:
                data = json.loads(data_text)
            except ValueError:
                continue
            choice = (data.get('choices') or [{}])[0]
            delta = choice.get('delta') or {}
            if delta.get('content'):
                yield {'content': delta['content']}
            if delta.get('reasoning_content'):
                yield {'reasoning': delta['reasoning_content']}
            if delta.get('tool_calls'):
                yield {'tool_call_deltas': delta['tool_calls']}
            usage = data.get('usage')
            if usage:
                yield {'usage': {
                    'prompt_tokens': usage.get('prompt_tokens') or 0,
                    'completion_tokens': usage.get('completion_tokens') or 0,
                    'total_tokens': usage.get('total_tokens') or 0,
                }}

    @staticmethod
    def _stream_ollama(model, messages, options=None):
        options = options or {}
        provider = model.provider_id
        url = LLMService._base_url(provider) + '/api/chat'
        payload = {'model': model.code, 'messages': messages, 'stream': True}
        max_tokens = options.get('max_tokens') or model.max_output_tokens
        sampling = LLMService._sampling_params(model, options)
        if max_tokens:
            sampling['num_predict'] = max_tokens
        if sampling:
            payload['options'] = sampling
        resp = LLMService._request_stream('POST', url, json=payload)
        for raw_line in resp.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            line = raw_line.decode('utf-8', errors='replace')
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            message = data.get('message') or {}
            if message.get('content'):
                yield {'content': message['content']}
            if message.get('reasoning_content'):
                yield {'reasoning': message['reasoning_content']}
            if data.get('done'):
                prompt_tokens = data.get('prompt_eval_count') or 0
                completion_tokens = data.get('eval_count') or 0
                yield {'usage': {
                    'prompt_tokens': prompt_tokens,
                    'completion_tokens': completion_tokens,
                    'total_tokens': prompt_tokens + completion_tokens,
                }}
                break

    @staticmethod
    def _stream_responses_api(model, messages, options=None):
        options = options or {}
        provider = model.provider_id
        if not LLMService._api_key(provider):
            raise LLMError(_('No API key is configured. Fill it in under '
                             '"Model Providers".'))
        url = LLMService._deepseek_responses_url(provider.base_url)
        payload = {
            'model': model.code,
            'input': messages,
            'tools': [{'type': 'web_search'}],
            'stream': True,
        }
        max_tokens = options.get('max_tokens') or model.max_output_tokens
        if max_tokens:
            payload['max_output_tokens'] = max_tokens
        payload.update(LLMService._sampling_params(model, options))
        resp = LLMService._request_stream(
            'POST', url, headers=LLMService._headers(provider), json=payload)
        for raw_line in resp.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            line = raw_line.decode('utf-8', errors='replace')
            if not line or not line.startswith('data:'):
                continue
            data_text = line[5:].strip()
            if not data_text:
                continue
            try:
                data = json.loads(data_text)
            except ValueError:
                continue
            event_type = data.get('type') or ''
            if event_type == 'response.reasoning_text.delta' and data.get('delta'):
                yield {'reasoning': data['delta']}
            elif event_type == 'response.output_text.delta' and data.get('delta'):
                yield {'content': data['delta']}
            elif event_type == 'response.completed':
                usage = (data.get('response') or {}).get('usage') or {}
                yield {'usage': {
                    'prompt_tokens': usage.get('input_tokens') or 0,
                    'completion_tokens': usage.get('output_tokens') or 0,
                    'total_tokens': usage.get('total_tokens') or 0,
                }}
                break
            elif event_type in ('response.failed', 'response.incomplete'):
                break

    @staticmethod
    def stream_chat(model, messages, options=None):
        """Stream a model response; yields ``content``/``reasoning``/``usage``
        /``tool_calls`` or ``error`` dicts. Never raises.

        When the provider streams native tool call deltas they are assembled
        and emitted once as ``{'tool_calls': [...]}`` after the stream ends.
        """
        options = options or {}
        provider = model.provider_id
        messages = LLMService._with_system_instruction(messages, model, options)
        pending_tools = {}
        try:
            if provider.provider_type == 'ollama':
                stream = LLMService._stream_ollama(model, messages, options)
            elif LLMService._uses_responses_api(model, options):
                stream = LLMService._stream_responses_api(
                    model, messages, options)
            else:
                stream = LLMService._stream_openai_compatible(
                    model, messages, options)
            for chunk in stream:
                deltas = chunk.pop('tool_call_deltas', None)
                if deltas:
                    LLMService._accumulate_tool_call_deltas(
                        pending_tools, deltas)
                if chunk:
                    yield chunk
            if pending_tools:
                yield {
                    'tool_calls': LLMService._finalize_tool_call_deltas(
                        pending_tools),
                }
        except LLMError as exc:
            yield {'error': str(exc)}
        except Exception:  # noqa: BLE001
            _logger.exception('hdai stream_chat failed')
            yield {'error': _('Unexpected provider error.')}

    @staticmethod
    def _accumulate_tool_call_deltas(pending, deltas):
        for delta in deltas or []:
            index = delta.get('index', 0)
            entry = pending.setdefault(index, {
                'id': '', 'name': '', 'arguments': '',
            })
            if delta.get('id'):
                entry['id'] = delta['id']
            function = delta.get('function') or {}
            if function.get('name'):
                entry['name'] = function['name']
            if function.get('arguments'):
                entry['arguments'] += function['arguments']

    @staticmethod
    def _finalize_tool_call_deltas(pending):
        tool_calls = []
        for index in sorted(pending):
            entry = pending[index]
            arguments = entry.get('arguments') or '{}'
            try:
                parsed = json.loads(arguments) if arguments else {}
            except ValueError:
                parsed = {}
            if not isinstance(parsed, dict):
                parsed = {}
            tool_calls.append({
                'id': entry.get('id') or 'call_%s' % index,
                'name': entry.get('name') or '',
                'arguments': parsed,
            })
        return tool_calls

    @staticmethod
    def test_connection(model):
        """Minimal request test; returns a dict with ``ok`` and either
        ``reply``/``latency``/``usage`` or ``error``."""
        try:
            started = time.time()
            content, _reasoning, usage = LLMService.chat(
                model,
                [{'role': 'user', 'content': 'Hello, please reply with OK only.'}],
                {'max_tokens': 16},
            )
            return {
                'ok': True,
                'reply': content,
                'latency': time.time() - started,
                'usage': usage,
            }
        except LLMError as exc:
            return {'ok': False, 'error': str(exc)}
        except Exception:  # noqa: BLE001
            _logger.exception('hdai test_connection failed')
            return {'ok': False, 'error': _('Unexpected error during the test.')}

    @staticmethod
    def probe_model_capabilities(model):
        """Actively probe a model's capabilities through its provider.

        Runs the plain connectivity test first, then three capability
        probes:
        - reasoning: a chat with ``reasoning_strength`` enabled; the model
          is considered to support reasoning when the provider returns
          reasoning content;
        - web search: a chat with ``web_search`` enabled; the model is
          considered to support web search when the provider accepts the
          request (providers that silently ignore the flag report
          supported; local Ollama providers are never probed for web
          search because their adapter ignores the parameter);
        - streaming: a minimal streamed chat; the model is considered to
          support streaming when the provider returns at least one chunk
          without an error.

        Provider metadata from ``list_models`` (context window / max output
        tokens / default capabilities) is merged when available. The probe
        never writes anything: callers persist the detected values.
        """
        started = time.time()
        base = LLMService.test_connection(model)
        if not base.get('ok'):
            return {
                'ok': False,
                'error': base.get('error') or _('Unknown error'),
            }
        # Plain-data snapshot so the probe paths cannot depend on ORM state
        # (same pattern as the streaming generators).
        snapshot = SimpleNamespace(
            code=model.code,
            max_output_tokens=model.max_output_tokens or 64,
            supports_reasoning=True,
            supports_web_search=True,
            supports_streaming=True,
            provider_id=model.provider_id,
        )
        prompt = [{
            'role': 'user',
            'content': 'Hello, please reply with OK only.',
        }]
        reasoning_supported = False
        reasoning_error = ''
        try:
            _content, reasoning, _usage = LLMService.chat(
                snapshot, prompt,
                {'reasoning_strength': 'low', 'max_tokens': 128})
            reasoning_supported = bool(reasoning)
            if not reasoning_supported:
                reasoning_error = _(
                    'The provider accepted the request but returned no '
                    'reasoning content.')
        except LLMError as exc:
            reasoning_error = str(exc)
        except Exception:  # noqa: BLE001
            _logger.exception('hdai reasoning probe failed')
            reasoning_error = _(
                'Unexpected error during the reasoning probe.')
        web_search_supported = False
        web_search_error = ''
        if model.provider_id.provider_type != 'ollama':
            try:
                LLMService.chat(
                    snapshot, prompt,
                    {'web_search': True, 'max_tokens': 128})
                web_search_supported = True
            except LLMError as exc:
                web_search_error = str(exc)
            except Exception:  # noqa: BLE001
                _logger.exception('hdai web search probe failed')
                web_search_error = _(
                    'Unexpected error during the web search probe.')
        streaming_supported = False
        streaming_error = ''
        try:
            first = next(iter(LLMService.stream_chat(
                snapshot, prompt, {'max_tokens': 32})), None)
            if first is None or first.get('error'):
                streaming_supported = False
                streaming_error = (first or {}).get('error') or _(
                    'The provider returned an empty or failed stream.')
            else:
                streaming_supported = True
        except Exception:  # noqa: BLE001
            _logger.exception('hdai streaming probe failed')
            streaming_error = _(
                'Unexpected error during the streaming probe.')
        metadata = {}
        try:
            for info in LLMService.list_models(model.provider_id):
                if info.get('code') == model.code:
                    metadata = info
                    break
        except Exception:  # noqa: BLE001
            _logger.info('hdai capability probe: model metadata unavailable')
        context_length = metadata.get('context_length')
        max_output_tokens = metadata.get('max_output_tokens')
        defaults = LLMService._defaults_for_model(
            model.provider_id, model.code)
        return {
            'ok': True,
            'supports_reasoning': reasoning_supported,
            'supports_web_search': web_search_supported,
            'supports_streaming': streaming_supported,
            'context_length': (
                context_length
                or model.context_length
                or defaults['context_length']),
            'context_length_detected': bool(context_length),
            'max_output_tokens': (
                max_output_tokens
                or model.max_output_tokens
                or defaults['max_output_tokens']),
            'max_output_tokens_detected': bool(max_output_tokens),
            'latency': time.time() - started,
            'reasoning_probe': {
                'supported': reasoning_supported,
                'error': reasoning_error,
            },
            'web_search_probe': {
                'supported': web_search_supported,
                'error': web_search_error,
            },
            'streaming_probe': {
                'supported': streaming_supported,
                'error': streaming_error,
            },
        }
