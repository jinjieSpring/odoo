# -*- coding: utf-8 -*-
"""Normalize vendor model payloads into ai.model field values."""

import json
import re

_CONTEXT_KEYS = (
    'max_model_len', 'context_length', 'max_context_length',
    'n_ctx_train', 'n_ctx', 'ctx_len', 'max_seq_len',
)

_NAME_ACRONYMS = {
    'gpt': 'GPT', 'bge': 'BGE', 'e5': 'E5', 'gte': 'GTE',
    'llm': 'LLM', 'tts': 'TTS', 'asr': 'ASR',
}


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


def infer_model_kind(name):
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


def usage_from_raw(raw):
    raw = raw or {}
    prompt = int(raw.get('prompt_tokens') or raw.get('input_tokens') or 0)
    completion = int(raw.get('completion_tokens') or raw.get('output_tokens') or 0)
    total = int(raw.get('total_tokens') or (prompt + completion))
    return {
        'prompt_tokens': prompt,
        'completion_tokens': completion,
        'total_tokens': total,
    }


def parse_tool_calls(message):
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
