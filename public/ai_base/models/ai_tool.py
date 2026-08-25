# -*- coding: utf-8 -*-
"""AI tool registry: Python functions, ORM actions and HTTP endpoints."""

import json
import logging
import re
import time
from datetime import timedelta

import requests

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

AI_TOOL_REGISTRY = {}
_FENCE_RE = re.compile(r'```json\s*(.*?)```', re.DOTALL)
_OPENAI_FUNCTION_NAME_RE = re.compile(r'^[a-zA-Z0-9_-]+$')
_OPENAI_FUNCTION_NAME_INVALID_RE = re.compile(r'[^a-zA-Z0-9_-]+')
_OPENAI_FUNCTION_NAME_MAX = 64
_SENSITIVE_FIELDS = (
    'password', 'api_key', 'api_secret', 'credit_card', 'bank_account',
    'id_number', 'secret', 'token',
)


def openai_function_name(name):
    """Sanitize a tool name for OpenAI ``tools[].function.name``.

    Providers reject names that do not match ``^[a-zA-Z0-9_-]+$``. Internal
    names may contain dots (``generic.search_count``) or non-ASCII.
    """
    name = (name or '').strip()
    if (
        _OPENAI_FUNCTION_NAME_RE.fullmatch(name)
        and len(name) <= _OPENAI_FUNCTION_NAME_MAX
    ):
        return name
    sanitized = _OPENAI_FUNCTION_NAME_INVALID_RE.sub('_', name).strip('_')
    sanitized = re.sub(r'_+', '_', sanitized)
    if not sanitized:
        sanitized = 'tool'
    return sanitized[:_OPENAI_FUNCTION_NAME_MAX]


def schema_description(label, description):
    """Prefix the model-facing description with the human label when useful."""
    label = (label or '').strip()
    description = (description or '').strip()
    if label and description:
        if description.startswith(label):
            return description
        return '%s. %s' % (label, description)
    return label or description


def ai_tool(
    name,
    description,
    input_schema,
    output_schema=None,
    category='python',
    required_groups=None,
    rate_limit=30,
    timeout=15,
    label='',
):
    """Register a method as a pre-declared AI tool. Arbitrary code is forbidden."""

    def decorator(method):
        metadata = {
            'name': name,
            'label': label or '',
            'description': description,
            'category': category,
            'tool_type': 'python',
            'input_schema': input_schema,
            'output_schema': output_schema or {'type': 'object'},
            'required_groups': required_groups or [],
            'rate_limit': rate_limit,
            'timeout': timeout,
            'read_only': True,
        }
        if not name or not description or not input_schema:
            raise ValueError('ai_tool requires name, description and input_schema')
        method._ai_tool_metadata = metadata
        AI_TOOL_REGISTRY[name] = (method.__name__, metadata)
        return method

    return decorator


def validate_tool_schema(params, schema):
    errors = []
    _validate_value(params, schema or {}, errors, '$')
    return (not errors, errors)


def _schema_error(path, message):
    return '%s %s' % (path, message)


def _validate_value(value, schema, errors, path):
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
                        '%s.%s' % (path, key), 'is not allowed here'))
        for key, sub_schema in (schema.get('properties') or {}).items():
            if key in value:
                _validate_value(
                    value[key], sub_schema, errors, '%s.%s' % (path, key))
        for key in schema.get('required') or []:
            if key not in value:
                errors.append(_schema_error('%s.%s' % (path, key), 'is required'))
    elif expected == 'array':
        if not isinstance(value, list):
            errors.append(_schema_error(path, 'must be an array'))
            return
        item_schema = schema.get('items')
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_value(
                    item, item_schema, errors, '%s[%s]' % (path, index))
    else:
        if expected == 'string' and not isinstance(value, str):
            errors.append(_schema_error(path, 'must be a string'))
        elif expected == 'integer' and not isinstance(value, int):
            errors.append(_schema_error(path, 'must be an integer'))
        elif expected == 'number' and not isinstance(value, (int, float)):
            errors.append(_schema_error(path, 'must be a number'))
        elif expected == 'boolean' and not isinstance(value, bool):
            errors.append(_schema_error(path, 'must be a boolean'))
        if schema.get('enum') is not None and value not in schema['enum']:
            errors.append(_schema_error(path, 'must be one of %s' % schema['enum']))


def extract_tool_calls(content):
    if not content:
        return []
    calls = []
    for match in _FENCE_RE.finditer(str(content)):
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
    if not content:
        return ''
    return _FENCE_RE.sub('', str(content)).strip()


class AiTool(models.Model):
    _name = 'ai.tool'
    _description = 'AI Tool'
    _order = 'tool_type, label, name'
    _rec_names_search = ['label', 'name']
    _BUILTIN_WRITABLE = frozenset({'label'})
    _BUILTIN_LABELS = {
        'generic.search_read': 'Search records',
        'generic.search_count': 'Count records',
        'generic.group_by': 'Group records',
    }

    name = fields.Char(
        string='Code', required=True,
        help='Technical identifier sent to the model. Prefer letters, '
             'digits, underscore and hyphen.')
    label = fields.Char(
        string='Label', translate=True,
        help='Display name shown in lists, agent tools and chat cards.')
    description = fields.Text(string='Description', required=True)
    tool_type = fields.Selection([
        ('python', 'Python Function'),
        ('orm', 'Odoo ORM Action'),
        ('http', 'HTTP Endpoint'),
    ], string='Type', required=True, default='python')
    category = fields.Char(string='Category', default='generic')
    input_schema = fields.Json(string='Input JSON Schema', default=dict)
    output_schema = fields.Json(string='Output JSON Schema', default=dict)
    required_groups = fields.Char(
        string='Required Groups',
        help='Comma-separated XML IDs, e.g. base.group_user')
    is_active = fields.Boolean(string='Active', default=True)
    read_only = fields.Boolean(string='Read Only', default=True)
    rate_limit = fields.Integer(string='Rate Limit / minute', default=30)
    timeout = fields.Integer(string='Timeout (seconds)', default=15)
    # ORM tools
    orm_model = fields.Char(string='ORM Model')
    orm_method = fields.Selection([
        ('search', 'search'),
        ('read', 'read'),
        ('write', 'write'),
        ('create', 'create'),
    ], string='ORM Method')
    # HTTP tools
    http_method = fields.Selection([
        ('GET', 'GET'),
        ('POST', 'POST'),
        ('PUT', 'PUT'),
        ('PATCH', 'PATCH'),
    ], string='HTTP Method', default='POST')
    http_url = fields.Char(string='HTTP URL')
    http_headers = fields.Json(string='HTTP Headers', default=dict)
    is_builtin = fields.Boolean(
        string='Built-in', default=False, copy=False,
        help='Registered from Python with @ai_tool. Code and behaviour '
             'cannot be changed. The label can be edited.')

    _name_uniq = models.Constraint(
        'UNIQUE(name)',
        'The tool name must be unique.')

    @api.depends('label', 'name')
    @api.depends_context('lang')
    def _compute_display_name(self):
        for tool in self:
            tool.display_name = tool._tool_label()

    def _tool_label(self):
        """Human-facing name: translated builtin default, custom label, or code."""
        self.ensure_one()
        defaults = {
            'generic.search_read': _('Search records'),
            'generic.search_count': _('Count records'),
            'generic.group_by': _('Group records'),
        }
        default = defaults.get(self.name)
        text = (self.label or '').strip()
        if default and (not text or text == self._BUILTIN_LABELS.get(self.name)):
            return default
        return text or self.name

    def write(self, vals):
        if (
            self.filtered('is_builtin')
            and vals
            and not self.env.context.get('ai_tool_sync')
        ):
            if set(vals) - self._BUILTIN_WRITABLE:
                raise UserError(_('Built-in tools cannot be edited or deleted.'))
        return super().write(vals)

    def unlink(self):
        if self.filtered('is_builtin') and not self.env.context.get('ai_tool_sync'):
            raise UserError(_('Built-in tools cannot be edited or deleted.'))
        return super().unlink()

    def _register_hook(self):
        super()._register_hook()
        try:
            if 'ai.tool' in self.env.registry.models:
                self._sync_registry()
        except Exception:  # noqa: BLE001
            _logger.exception('ai_base tool registry sync failed')

    @api.model
    def _sync_registry(self):
        method_owner = {}
        for model in self.env.registry.models.values():
            for method_name in dir(model):
                if method_name.startswith('_ai_'):
                    method_owner.setdefault(method_name, model._name)
        normalized = {}
        for name, entry in AI_TOOL_REGISTRY.items():
            if len(entry) == 2:
                method_name, metadata = entry
                normalized[name] = (
                    method_owner.get(method_name, ''), method_name, metadata)
            else:
                normalized[name] = entry
        AI_TOOL_REGISTRY.update(normalized)
        existing = {tool.name: tool for tool in self.search([])}
        for name, (model_name, method_name, metadata) in AI_TOOL_REGISTRY.items():
            vals = {
                'description': metadata['description'],
                'tool_type': 'python',
                'category': metadata.get('category') or 'python',
                'input_schema': metadata['input_schema'],
                'output_schema': metadata.get('output_schema') or {},
                'required_groups': ','.join(metadata.get('required_groups') or []),
                'read_only': metadata.get('read_only', True),
                'is_builtin': True,
            }
            default_label = (
                metadata.get('label') or self._BUILTIN_LABELS.get(name) or '')
            if name in existing:
                current = existing[name]
                if default_label and not (current.label or '').strip():
                    vals['label'] = default_label
                existing[name].with_context(ai_tool_sync=True).write(vals)
            else:
                self.create(dict(
                    vals, name=name, label=default_label, is_active=True,
                    rate_limit=metadata.get('rate_limit') or 30,
                    timeout=metadata.get('timeout') or 15,
                ))

    @api.model
    def action_get_manifest_for_user(self, session=None):
        """ACL-filtered tool list. ``session`` lets ``ai_agent`` narrow by agent."""
        tools = self.search([('is_active', '=', True)])
        allowed = [tool for tool in tools if self._check_permissions(tool)]
        return [{
            'name': tool.name,
            'label': tool._tool_label(),
            'description': tool.description,
            'input_schema': tool.input_schema or {},
            'tool_type': tool.tool_type,
            'read_only': tool.read_only,
        } for tool in allowed]

    @api.model
    def _openai_name_map(self, manifest):
        """Map OpenAI function names back to internal ``ai.tool`` names."""
        used = set()
        mapping = {}
        for tool in manifest or []:
            internal = tool.get('name') or ''
            base = openai_function_name(internal)
            api_name = base
            index = 2
            while api_name in used:
                suffix = '_%s' % index
                api_name = '%s%s' % (
                    base[:_OPENAI_FUNCTION_NAME_MAX - len(suffix)], suffix)
                index += 1
            used.add(api_name)
            mapping[api_name] = internal
        return mapping

    @api.model
    def _function_schemas(self, manifest=None):
        manifest = manifest if manifest is not None \
            else self.action_get_manifest_for_user(session=None)
        name_map = self._openai_name_map(manifest)
        internal_to_api = {
            internal: api_name for api_name, internal in name_map.items()
        }
        schemas = []
        for tool in manifest:
            input_schema = tool.get('input_schema') or {}
            if not isinstance(input_schema, dict):
                input_schema = {'type': 'object', 'properties': {}}
            if input_schema.get('type') != 'object':
                input_schema = dict(input_schema, type='object')
            schemas.append({
                'type': 'function',
                'function': {
                    'name': internal_to_api.get(
                        tool['name'], openai_function_name(tool['name'])),
                    'description': schema_description(
                        tool.get('label'), tool.get('description')),
                    'parameters': input_schema,
                },
            })
        return schemas

    @api.model
    def action_invoke_tool(self, tool_name, params=None, context=None):
        started = time.time()
        params = params or {}
        context = context or {}
        tool = self.sudo().search(
            [('name', '=', tool_name), ('is_active', '=', True)], limit=1)
        if not tool:
            return self._tool_error(
                404, _('Tool "%s" is not registered.') % tool_name,
                started, tool_name, params)
        if not self._check_permissions(tool):
            return self._tool_error(
                421, _('You do not have permission to call tool "%s".') % tool_name,
                started, tool_name, params)
        if self._is_rate_limited(tool):
            return self._tool_error(
                429, _('Tool "%s" was called too frequently.') % tool_name,
                started, tool_name, params)
        ok, errors = validate_tool_schema(params, tool.input_schema or {})
        if not ok:
            return self._tool_error(
                400, _('Invalid tool parameters: %s') % '; '.join(errors),
                started, tool_name, params)
        try:
            result = self._execute_tool(tool, params, context)
        except (AccessError, UserError) as exc:
            result = self._tool_error(
                403, str(exc), started, tool_name, params)
        except Exception as exc:  # noqa: BLE001
            _logger.exception('ai_base tool %s failed', tool_name)
            result = self._tool_error(
                500, _('Tool "%s" failed: %s') % (tool_name, exc),
                started, tool_name, params)
        self._log_call(tool, params, result, started)
        return result

    def _is_rate_limited(self, tool):
        limit = tool.rate_limit or 30
        if limit <= 0:
            return False
        since = fields.Datetime.now() - timedelta(seconds=60)
        count = self.env['ai.request.log'].sudo().search_count([
            ('request_type', '=', 'tool'),
            ('tool_name', '=', tool.name),
            ('user_id', '=', self.env.user.id),
            ('create_date', '>=', since),
        ])
        return count >= limit

    def _check_permissions(self, tool):
        groups = [
            part.strip()
            for part in (tool.required_groups or '').split(',')
            if part.strip()
        ]
        if groups and not any(self.env.user.has_group(g) for g in groups):
            return False
        return True

    def _execute_tool(self, tool, params, context):
        if tool.tool_type == 'orm':
            return self._execute_orm(tool, params)
        if tool.tool_type == 'http':
            return self._execute_http(tool, params)
        return self._execute_python(tool, params, context)

    def _execute_python(self, tool, params, context):
        entry = AI_TOOL_REGISTRY.get(tool.name)
        if not entry:
            return self._tool_error(
                404, _('Tool "%s" has no executable implementation.') % tool.name,
                time.time(), tool.name, params)
        if len(entry) == 2:
            method_name, metadata = entry
            model_name = ''
        else:
            model_name, method_name, metadata = entry
        if not model_name:
            model_name = self._resolve_model_for_method(method_name)
            if not model_name:
                return self._tool_error(
                    500, _('Tool "%s" has no resolvable model.') % tool.name,
                    time.time(), tool.name, params)
            AI_TOOL_REGISTRY[tool.name] = (model_name, method_name, metadata)
        method = getattr(self.env[model_name], method_name, None)
        if method is None:
            return self._tool_error(
                500, _('Tool "%s" has no callable implementation.') % tool.name,
                time.time(), tool.name, params)
        result = method(params, context)
        if not isinstance(result, dict):
            return self._tool_error(
                500, _('Tool "%s" returned an invalid result.') % tool.name,
                time.time(), tool.name, params)
        result.setdefault('status', 'success')
        result.setdefault('message', '')
        return result

    def _safe_domain(self, domain):
        if domain is None:
            return []
        if not isinstance(domain, list):
            raise UserError(_('The domain must be a list of conditions.'))
        for condition in domain:
            if not isinstance(condition, (list, tuple)) or len(condition) != 3:
                raise UserError(_('Each domain condition must be a 3-element tuple.'))
            field, operator, _value = condition
            if not isinstance(field, str) or not isinstance(operator, str):
                raise UserError(_('Invalid domain condition.'))
            if operator not in (
                    '=', '!=', '>', '>=', '<', '<=', 'like', 'ilike',
                    'not like', 'not ilike', 'in', 'not in', 'child_of',
                    'parent_of'):
                raise UserError(_('Unsupported domain operator "%s".') % operator)
        return domain

    def _clean_fields(self, model, fields_list):
        available = set(model._fields)
        cleaned = []
        for field_name in fields_list or []:
            if not isinstance(field_name, str) or field_name not in available:
                continue
            if field_name in _SENSITIVE_FIELDS:
                continue
            cleaned.append(field_name)
        return cleaned

    def _execute_orm(self, tool, params):
        model_name = tool.orm_model or params.get('model')
        if not model_name or model_name not in self.env:
            raise UserError(_('Unknown model "%s".') % model_name)
        model = self.env[model_name]
        if model._abstract or model._transient:
            raise UserError(_('Abstract or transient models cannot be queried.'))
        method = tool.orm_method or params.get('method') or 'search'
        if method in ('write', 'create') and tool.read_only:
            raise UserError(_('Tool "%s" is read-only.') % tool.name)
        domain = self._safe_domain(params.get('domain') or [])
        fields_list = self._clean_fields(model, params.get('fields') or ['id', 'name'])
        limit = max(1, min(int(params.get('limit') or 80), 200))
        if method == 'search':
            records = model.search(domain, limit=limit, offset=int(params.get('offset') or 0))
            return {
                'status': 'success',
                'message': _('Found %s records.') % len(records),
                'data': {'records': records.read(fields_list), 'count': len(records)},
            }
        if method == 'read':
            record_ids = params.get('ids') or []
            records = model.browse(record_ids).exists()
            return {
                'status': 'success',
                'message': _('Read %s records.') % len(records),
                'data': {'records': records.read(fields_list)},
            }
        if method == 'write':
            records = model.browse(params.get('ids') or []).exists()
            values = params.get('values') or {}
            for key in list(values):
                if key in _SENSITIVE_FIELDS:
                    values.pop(key)
            records.write(values)
            return {
                'status': 'success',
                'message': _('Updated %s records.') % len(records),
                'data': {'ids': records.ids},
            }
        if method == 'create':
            values = params.get('values') or {}
            for key in list(values):
                if key in _SENSITIVE_FIELDS:
                    values.pop(key)
            record = model.create(values)
            return {
                'status': 'success',
                'message': _('Created record %s.') % record.id,
                'data': {'id': record.id},
            }
        raise UserError(_('Unsupported ORM method "%s".') % method)

    def _execute_http(self, tool, params):
        if not tool.http_url:
            raise UserError(_('HTTP tool "%s" has no URL.') % tool.name)
        headers = dict(tool.http_headers or {})
        method = tool.http_method or 'POST'
        timeout = tool.timeout or 15
        if method == 'GET':
            response = requests.get(
                tool.http_url, params=params, headers=headers, timeout=timeout)
        else:
            response = requests.request(
                method, tool.http_url, json=params, headers=headers, timeout=timeout)
        text = response.text[:4000]
        try:
            payload = response.json()
        except ValueError:
            payload = {'text': text}
        if response.status_code >= 400:
            return {
                'status': 'error',
                'code': response.status_code,
                'message': text[:500],
                'data': payload,
            }
        return {
            'status': 'success',
            'message': _('HTTP %s') % response.status_code,
            'data': payload,
        }

    @api.model
    def _resolve_model_for_method(self, method_name):
        for model in self.env.registry.models.values():
            if method_name in dir(model):
                return model._name
        return ''

    def _tool_error(self, code, message, started, tool_name, params):
        return {
            'status': 'error',
            'code': code,
            'message': message,
            'data': {},
            'execution_time_ms': int((time.time() - started) * 1000),
        }

    def _log_call(self, tool, params, result, started):
        self.env['ai.request.log'].sudo().create({
            'request_type': 'tool',
            'tool_name': tool.name,
            'user_id': self.env.user.id,
            'company_id': self.env.company.id,
            'latency_ms': int((time.time() - started) * 1000),
            'status': 'success' if result.get('status') == 'success' else 'error',
            'error_message': result.get('message') if result.get('status') == 'error' else False,
            'input_summary': json.dumps(params, ensure_ascii=False)[:2000],
            'output_summary': json.dumps(result, ensure_ascii=False)[:2000],
            'tool_calls': json.dumps([{
                'name': tool.name,
                'params': params,
                'result_status': result.get('status'),
            }], ensure_ascii=False),
        })


class AiGenericTools(models.AbstractModel):
    _name = 'ai.generic.tools'
    _description = 'AI Generic Read-Only Tools'

    def _tool_fail(self, code, message):
        return {'status': 'error', 'code': code, 'message': message, 'data': {}}

    @ai_tool(
        name='generic.search_read',
        label='Search records',
        description='Search records of any Odoo model and return the requested fields.',
        input_schema={
            'type': 'object',
            'properties': {
                'model': {'type': 'string'},
                'domain': {'type': 'array'},
                'fields': {'type': 'array', 'items': {'type': 'string'}},
                'limit': {'type': 'integer'},
                'offset': {'type': 'integer'},
                'order': {'type': 'string'},
            },
            'required': ['model'],
            'additionalProperties': False,
        },
        required_groups=['base.group_user'],
    )
    def _ai_search_read(self, params, context=None):
        return self.env['ai.tool']._execute_orm(
            self.env['ai.tool'].new({
                'name': 'generic.search_read',
                'orm_model': params.get('model'),
                'orm_method': 'search',
                'read_only': True,
            }),
            params,
        )

    @ai_tool(
        name='generic.search_count',
        label='Count records',
        description='Count records of any Odoo model matching a domain.',
        input_schema={
            'type': 'object',
            'properties': {
                'model': {'type': 'string'},
                'domain': {'type': 'array'},
            },
            'required': ['model'],
            'additionalProperties': False,
        },
        required_groups=['base.group_user'],
    )
    def _ai_search_count(self, params, context=None):
        model_name = params.get('model')
        if not model_name or model_name not in self.env:
            return self._tool_fail(404, _('Model "%s" does not exist.') % model_name)
        try:
            domain = self.env['ai.tool']._safe_domain(params.get('domain') or [])
            count = self.env[model_name].search_count(domain)
        except UserError as exc:
            return self._tool_fail(400, str(exc))
        return {
            'status': 'success',
            'message': _('Counted %s records.') % count,
            'data': {'count': count},
        }

    @ai_tool(
        name='generic.group_by',
        label='Group records',
        description=(
            'Group records of any Odoo model by a field and compute '
            'aggregates, such as sales orders grouped by salesperson or '
            'partners counted by country. Use this instead of search_read '
            'when the user wants totals per group. Provide the model name, '
            'the groupby field and aggregate expressions like '
            '"amount_total:sum" or "id:count". Results respect the current '
            'user permissions and record rules.'
        ),
        input_schema={
            'type': 'object',
            'properties': {
                'model': {
                    'type': 'string',
                    'description': 'Technical name of the Odoo model, e.g. sale.order.',
                },
                'groupby': {
                    'type': 'string',
                    'description': 'Field to group by, e.g. user_id or state.',
                },
                'aggregates': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Expressions such as ["id:count", "amount_total:sum"].',
                },
                'domain': {'type': 'array'},
                'limit': {'type': 'integer'},
            },
            'required': ['model', 'groupby', 'aggregates'],
            'additionalProperties': False,
        },
        required_groups=['base.group_user'],
    )
    def _ai_group_by(self, params, context=None):
        model_name = params.get('model')
        if not model_name or model_name not in self.env:
            return self._tool_fail(
                404, _('Model "%s" does not exist.') % model_name)
        model = self.env[model_name]
        if model._abstract or model._transient:
            return self._tool_fail(
                400, _('Abstract or transient models cannot be queried.'))
        groupby = params.get('groupby')
        if not isinstance(groupby, str) or groupby not in model._fields:
            return self._tool_fail(
                400, _('The groupby field "%s" does not exist on model "%s".')
                % (groupby, model_name))
        if groupby in _SENSITIVE_FIELDS:
            return self._tool_fail(
                400, _('Cannot group or aggregate sensitive field "%s".')
                % groupby)
        aggregates = params.get('aggregates') or []
        validated = []
        allowed = (
            'sum', 'avg', 'min', 'max', 'count',
            'count_distinct', 'bool_and', 'bool_or',
        )
        for expression in aggregates:
            if not isinstance(expression, str) or ':' not in expression:
                return self._tool_fail(
                    400, _('Invalid aggregate expression "%s", expected '
                           '"field:aggregator".') % expression)
            field_name, aggregator = expression.split(':', 1)
            if field_name not in model._fields:
                return self._tool_fail(
                    400, _('The aggregate field "%s" does not exist on model '
                           '"%s".') % (field_name, model_name))
            if field_name in _SENSITIVE_FIELDS:
                return self._tool_fail(
                    400, _('Cannot group or aggregate sensitive field "%s".')
                    % field_name)
            if aggregator not in allowed:
                return self._tool_fail(
                    400, _('Unsupported aggregator "%s".') % aggregator)
            validated.append('%s:%s' % (field_name, aggregator))
        try:
            domain = self.env['ai.tool']._safe_domain(params.get('domain') or [])
            limit = max(1, min(int(params.get('limit') or 80), 200))
        except (TypeError, ValueError, UserError) as exc:
            return self._tool_fail(400, str(exc))
        try:
            rows = model._read_group(
                domain, [groupby], validated or ['id:count'], limit=limit)
        except AccessError as exc:
            return self._tool_fail(421, str(exc))
        except Exception as exc:  # noqa: BLE001
            return self._tool_fail(
                500, _('The grouping query failed: %s') % exc)
        groups = []
        specs = validated or ['id:count']
        for row in rows:
            entry = {groupby: self._plain_value(row[0])}
            for index, expression in enumerate(specs):
                entry[expression.replace(':', '_')] = self._plain_value(
                    row[index + 1])
            groups.append(entry)
        return {
            'status': 'success',
            'message': _('Grouped %s records into %s groups.') % (
                model.search_count(domain), len(groups)),
            'data': {'groups': groups},
        }

    def _plain_value(self, value):
        ids = getattr(value, 'ids', None)
        if ids is not None:
            return ids
        if hasattr(value, 'isoformat'):
            return value.isoformat()
        return value
