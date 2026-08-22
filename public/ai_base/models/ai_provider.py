# -*- coding: utf-8 -*-
"""Vendor provider layer: unified chat / embedding / image / audio APIs."""

import json
import logging
import re
import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AiError(Exception):
    """Raised when a vendor call cannot be completed."""


def normalize_base_url(url):
    """Ensure the endpoint carries an explicit http/https scheme."""
    url = (url or '').strip().rstrip('/')
    if not url:
        return url
    if '://' not in url:
        return 'http://' + url
    return url


def _http_error_message(url, status, body):
    message = _('The API returned HTTP error %s: %s') % (status, (body or '')[:500])
    if status == 404 and str(url).rstrip('/').endswith('/models'):
        message = '%s %s' % (message, _(
            'The model list endpoint was not found. For llama.cpp / vLLM, '
            'set the endpoint to http://<host>:<port>/v1 so that '
            '/v1/models is used.'))
    return message


def _request_error_message(url, exc):
    text = str(exc)
    if 'No connection adapters were found' in text:
        return _(
            'The endpoint is missing a scheme: "%s". Add http:// or https://.') % url
    if isinstance(exc, requests.ConnectionError):
        return _('Could not connect to "%s". Check the address and that the '
                 'service is running.') % url
    if isinstance(exc, requests.Timeout):
        return _('The request to "%s" timed out.') % url
    return _('Request failed: %s') % text


def http_request(method, url, timeout=60, proxies=None, **kwargs):
    """Synchronous JSON HTTP helper used by every provider client (and tests)."""
    try:
        resp = requests.request(
            method, url, timeout=timeout or 60, proxies=proxies, **kwargs)
    except requests.RequestException as exc:
        raise AiError(_request_error_message(url, exc)) from exc
    if resp.status_code >= 400:
        raise AiError(_http_error_message(url, resp.status_code, resp.text))
    resp.encoding = 'utf-8'
    try:
        return resp.json()
    except ValueError as exc:
        raise AiError(_('The API returned non-JSON data: %s') % (
            resp.text[:500])) from exc


def http_stream(method, url, timeout=120, proxies=None, **kwargs):
    try:
        resp = requests.request(
            method, url, stream=True, timeout=timeout or 120,
            proxies=proxies, **kwargs)
    except requests.RequestException as exc:
        raise AiError(_request_error_message(url, exc)) from exc
    if resp.status_code >= 400:
        raise AiError(_http_error_message(url, resp.status_code, resp.text))
    resp.encoding = 'utf-8'
    return resp


def _as_int(value):
    try:
        if value is None or value is False:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _json_safe(value):
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


_CONTEXT_KEYS = (
    'max_model_len', 'context_length', 'max_context_length',
    'n_ctx_train', 'n_ctx', 'ctx_len', 'max_seq_len',
)


def _context_from_entry(entry):
    if not isinstance(entry, dict):
        return 0
    for key in _CONTEXT_KEYS:
        value = _as_int(entry.get(key))
        if value:
            return value
    meta = entry.get('meta') if isinstance(entry.get('meta'), dict) else {}
    for key in _CONTEXT_KEYS:
        value = _as_int(meta.get(key))
        if value:
            return value
    details = entry.get('details') if isinstance(entry.get('details'), dict) else {}
    value = _as_int(details.get('context_length'))
    if value:
        return value
    info = entry.get('model_info') if isinstance(entry.get('model_info'), dict) else {}
    for key, item in info.items():
        if 'context_length' in str(key):
            value = _as_int(item)
            if value:
                return value
    show = entry.get('show') if isinstance(entry.get('show'), dict) else {}
    if show:
        nested = _context_from_entry(show)
        if nested:
            return nested
    return 0


_NAME_ACRONYMS = {
    'gpt': 'GPT', 'bge': 'BGE', 'e5': 'E5', 'gte': 'GTE',
    'llm': 'LLM', 'tts': 'TTS', 'asr': 'ASR',
}


def pretty_model_name(remote_name):
    """Turn a vendor model id into a short display label."""
    raw = (remote_name or '').strip()
    if not raw:
        return raw
    name = raw.split('/')[-1]
    tag = ''
    if ':' in name:
        name, tag = name.split(':', 1)
    tokens = []
    for token in re.split(r'[-_]+', name):
        if not token:
            continue
        lower = token.lower()
        if lower in _NAME_ACRONYMS:
            tokens.append(_NAME_ACRONYMS[lower])
        elif re.fullmatch(r'\d+(\.\d+)?[bB]', token):
            tokens.append(token.upper())
        elif re.fullmatch(r'\d+\.\d+', token):
            tokens.append(token)
        else:
            tokens.append(token[0].upper() + token[1:])
    merged = []
    index = 0
    while index < len(tokens):
        current = tokens[index]
        nxt = tokens[index + 1] if index + 1 < len(tokens) else ''
        if current == 'GPT' and re.fullmatch(r'\d+o', nxt, flags=re.I):
            merged.append('GPT-%s' % nxt)
            index += 2
            continue
        merged.append(current)
        index += 1
    result = ' '.join(merged)
    if tag:
        result = '%s (%s)' % (result, tag)
    return result or raw


def _infer_model_kind(name):
    lower = (name or '').lower()
    if any(token in lower for token in (
            'embed', 'embedding', 'bge-', 'e5-', 'gte-')):
        return 'embedding'
    if any(token in lower for token in (
            'whisper', 'transcribe', 'speech-to-text')):
        return 'audio_transcribe'
    if any(token in lower for token in (
            'dall-e', 'dalle', 'flux', 'sdxl', 'stable-diffusion',
            'image-generate')):
        return 'image'
    return 'chat'


def _usage(raw):
    raw = raw or {}
    prompt = int(raw.get('prompt_tokens') or raw.get('input_tokens') or 0)
    completion = int(raw.get('completion_tokens') or raw.get('output_tokens') or 0)
    total = int(raw.get('total_tokens') or (prompt + completion))
    return {
        'prompt_tokens': prompt,
        'completion_tokens': completion,
        'total_tokens': total,
    }


def _parse_tool_calls(message):
    calls = []
    for call in (message or {}).get('tool_calls') or []:
        function = call.get('function') or {}
        name = function.get('name') or ''
        if not name:
            continue
        arguments = function.get('arguments') or {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments else {}
            except ValueError:
                arguments = {}
        if not isinstance(arguments, dict):
            arguments = {}
        calls.append({
            'id': call.get('id'),
            'name': name,
            'arguments': arguments,
        })
    return calls


class BaseAdapter:
    """HTTP client for an ai.provider record. Subclasses implement the four primitives."""

    def __init__(self, provider):
        self.provider = provider

    @property
    def endpoint(self):
        return normalize_base_url(
            self.provider.endpoint or getattr(self.provider, 'base_url', ''))

    @property
    def timeout(self):
        return self.provider.timeout or 60

    @property
    def proxies(self):
        proxy = (self.provider.proxy or '').strip()
        if not proxy:
            return None
        return {'http': proxy, 'https': proxy}

    def _api_key(self):
        sudo = getattr(self.provider, 'sudo', None)
        if sudo is not None:
            return sudo().api_key
        return self.provider.api_key

    def _headers(self):
        key = self._api_key()
        return {'Authorization': 'Bearer %s' % key} if key else {}

    def _require_key_if_cloud(self):
        if self._is_local():
            return
        if not self._api_key():
            raise AiError(_('No API key is configured for provider "%s".') % (
                self.provider.name,))

    def _is_local(self):
        provider_type = getattr(self.provider, 'provider_type', '')
        if provider_type in ('ollama',):
            return True
        base = (self.endpoint or '').lower()
        return ('localhost' in base or '127.0.0.1' in base or '0.0.0.0' in base)

    def _remote_name(self, model):
        return model.model_name_remote or model.code

    def list_models(self):
        """Return remote model descriptors used to fill ``ai.model``."""
        return []

    def _normalize_listed_model(self, remote_name, entry):
        entry = entry if isinstance(entry, dict) else {}
        kind = _infer_model_kind(remote_name)
        context = _context_from_entry(entry)
        max_out = _as_int(
            entry.get('max_tokens') or entry.get('max_output_tokens'))
        meta = entry.get('meta') if isinstance(entry.get('meta'), dict) else {}
        if not max_out:
            max_out = _as_int(
                meta.get('max_tokens') or meta.get('max_output_tokens'))
        return {
            'remote_name': remote_name,
            'name': pretty_model_name(remote_name),
            'model_kind': kind,
            'max_context_tokens': context or None,
            'max_tokens_default': max_out or None,
            'supports_streaming': kind == 'chat',
            'vendor_info': _json_safe(entry),
        }

    def chat_completion(self, model, messages, options=None):
        raise NotImplementedError

    def embedding(self, model, texts, options=None):
        raise NotImplementedError

    def image_generate(self, model, prompt, options=None):
        raise NotImplementedError

    def audio_transcribe(self, model, audio_bytes, filename='audio.wav', options=None):
        raise NotImplementedError

    def stream_chat(self, model, messages, options=None):
        raise NotImplementedError

    # Backwards-friendly aliases used by the service layer.
    def chat(self, model, messages, options=None):
        return self.chat_completion(model, messages, options)

    def embed(self, model, texts, options=None):
        return self.embedding(model, texts, options)


class OpenAICompatibleAdapter(BaseAdapter):
    """OpenAI Chat Completions / Embeddings / Images / Audio protocol."""

    def _chat_url(self):
        return self.endpoint + '/chat/completions'

    def _payload(self, model, messages, options, stream=False):
        options = options or {}
        payload = {
            'model': self._remote_name(model),
            'messages': messages,
            'stream': stream,
        }
        temperature = options.get('temperature')
        if temperature is None:
            temperature = model.temperature_default
        if temperature is not None:
            payload['temperature'] = temperature
        top_p = options.get('top_p')
        if top_p is None:
            top_p = model.top_p_default
        if top_p is not None:
            payload['top_p'] = top_p
        max_tokens = options.get('max_tokens') or model.max_tokens_default
        if max_tokens:
            payload['max_tokens'] = max_tokens
        tools = options.get('tools')
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = options.get('tool_choice', 'auto')
        return payload

    def chat_completion(self, model, messages, options=None):
        self._require_key_if_cloud()
        data = http_request(
            'POST', self._chat_url(),
            timeout=self.timeout, proxies=self.proxies,
            headers=self._headers(),
            json=self._payload(model, messages, options, stream=False),
        )
        choice = (data.get('choices') or [{}])[0]
        message = choice.get('message') or {}
        return {
            'content': message.get('content') or '',
            'reasoning': message.get('reasoning_content') or '',
            'tool_calls': _parse_tool_calls(message),
            'usage': _usage(data.get('usage')),
            'raw': data,
        }

    def stream_chat(self, model, messages, options=None):
        self._require_key_if_cloud()
        payload = self._payload(model, messages, options, stream=True)
        payload['stream_options'] = {'include_usage': True}
        resp = http_stream(
            'POST', self._chat_url(),
            timeout=self.timeout, proxies=self.proxies,
            headers=self._headers(), json=payload)
        for raw_line in resp.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            line = raw_line.decode('utf-8', errors='replace')
            if not line.startswith('data:'):
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
            chunk = {}
            if delta.get('content'):
                chunk['content'] = delta['content']
            if delta.get('reasoning_content'):
                chunk['reasoning'] = delta['reasoning_content']
            if data.get('usage'):
                chunk['usage'] = _usage(data['usage'])
            if chunk:
                yield chunk

    def embedding(self, model, texts, options=None):
        self._require_key_if_cloud()
        data = http_request(
            'POST', self.endpoint + '/embeddings',
            timeout=self.timeout, proxies=self.proxies,
            headers=self._headers(),
            json={'model': self._remote_name(model), 'input': list(texts)},
        )
        items = sorted(data.get('data') or [], key=lambda row: row.get('index', 0))
        return [row.get('embedding') or [] for row in items]

    def image_generate(self, model, prompt, options=None):
        self._require_key_if_cloud()
        options = options or {}
        payload = {
            'model': self._remote_name(model),
            'prompt': prompt,
            'n': options.get('n') or 1,
            'size': options.get('size') or '1024x1024',
        }
        data = http_request(
            'POST', self.endpoint + '/images/generations',
            timeout=self.timeout, proxies=self.proxies,
            headers=self._headers(), json=payload)
        return {'raw': data, 'data': data.get('data') or []}

    def audio_transcribe(self, model, audio_bytes, filename='audio.wav', options=None):
        self._require_key_if_cloud()
        files = {'file': (filename, audio_bytes)}
        data = http_request(
            'POST', self.endpoint + '/audio/transcriptions',
            timeout=self.timeout, proxies=self.proxies,
            headers=self._headers(),
            data={'model': self._remote_name(model)},
            files=files)
        return {'text': data.get('text') or '', 'raw': data}

    def list_models(self):
        self._require_key_if_cloud()
        data = http_request(
            'GET', self.endpoint + '/models',
            timeout=self.timeout, proxies=self.proxies,
            headers=self._headers())
        models = []
        for entry in data.get('data') or []:
            remote = entry.get('id')
            if not remote:
                continue
            models.append(self._normalize_listed_model(remote, entry))
        return models


class QwenAdapter(OpenAICompatibleAdapter):
    """Tongyi Qianwen via the OpenAI-compatible DashScope endpoint."""


class DeepSeekAdapter(OpenAICompatibleAdapter):
    """DeepSeek cloud (OpenAI-compatible chat completions)."""


class CustomAdapter(OpenAICompatibleAdapter):
    """Private / self-hosted OpenAI-compatible gateway."""


class OllamaAdapter(BaseAdapter):
    """Native Ollama HTTP API (also understands OpenAI-compatible /v1)."""

    def chat_completion(self, model, messages, options=None):
        options = options or {}
        payload = {
            'model': self._remote_name(model),
            'messages': messages,
            'stream': False,
        }
        sampling = {}
        temperature = options.get('temperature', model.temperature_default)
        if temperature is not None:
            sampling['temperature'] = temperature
        top_p = options.get('top_p', model.top_p_default)
        if top_p is not None:
            sampling['top_p'] = top_p
        max_tokens = options.get('max_tokens') or model.max_tokens_default
        if max_tokens:
            sampling['num_predict'] = max_tokens
        if sampling:
            payload['options'] = sampling
        data = http_request(
            'POST', self.endpoint + '/api/chat',
            timeout=self.timeout, proxies=self.proxies, json=payload)
        message = data.get('message') or {}
        usage = {
            'prompt_tokens': data.get('prompt_eval_count') or 0,
            'completion_tokens': data.get('eval_count') or 0,
        }
        usage['total_tokens'] = usage['prompt_tokens'] + usage['completion_tokens']
        return {
            'content': message.get('content') or '',
            'reasoning': message.get('reasoning_content') or '',
            'tool_calls': [],
            'usage': usage,
            'raw': data,
        }

    def stream_chat(self, model, messages, options=None):
        payload = {
            'model': self._remote_name(model),
            'messages': messages,
            'stream': True,
        }
        resp = http_stream(
            'POST', self.endpoint + '/api/chat',
            timeout=self.timeout, proxies=self.proxies, json=payload)
        for raw_line in resp.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            try:
                data = json.loads(raw_line.decode('utf-8', errors='replace'))
            except ValueError:
                continue
            message = data.get('message') or {}
            chunk = {}
            if message.get('content'):
                chunk['content'] = message['content']
            if data.get('done'):
                prompt = data.get('prompt_eval_count') or 0
                completion = data.get('eval_count') or 0
                chunk['usage'] = {
                    'prompt_tokens': prompt,
                    'completion_tokens': completion,
                    'total_tokens': prompt + completion,
                }
            if chunk:
                yield chunk

    def embedding(self, model, texts, options=None):
        vectors = []
        for text in texts:
            data = http_request(
                'POST', self.endpoint + '/api/embeddings',
                timeout=self.timeout, proxies=self.proxies,
                json={'model': self._remote_name(model), 'prompt': text})
            vectors.append(data.get('embedding') or [])
        return vectors

    def image_generate(self, model, prompt, options=None):
        raise AiError(_('Ollama does not implement image generation in this provider.'))

    def audio_transcribe(self, model, audio_bytes, filename='audio.wav', options=None):
        raise AiError(_('Ollama does not implement audio transcription in this provider.'))

    def list_models(self):
        data = http_request(
            'GET', self.endpoint + '/api/tags',
            timeout=self.timeout, proxies=self.proxies)
        models = []
        for entry in data.get('models') or []:
            remote = entry.get('name') or entry.get('model')
            if not remote:
                continue
            extra = dict(entry)
            try:
                shown = http_request(
                    'POST', self.endpoint + '/api/show',
                    timeout=self.timeout, proxies=self.proxies,
                    json={'name': remote})
                extra['show'] = shown
                if isinstance(shown, dict):
                    extra.setdefault('details', shown.get('details'))
                    extra.setdefault('model_info', shown.get('model_info'))
                    extra.setdefault('parameters', shown.get('parameters'))
            except AiError:
                _logger.info('ollama /api/show unavailable for %s', remote)
            models.append(self._normalize_listed_model(remote, extra))
        return models


class ErnieAdapter(BaseAdapter):
    """Baidu Ernie / Wenxin workshop chat + embedding."""

    def _access_token(self):
        key = self._api_key() or ''
        secret = (self.provider.api_secret or '').strip()
        if not key or not secret:
            raise AiError(_('Ernie requires both API Key and Secret Key.'))
        url = ('https://aip.baidubce.com/oauth/2.0/token'
               '?grant_type=client_credentials&client_id=%s&client_secret=%s') % (
                   key, secret)
        data = http_request('POST', url, timeout=self.timeout, proxies=self.proxies)
        token = data.get('access_token')
        if not token:
            raise AiError(_('Ernie did not return an access_token.'))
        return token

    def chat_completion(self, model, messages, options=None):
        options = options or {}
        token = self._access_token()
        url = '%s?access_token=%s' % (self.endpoint, token)
        # Ernie uses system as a top-level field.
        system = ''
        cleaned = []
        for message in messages:
            if message.get('role') == 'system' and not system:
                system = message.get('content') or ''
            else:
                cleaned.append(message)
        payload = {'messages': cleaned}
        if system:
            payload['system'] = system
        if options.get('temperature') is not None or model.temperature_default:
            payload['temperature'] = options.get('temperature', model.temperature_default)
        data = http_request(
            'POST', url, timeout=self.timeout, proxies=self.proxies, json=payload)
        return {
            'content': data.get('result') or '',
            'reasoning': '',
            'tool_calls': [],
            'usage': _usage(data.get('usage')),
            'raw': data,
        }

    def stream_chat(self, model, messages, options=None):
        result = self.chat_completion(model, messages, options)
        if result.get('content'):
            yield {'content': result['content']}
        if result.get('usage'):
            yield {'usage': result['usage']}

    def embedding(self, model, texts, options=None):
        token = self._access_token()
        url = '%s?access_token=%s' % (self.endpoint, token)
        data = http_request(
            'POST', url, timeout=self.timeout, proxies=self.proxies,
            json={'input': list(texts)})
        items = data.get('data') or []
        return [row.get('embedding') or [] for row in items]

    def image_generate(self, model, prompt, options=None):
        raise AiError(_('Ernie image generation is not implemented in this provider.'))

    def audio_transcribe(self, model, audio_bytes, filename='audio.wav', options=None):
        raise AiError(_('Ernie audio transcription is not implemented in this provider.'))

    def list_models(self):
        self._access_token()
        return []


ADAPTER_CLASSES = {
    'openai_compat': OpenAICompatibleAdapter,
    'qwen': QwenAdapter,
    'ernie': ErnieAdapter,
    'deepseek': DeepSeekAdapter,
    'ollama': OllamaAdapter,
    'custom': CustomAdapter,
}


def get_provider(provider):
    """Return an HTTP client for an ``ai.provider`` record."""
    provider_type = getattr(provider, 'provider_type', None) or 'openai_compat'
    cls = ADAPTER_CLASSES.get(provider_type) or OpenAICompatibleAdapter
    return cls(provider)


class AiProvider(models.Model):
    _name = 'ai.provider'
    _description = 'AI Model Provider'
    _order = 'sequence, name'
    _check_company_auto = True

    _TYPE_PRESETS = {
        'openai_compat': {
            'name': 'OpenAI Compatible',
            'endpoint': 'https://api.openai.com/v1',
        },
        'qwen': {
            'name': 'Tongyi Qianwen',
            'endpoint': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        },
        'ernie': {
            'name': 'Wenxin Yiyan',
            'endpoint': 'https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat/completions',
        },
        'deepseek': {
            'name': 'DeepSeek',
            'endpoint': 'https://api.deepseek.com/v1',
        },
        'ollama': {
            'name': 'Ollama (Local)',
            'endpoint': 'http://localhost:11434',
        },
        'custom': {
            'name': 'Private Model',
            'endpoint': '',
        },
    }

    name = fields.Char(string='Provider Name', required=True)
    provider_type = fields.Selection([
        ('openai_compat', 'OpenAI Compatible'),
        ('qwen', 'Tongyi Qianwen'),
        ('ernie', 'Wenxin Yiyan'),
        ('deepseek', 'DeepSeek'),
        ('ollama', 'Ollama (Local)'),
        ('custom', 'Private / Custom'),
    ], string='Provider Type', required=True, default='openai_compat')
    endpoint = fields.Char(string='API Endpoint')
    api_key = fields.Char(
        string='API Key', copy=False, groups='ai_base.group_manager')
    api_secret = fields.Char(
        string='API Secret', copy=False, groups='ai_base.group_manager',
        help='Used by Ernie (Wenxin) as the secret key.')
    timeout = fields.Integer(string='Timeout (seconds)', default=60)
    proxy = fields.Char(string='HTTP Proxy')
    sequence = fields.Integer(string='Sequence', default=10)
    is_active = fields.Boolean(
        string='Active', default=True,
        help='Master switch for this provider. Disabled providers are skipped '
             'even if a model under them is active or marked preferred.')
    note = fields.Text(string='Notes')
    company_id = fields.Many2one(
        'res.company', string='Company', index=True,
        help='Empty means the provider is available to every company.')
    model_ids = fields.One2many('ai.model', 'provider_id', string='Models')
    model_count = fields.Integer(compute='_compute_model_count', string='Models')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            preset = self._TYPE_PRESETS.get(vals.get('provider_type') or 'openai_compat')
            if preset:
                for field, value in preset.items():
                    vals.setdefault(field, value)
            if vals.get('endpoint'):
                vals['endpoint'] = normalize_base_url(vals['endpoint'])
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('endpoint'):
            vals['endpoint'] = normalize_base_url(vals['endpoint'])
        return super().write(vals)

    @api.onchange('provider_type')
    def _onchange_provider_type(self):
        preset = self._TYPE_PRESETS.get(self.provider_type)
        if not preset:
            return
        previous = self._origin.provider_type if self._origin else False
        previous_preset = self._TYPE_PRESETS.get(previous, {})
        if not self.name or self.name == previous_preset.get('name'):
            self.name = preset['name']
        self.endpoint = preset['endpoint']

    @api.depends('model_ids')
    def _compute_model_count(self):
        data = self.env['ai.model']._read_group(
            [('provider_id', 'in', self.ids)],
            ['provider_id'], ['provider_id:count'])
        count_map = {provider.id: count for provider, count in data}
        for provider in self:
            provider.model_count = count_map.get(provider.id, 0)

    def _get_client(self):
        self.ensure_one()
        return get_provider(self)

    def action_test_connection(self):
        """Health-check the provider and create listed models on success."""
        self.ensure_one()
        if not self.is_active:
            raise UserError(_('Provider "%s" is disabled.') % self.name)
        client = self._get_client()
        try:
            listed = client.list_models()
        except AiError as exc:
            return self._notify(False, _('Connection test failed: %s') % exc)
        created, updated = self._sync_listed_models(listed)
        if created and updated:
            message = _(
                'Connection successful. Created %s model(s), updated %s.') % (
                    created, updated)
        elif created:
            message = _('Connection successful. Created %s model(s).') % created
        elif updated:
            message = _('Connection successful. Updated %s existing model(s).') % updated
        else:
            message = _('Connection successful, but the API returned no models.')
        return self._notify(True, message, reload=True)

    def _sync_listed_models(self, listed):
        self.ensure_one()
        existing = {
            model.model_name_remote: model for model in self.model_ids
            if model.model_name_remote
        }
        created = 0
        updated = 0
        for info in listed:
            remote = info.get('remote_name')
            if not remote:
                continue
            vals = self._listed_model_vals(info)
            current = existing.get(remote)
            if current:
                if current._name_tracks_remote():
                    vals['name'] = pretty_model_name(remote)
                current.write(vals)
                updated += 1
                continue
            display = info.get('name') or ''
            if not display or display == remote:
                display = pretty_model_name(remote)
            vals.update({
                'name': display,
                'code': self._unique_model_code(remote),
                'provider_id': self.id,
                'model_name_remote': remote,
                'model_kind': info.get('model_kind') or 'chat',
            })
            created_model = self.env['ai.model'].create(vals)
            existing[remote] = created_model
            created += 1
        return created, updated

    def _listed_model_vals(self, info):
        vals = {
            'vendor_info': info.get('vendor_info') or {},
            'supports_streaming': bool(info.get('supports_streaming')),
        }
        if info.get('max_context_tokens'):
            vals['max_context_tokens'] = info['max_context_tokens']
        if info.get('max_tokens_default'):
            vals['max_tokens_default'] = info['max_tokens_default']
        return vals

    def _unique_model_code(self, remote_name):
        return self.env['ai.model']._unique_code_for_remote(
            remote_name, provider_id=self.id)

    def _notify(self, ok, message, reload=False):
        params = {
            'type': 'success' if ok else 'warning',
            'title': _('Connection Test Successful') if ok else _(
                'Connection Test Failed'),
            'message': message,
            'sticky': not ok,
        }
        if reload:
            params['next'] = {
                'type': 'ir.actions.act_window',
                'res_model': 'ai.provider',
                'res_id': self.id,
                'view_mode': 'form',
                'views': [(False, 'form')],
                'target': 'current',
            }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': params,
        }
