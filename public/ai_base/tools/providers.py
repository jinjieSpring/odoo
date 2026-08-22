# -*- coding: utf-8 -*-
"""HTTP clients for ai.provider records."""

import json
import logging

from odoo import _

from .http import AiError, http_request, http_stream, normalize_base_url
from .model_info import (
    _as_int,
    _context_from_entry,
    _json_safe,
    infer_model_kind,
    parse_tool_calls,
    pretty_model_name,
    usage_from_raw,
)

_logger = logging.getLogger(__name__)


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
        kind = infer_model_kind(remote_name)
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
            'tool_calls': parse_tool_calls(message),
            'usage': usage_from_raw(data.get('usage')),
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
                chunk['usage'] = usage_from_raw(data['usage'])
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
            'usage': usage_from_raw(data.get('usage')),
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
