# -*- coding: utf-8 -*-
"""Tool helpers for hdai_base (schema, parsing, legacy BaseTool cards).

Canonical registration is ``@ai_tool`` / ``hdai.tool``. This module keeps
pure helpers for the tool loop and a legacy ``BaseTool`` registry for old
UI card paths. New tools must not call ``register_tool``.
"""

import json
import logging
import re

from odoo import _
from odoo.tools.translate import get_translation

_logger = logging.getLogger(__name__)

_TOOL_REGISTRY = {}
_FENCE_RE = re.compile(r'```json\s*(.*?)```', re.DOTALL)
_DOMAIN_OPERATORS = ('&', '|', '!')


class ToolError(Exception):
    """Raised by tool validation/execution; carries user-facing info."""

    def __init__(self, code, message, hint='', admin_notify=False,
                 action=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.admin_notify = admin_notify
        self.action = action

    def to_dict(self):
        return {
            'code': self.code,
            'message': self.message,
            'hint': self.hint,
            'admin_notify': self.admin_notify,
            'action': self.action,
        }


class BaseTool:
    """Legacy card tool. Prefer ``@ai_tool`` on an AbstractModel instead."""

    name = ''
    label = ''
    icon = 'fa-cogs'
    module = 'hdai'

    def validate(self, env, payload):
        """Raise ToolError when the tool cannot be executed yet."""

    def execute(self, env, payload):
        """Return an Odoo action or raise ToolError."""
        raise NotImplementedError

    def card(self, env, payload, error=None):
        def translated(value):
            try:
                return get_translation(self.module, env.lang, value, ())
            except Exception:  # noqa: BLE001
                return value
        card = {
            'tool': self.name,
            'name': translated(self.label),
            'icon': self.icon,
            'label': translated((payload or {}).get('label') or self.label),
            'payload': payload,
        }
        if error:
            card['status'] = 'blocked'
            card['error'] = (
                error if isinstance(error, dict) else error.to_dict())
        else:
            card['status'] = 'ready'
        return card


def register_tool(tool):
    """Legacy: register a ``BaseTool`` instance. Do not use for new tools."""
    _TOOL_REGISTRY[tool.name] = tool()
    return tool


def get_tool(name):
    """Legacy BaseTool lookup. Prefer ``env['hdai.tool']`` for new code."""
    return _TOOL_REGISTRY.get(name)


def parse_tool_payload(reply):
    """Extract a ``{"tool": ...}`` payload from a reply (pure function)."""
    if not reply:
        return None
    text = str(reply).strip()
    match = _FENCE_RE.search(text)
    candidate = match.group(1) if match else text
    try:
        data = json.loads(candidate)
    except ValueError:
        return None
    if not isinstance(data, dict) or not data.get('tool'):
        return None
    return data


def split_tool_content(content):
    """Split content around a tool JSON block: return ``(before, payload,
    after)`` so the client can render the explanation text, the tool card and
    the trailing text instead of showing the raw JSON."""
    if not content:
        return content, None, ''
    text = str(content)
    match = _FENCE_RE.search(text)
    if match:
        before = text[:match.start()]
        after = text[match.end():]
        candidate = match.group(1)
    else:
        start = text.find('{')
        if start == -1:
            return text, None, ''
        depth = 0
        end = -1
        for index in range(start, len(text)):
            char = text[index]
            if char == '{':
                depth += 1
            elif char == '}':
                depth -= 1
                if depth == 0:
                    end = index
                    break
        if end == -1:
            return text, None, ''
        before = text[:start]
        after = text[end + 1:]
        candidate = text[start:end + 1]
    try:
        payload = json.loads(candidate)
    except ValueError:
        return text, None, ''
    if not isinstance(payload, dict) or not payload.get('tool'):
        return text, None, ''
    return before, payload, after


def extract_tool_calls(content):
    """Extract every text-protocol tool payload from a reply (pure function).

    The server-side tool loop accepts both native ``tool_calls`` returned by
    the provider and the text protocol used by providers without native
    function calling: the model writes one or more fenced JSON blocks
    ``{"tool": "<name>", "params": {...}}`` in its reply. The function
    returns a list of dicts normalized to the native shape
    ``{'id': None, 'name': ..., 'arguments': {...}}``.
    """
    if not content:
        return []
    text = str(content)
    calls = []
    for match in _FENCE_RE.finditer(text):
        try:
            data = json.loads(match.group(1))
        except ValueError:
            continue
        if not isinstance(data, dict) or not data.get('tool'):
            continue
        params = data.get('params')
        calls.append({
            'id': None,
            'name': str(data['tool']),
            'arguments': params if isinstance(params, dict) else {},
        })
    return calls


def strip_tool_blocks(content):
    """Remove every fenced JSON tool block from a reply (pure function)."""
    if not content:
        return ''
    return _FENCE_RE.sub('', str(content)).strip()


def validate_tool_schema(params, schema):
    """Validate ``params`` against a JSON Schema subset (pure function).

    The tool framework declares its input schemas with the subset documented
    in HD-AI-STD-001 section 6: ``type``, ``properties``/``required``/
    ``additionalProperties``, ``items``, ``enum``/``const``, numeric bounds,
    string length bounds and ``pattern``. Returns ``(ok, errors)`` where
    ``errors`` is a list of human-readable violation descriptions.
    """
    errors = []
    _validate_value(params, schema, errors, '$')
    return (not errors, errors)


def _validate_value(value, schema, errors, path):
    """Recursive validation helper."""
    if not isinstance(schema, dict):
        return
    expected = schema.get('type')
    if expected == 'object':
        if not isinstance(value, dict):
            errors.append(_schema_error(path, 'must be an object'))
            return
        if schema.get('additionalProperties') is False:
            allowed = set(schema.get('properties') or {})
            for key in value:
                if key not in allowed:
                    errors.append(_schema_error(
                        '%s.%s' % (path, key),
                        'is not allowed here'))
        for key, sub_schema in (schema.get('properties') or {}).items():
            if key in value:
                _validate_value(
                    value[key], sub_schema, errors,
                    '%s.%s' % (path, key))
        for key in schema.get('required') or []:
            if key not in value:
                errors.append(_schema_error(
                    '%s.%s' % (path, key), 'is required'))
    elif expected == 'array':
        if not isinstance(value, list):
            errors.append(_schema_error(path, 'must be an array'))
            return
        item_schema = schema.get('items')
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_value(
                    item, item_schema, errors,
                    '%s[%s]' % (path, index))
        elif isinstance(item_schema, list):
            for index, item in enumerate(value):
                if index < len(item_schema):
                    _validate_value(
                        item, item_schema[index], errors,
                        '%s[%s]' % (path, index))
        min_items = schema.get('minItems')
        if min_items is not None and len(value) < min_items:
            errors.append(_schema_error(
                path, 'must have at least %s items' % min_items))
        max_items = schema.get('maxItems')
        if max_items is not None and len(value) > max_items:
            errors.append(_schema_error(
                path, 'must have at most %s items' % max_items))
    else:
        _validate_scalar(value, schema, errors, path)


def _validate_scalar(value, schema, errors, path):
    expected = schema.get('type')
    if expected == 'string':
        if not isinstance(value, str):
            errors.append(_schema_error(path, 'must be a string'))
            return
        min_length = schema.get('minLength')
        if min_length is not None and len(value) < min_length:
            errors.append(_schema_error(
                path, 'must be at least %s characters' % min_length))
        max_length = schema.get('maxLength')
        if max_length is not None and len(value) > max_length:
            errors.append(_schema_error(
                path, 'must be at most %s characters' % max_length))
        pattern = schema.get('pattern')
        if pattern and not re.match(pattern, value):
            errors.append(_schema_error(
                path, 'does not match the required pattern'))
    elif expected == 'integer':
        if not isinstance(value, int) or isinstance(value, bool):
            errors.append(_schema_error(path, 'must be an integer'))
            return
        _validate_number_bounds(value, schema, errors, path)
    elif expected == 'number':
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(_schema_error(path, 'must be a number'))
            return
        _validate_number_bounds(value, schema, errors, path)
    elif expected == 'boolean':
        if not isinstance(value, bool):
            errors.append(_schema_error(path, 'must be a boolean'))
            return
    elif expected is None:
        pass
    enum = schema.get('enum')
    if enum is not None and value not in enum:
        errors.append(_schema_error(path, 'must be one of %s' % enum))
    const = schema.get('const')
    if const is not None and value != const:
        errors.append(_schema_error(path, 'must equal %r' % const))


def _validate_number_bounds(value, schema, errors, path):
    minimum = schema.get('minimum')
    if minimum is not None and value < minimum:
        errors.append(_schema_error(
            path, 'must be >= %s' % minimum))
    maximum = schema.get('maximum')
    if maximum is not None and value > maximum:
        errors.append(_schema_error(
            path, 'must be <= %s' % maximum))


def _schema_error(path, message):
    return '%s %s' % (path, message)


def build_tool_card(env, payload):
    """Pre-validate a payload and return its tool card (never raises).

    Prefers the canonical ``hdai.tool`` registry; falls back to the legacy
    ``BaseTool`` registry only when no ``@ai_tool`` entry exists.
    """
    if not isinstance(payload, dict) or not payload.get('tool'):
        return {
            'tool': 'unknown',
            'name': _('Unknown tool'),
            'icon': 'fa-question-circle',
            'label': _('Invalid tool call'),
            'status': 'blocked',
            'error': {
                'code': 'invalid_payload',
                'message': _('The request is not a valid tool call.'),
                'hint': '',
                'admin_notify': False,
            },
            'payload': payload,
        }
    tool_name = payload.get('tool')
    params = payload.get('params') or {}
    registry_tool = env['hdai.tool'].sudo().search(
        [('name', '=', tool_name), ('active', '=', True)], limit=1)
    if registry_tool:
        ok, errors = validate_tool_schema(
            params, registry_tool.input_schema or {})
        label = (registry_tool.description or registry_tool.name)[:120]
        card = {
            'tool': registry_tool.name,
            'name': registry_tool.name,
            'icon': 'fa-cogs',
            'label': label,
            'status': 'ready',
            'payload': {'tool': registry_tool.name, 'params': params},
            'suggestive': bool(registry_tool.suggestive),
        }
        if not env['hdai.tool']._check_permissions(registry_tool):
            card['status'] = 'blocked'
            card['error'] = {
                'code': 'forbidden',
                'message': _('You do not have permission to call tool "%s".') % (
                    tool_name),
                'hint': '',
                'admin_notify': False,
            }
            return card
        if not ok:
            card['status'] = 'blocked'
            card['error'] = {
                'code': 'invalid_schema',
                'message': _('The tool call parameters are invalid.'),
                'hint': errors[0] if errors else '',
                'admin_notify': False,
            }
            return card
        return card
    tool = get_tool(tool_name)
    if not tool:
        return {
            'tool': tool_name,
            'name': _('Unknown tool'),
            'icon': 'fa-question-circle',
            'label': _('Unknown tool'),
            'status': 'blocked',
            'error': {
                'code': 'unknown_tool',
                'message': _('The requested tool "%s" is not available.') % (
                    tool_name),
                'hint': _('The tool extension module may not be installed.'),
                'admin_notify': True,
            },
            'payload': payload,
        }
    try:
        tool.validate(env, payload)
    except ToolError as exc:
        return tool.card(env, payload, error=exc.to_dict())
    return tool.card(env, payload)


# ---------------------------------------------------------------------------
# Domain helpers (shared by tools)
# ---------------------------------------------------------------------------

def _resolve_m2o_value(env, comodel, value):
    """Resolve a display name to a record id (exactly one match required)."""
    if not isinstance(value, str):
        return value
    value = value.strip()
    # Exact match on the stored name first: display_name searches can be
    # fuzzy (e.g. res.partner matches partial names), which would resolve to
    # multiple records.
    records = comodel
    if 'name' in comodel._fields:
        records = comodel.search([('name', '=', value)])
    if not records:
        records = comodel.search([('display_name', '=', value)])
    if not records:
        raise ToolError(
            'invalid_domain',
            _('No %s record named "%s" was found.') % (
                comodel._description, value),
            _('Use an existing record name or a valid record id.'))
    if len(records) > 1:
        raise ToolError(
            'invalid_domain',
            _('Multiple %s records match "%s".') % (
                comodel._description, value),
            _('Make the filter more specific.'))
    return records.id


def _valid_field_path(env, model, field_path):
    """Check a (possibly dotted) field path on a model."""
    parts = field_path.split('.')
    current = model
    for index, part in enumerate(parts):
        field = current._fields.get(part)
        if not field:
            return False
        if index < len(parts) - 1:
            if not field.relational:
                return False
            current = env[field.comodel_name]
    return True


def resolve_domain(env, model, domain):
    """Validate a domain and resolve many2one display names to ids."""
    if not isinstance(domain, list):
        raise ToolError(
            'invalid_domain', _('The filter must be a list of conditions.'))
    resolved = []
    for node in domain:
        if node in _DOMAIN_OPERATORS:
            resolved.append(node)
            continue
        if not isinstance(node, (tuple, list)) or len(node) != 3:
            raise ToolError(
                'invalid_domain', _('Malformed filter condition.'))
        field_path, operator, value = node[0], node[1], node[2]
        base = field_path.split('.')[0]
        if base not in model._fields:
            raise ToolError(
                'invalid_domain',
                _('Field "%s" does not exist on %s.') % (
                    base, model._description),
                _('Check the requested field name.'))
        if '.' in field_path and not _valid_field_path(env, model, field_path):
            raise ToolError(
                'invalid_domain',
                _('Invalid field path "%s".') % field_path)
        field = model._fields[base]
        if field.relational and operator in ('=', 'in') and isinstance(
                value, str):
            resolved.append([
                field_path, operator,
                _resolve_m2o_value(env, env[field.comodel_name], value),
            ])
        elif (field.relational and operator == 'in'
                and isinstance(value, (list, tuple))
                and all(isinstance(item, str) for item in value)):
            comodel = env[field.comodel_name]
            resolved.append([
                field_path, operator,
                [_resolve_m2o_value(env, comodel, item) for item in value],
            ])
        else:
            resolved.append([field_path, operator, value])
    return resolved
