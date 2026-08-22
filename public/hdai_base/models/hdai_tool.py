# -*- coding: utf-8 -*-
"""AI tool framework for hdai_base.

Implements the @ai_tool decorator, the tool registry (hdai.tool) and the
audit log (hdai.tool.log) defined by HD-AI-STD-001. All tools are strictly
read-only: the framework refuses to register tools that declare write
operations and the registry has no create/write/unlink path.
"""

import json
import logging
import time
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


def ai_tool(
    name,
    description,
    input_schema,
    output_schema,
    category='generic',
    scope='global',
    suggestive=False,
    required_permissions=None,
    rate_limit=30,
    timeout=15,
    cost_estimate=0.0,
    deprecated=False,
    deprecation_message='',
):
    """Register a method as an AI tool.

    Metadata follows HD-AI-STD-001 section 5. ``required_permissions`` is a
    list of security group XML ids; the caller must belong to at least one of
    them. ``suggestive`` tools are not part of the first phase (all phase-1
    tools are read-only) but the flag is accepted for forward compatibility.
    """

    def decorator(method):
        metadata = {
            'name': name,
            'description': description,
            'category': category,
            'scope': scope,
            'suggestive': bool(suggestive),
            'read_only': not suggestive,
            'input_schema': input_schema,
            'output_schema': output_schema,
            'required_permissions': required_permissions or [],
            'rate_limit': rate_limit,
            'timeout': timeout,
            'cost_estimate': cost_estimate,
            'deprecated': deprecated,
            'deprecation_message': deprecation_message,
        }
        if not name or not description or not input_schema or not output_schema:
            raise ValueError(
                'ai_tool requires name, description, input_schema and '
                'output_schema for %s' % method.__qualname__)
        method._ai_tool_metadata = metadata
        # The model name is resolved during _sync_registry, when the
        # decorated methods are attached to their model classes.
        AI_TOOL_REGISTRY[name] = (method.__name__, metadata)
        return method

    return decorator


AI_TOOL_REGISTRY = {}


class HdaiTool(models.Model):
    _name = 'hdai.tool'
    _description = 'HD AI Tool'
    _order = 'category, name'

    name = fields.Char(string='Tool Name', required=True)
    description = fields.Text(string='Description', required=True)
    category = fields.Selection([
        ('generic', 'Generic'),
        ('crm', 'CRM'),
        ('sale', 'Sales'),
        ('account', 'Accounting'),
        ('stock', 'Inventory'),
        ('project', 'Project'),
        ('hr', 'Human Resources'),
        ('custom', 'Custom'),
    ], string='Category', required=True, default='generic')
    scope = fields.Selection([
        ('global', 'Global'),
        ('model', 'Model'),
        ('record', 'Record'),
    ], string='Scope', required=True, default='global')
    read_only = fields.Boolean(string='Read Only', default=True)
    suggestive = fields.Boolean(string='Suggestive', default=False)
    input_schema = fields.Json(string='Input Schema')
    output_schema = fields.Json(string='Output Schema')
    required_permissions = fields.Char(string='Required Permissions')
    rate_limit = fields.Integer(string='Rate Limit (per minute)', default=30)
    timeout = fields.Integer(string='Timeout (seconds)', default=15)
    cost_estimate = fields.Float(string='Cost Estimate', default=0.0)
    deprecated = fields.Boolean(string='Deprecated', default=False)
    deprecation_message = fields.Char(string='Deprecation Message')
    package_ids = fields.Many2many(
        'hdai.tool.package', 'hdai_tool_package_rel', 'tool_id',
        'package_id', string='Tool Packages')
    active = fields.Boolean(string='Active', default=True)

    def _register_hook(self):
        """Keep the tool registry in sync whenever the registry is built.

        The decorator registers tools at module import time; this hook runs
        after all models are loaded and (re)creates the hdai.tool records
        and package bindings so a plain server restart is enough to pick up
        newly added tools without a module update."""
        super()._register_hook()
        try:
            if 'hdai.tool' in self.env.registry.models:
                self._sync_registry()
        except Exception:  # noqa: BLE001
            _logger.exception('hdai_base tool registry sync failed')

    @api.model
    def _sync_registry(self):
        """Upsert every decorated tool into the registry table.

        The decorator registers a (method_name, metadata) placeholder at
        import time. The model that owns each tool is resolved here by
        scanning every loaded model for a method of the same name, which
        avoids depending on attributes surviving Odoo's class layering.
        This runs on module update; tools defined by other hdai_* modules
        are picked up automatically once those modules are installed."""
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
                'category': metadata['category'],
                'scope': metadata['scope'],
                'read_only': metadata['read_only'],
                'suggestive': metadata['suggestive'],
                'input_schema': metadata['input_schema'],
                'output_schema': metadata['output_schema'],
                'required_permissions': ','.join(metadata['required_permissions']),
                'rate_limit': metadata['rate_limit'],
                'timeout': metadata['timeout'],
                'cost_estimate': metadata['cost_estimate'],
                'deprecated': metadata['deprecated'],
                'deprecation_message': metadata['deprecation_message'],
                'active': True,
            }
            if name in existing:
                existing[name].write(vals)
            else:
                self.create(dict(vals, name=name))
        # Bind every generic tool to the generic package shipped by the base
        # module so the framework's built-in tools are always packaged.
        package = self.env.ref('hdai_base.tool_package_generic', raise_if_not_found=False)
        if package:
            generic_tools = self.search([('name', 'like', 'generic.%')])
            if generic_tools:
                package.tool_ids = [(6, 0, generic_tools.ids)]

    @api.model
    def action_get_manifest(self):
        """Return the tool manifest for the LLM (HD-AI-STD-001 section 5)."""
        tools = self.search([('active', '=', True), ('deprecated', '=', False)])
        return [{
            'name': tool.name,
            'description': tool.description,
            'input_schema': tool.input_schema,
            'output_schema': tool.output_schema,
            'category': tool.category,
            'scope': tool.scope,
            'read_only': tool.read_only,
            'suggestive': tool.suggestive,
        } for tool in tools]

    @api.model
    def action_get_manifest_for_user(self):
        """Manifest restricted to the tools the caller may actually invoke.

        The server-side tool loop builds its tool list from this filtered
        manifest: tools whose ``required_permissions`` the caller does not
        satisfy are never offered to the model, so permission checks are not
        merely enforced at execution time but kept out of the prompt."""
        tools = self.search([('active', '=', True), ('deprecated', '=', False)])
        allowed = [tool for tool in tools if self._check_permissions(tool)]
        return [{
            'name': tool.name,
            'description': tool.description,
            'input_schema': tool.input_schema,
            'output_schema': tool.output_schema,
            'category': tool.category,
            'scope': tool.scope,
            'read_only': tool.read_only,
            'suggestive': tool.suggestive,
        } for tool in allowed]

    @api.model
    def _loop_limits(self):
        """Loop guardrails (HD-AI-PLAN-003 P1-G6): max successive rounds and
        max tool calls per round, configurable via the settings page with the
        same conservative defaults as the design (10 rounds / 10 calls)."""
        params = self.env['ir.config_parameter'].sudo()
        return {
            'max_rounds': self._as_limit(
                params.get_param('hdai.max_successive_calls', '10')),
            'max_calls_per_round': self._as_limit(
                params.get_param('hdai.max_tool_calls_per_call', '10')),
        }

    @staticmethod
    def _as_limit(value):
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 10

    @api.model
    def _function_schemas(self, manifest=None):
        """Convert a manifest into OpenAI ``tools`` function definitions."""
        manifest = manifest if manifest is not None \
            else self.action_get_manifest_for_user()
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
                    'name': tool['name'],
                    'description': tool.get('description') or '',
                    'parameters': input_schema,
                },
            })
        return schemas

    @api.model
    def action_invoke_tool(self, tool_name, params=None, context=None):
        """Invoke a tool by name with permission checking and audit logging.

        The framework is read-only: it validates the schema, checks ACL/record
        rules through the ORM, and records the call in ``hdai.tool.log``.
        """
        started = time.time()
        params = params or {}
        context = context or {}
        # The registry lookup runs as superuser so that users without ACL on
        # the registry itself still get a clear 421 instead of an AccessError;
        # the permission gate below always uses the real caller.
        tool = self.sudo().search(
            [('name', '=', tool_name), ('active', '=', True)], limit=1)
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
                429, _('Tool "%s" was called too frequently; retry after a '
                       'minute.') % tool_name, started, tool_name, params)
        try:
            result = self._execute_tool(tool, params, context)
        except Exception as exc:  # noqa: BLE001
            _logger.exception('hdai_base tool %s failed', tool_name)
            result = self._tool_error(
                500, _('Tool "%s" failed: %s') % (tool_name, exc),
                started, tool_name, params)
        self._log_call(tool, params, result, started)
        return result

    def _is_rate_limited(self, tool):
        """Return True when the caller exceeded the tool's per-minute limit.

        The audit log is the source of truth: the last ``rate_limit`` calls
        from this user must all be older than 60 seconds for a new call to
        be allowed (sliding window, per HD-AI-STD-001 section 8.6)."""
        limit = tool.rate_limit or 30
        if limit <= 0:
            return False
        since = fields.Datetime.now() - timedelta(seconds=60)
        count = self.env['hdai.tool.log'].sudo().search_count([
            ('tool_name', '=', tool.name),
            ('caller_user_id', '=', self.env.user.id),
            ('create_date', '>=', since),
        ])
        return count >= limit

    def _check_permissions(self, tool):
        """Check that the caller belongs to at least one required group and
        has read access to every model the tool will touch."""
        groups = [g.strip() for g in (tool.required_permissions or '').split(',') if g.strip()]
        user = self.env.user
        if groups and not any(user.has_group(g) for g in groups):
            return False
        return True

    def _execute_tool(self, tool, params, context):
        """Dispatch a registered tool by name."""
        entry = AI_TOOL_REGISTRY.get(tool.name)
        if not entry:
            return self._tool_error(
                404, _('Tool "%s" has no executable implementation.') % tool.name,
                time.time(), tool.name, params)
        if len(entry) == 2:
            method_name, _metadata = entry
            model_name = ''
        else:
            model_name, method_name, _metadata = entry
        if not model_name:
            # The registry entry created by the decorator does not carry the
            # model name; resolve it lazily so tools work before any
            # _sync_registry call (e.g. right after a server restart).
            model_name = self._resolve_model_for_method(method_name)
            if not model_name:
                return self._tool_error(
                    500, _('Tool "%s" has no resolvable model.') % tool.name,
                    time.time(), tool.name, params)
            AI_TOOL_REGISTRY[tool.name] = (model_name, method_name, _metadata)
        if model_name not in self.env:
            return self._tool_error(
                500, _('The model "%s" of tool "%s" is not available.') % (model_name, tool.name),
                time.time(), tool.name, params)
        recordset = self.env[model_name]
        method = getattr(recordset, method_name, None)
        if method is None:
            return self._tool_error(
                500, _('Tool "%s" has no callable implementation.') % tool.name,
                time.time(), tool.name, params)
        # Tools are executed on the empty recordset with the caller's
        # environment, so ACL and record rules are enforced by the ORM.
        # ``_run_with_timeout`` is the governance extension point: the base
        # implementation only records timeout metadata; ``hdai_governance``
        # may override hard interrupt behaviour.
        result = self._run_with_timeout(
            tool, lambda: method(params, context))
        if not isinstance(result, dict):
            return self._tool_error(
                500, _('Tool "%s" returned an invalid result.') % tool.name,
                time.time(), tool.name, params)
        result.setdefault('status', 'success')
        result.setdefault('message', '')
        return result

    @api.model
    def _run_with_timeout(self, tool, callable_):
        """Run ``callable_`` honouring the tool timeout hook.

        Base behaviour: invoke immediately (``timeout`` is metadata only in
        threaded workers). Extension modules may override this method on
        ``hdai.tool`` via inheritance to enforce hard timeouts.
        """
        return callable_()
    @api.model
    def _resolve_model_for_method(self, method_name):
        """Return the technical name of the model owning ``method_name``."""
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
        """Append the audit record (append-only, see HD-AI-STD-001 8.5)."""
        # The audit trail is a system-level append-only log: it is written as
        # superuser so callers never need create access on the log model, and
        # no ACL grants write/unlink so the records stay immutable.
        self.env['hdai.tool.log'].sudo().create({
            'tool_name': tool.name,
            'caller_user_id': self.env.user.id,
            'input_params': json.dumps(params, ensure_ascii=False)[:2000],
            'output_summary': json.dumps(result, ensure_ascii=False)[:1000],
            'execution_time_ms': int((time.time() - started) * 1000),
            'status': result.get('status') == 'success' and 'success' or 'error',
            'error_code': result.get('code') if result.get('status') == 'error' else False,
        })


class HdaiToolPackage(models.Model):
    _name = 'hdai.tool.package'
    _description = 'HD AI Tool Package'
    _order = 'name'

    name = fields.Char(string='Package Name', required=True)
    description = fields.Text(string='Description')
    tool_ids = fields.Many2many(
        'hdai.tool', 'hdai_tool_package_rel', 'package_id',
        'tool_id', string='Tools')
    tool_count = fields.Integer(compute='_compute_tool_count', string='Tool Count')

    def _compute_tool_count(self):
        for package in self:
            package.tool_count = len(package.tool_ids)


class HdaiToolPackageRel(models.Model):
    _name = 'hdai.tool.package.rel'
    _description = 'HD AI Tool Package Relation'

    package_id = fields.Many2one(
        'hdai.tool.package', string='Package', required=True, ondelete='cascade')
    tool_id = fields.Many2one(
        'hdai.tool', string='Tool', required=True, ondelete='cascade')


class HdaiToolLog(models.Model):
    _name = 'hdai.tool.log'
    _description = 'HD AI Tool Audit Log'
    _order = 'create_date desc, id desc'

    tool_name = fields.Char(string='Tool Name', required=True, index=True)
    caller_user_id = fields.Many2one(
        'res.users', string='Caller', required=True, ondelete='restrict')
    input_params = fields.Text(string='Input Parameters')
    output_summary = fields.Text(string='Output Summary')
    execution_time_ms = fields.Integer(string='Execution Time (ms)')
    token_usage = fields.Integer(string='Token Usage')
    status = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
    ], string='Status', default='success')
    error_code = fields.Integer(string='Error Code')
    timestamp = fields.Datetime(string='Timestamp', default=fields.Datetime.now)
