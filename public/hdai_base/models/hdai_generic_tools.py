# -*- coding: utf-8 -*-
"""Generic read-only AI tools (HD-AI-PLAN-003 P1-G3).

All tools strictly follow HD-AI-STD-001:
- read-only (no create/write/unlink anywhere in this module);
- permission-aware (the ORM enforces ACL and record rules);
- paginated results with total_count;
- safe domain construction from untrusted input;
- audit logging performed by the hdai.tool framework.
"""

from odoo import _, models

from odoo.addons.hdai_base.models.hdai_tool import ai_tool


class HdaiGenericTools(models.AbstractModel):
    _name = 'hdai.generic.tools'
    _description = 'HD AI Generic Read-Only Tools'

    _SENSITIVE_FIELDS = (
        'password', 'api_key', 'credit_card', 'bank_account',
        'id_number', 'secret',
    )
    _DEFAULT_LIMIT = 100
    _MAX_LIMIT = 500

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_model(self, model_name):
        """Return the model technical name when it exists and is a regular
        (non-abstract, non-transient) model, else ``False``."""
        if not model_name or not isinstance(model_name, str):
            return False
        try:
            model = self.env[model_name]
        except KeyError:
            return False
        if model._abstract or model._transient:
            return False
        return model_name

    def _get_model(self, model_name):
        return self.env[model_name]

    def _safe_domain(self, domain):
        """Validate that a domain is a plain list of leaf conditions."""
        if domain is None:
            return []
        if not isinstance(domain, list):
            raise ValueError(_('The domain must be a list of conditions.'))
        for condition in domain:
            if not isinstance(condition, (list, tuple)) or len(condition) != 3:
                raise ValueError(
                    _('Each domain condition must be a 3-element tuple.'))
            field, operator, _value = condition
            if not isinstance(field, str) or not isinstance(operator, str):
                raise ValueError(_('Invalid domain condition.'))
            if operator not in (
                    '=', '!=', '>', '>=', '<', '<=', 'like', 'ilike',
                    'not like', 'not ilike', 'in', 'not in', 'child_of',
                    'parent_of'):
                raise ValueError(_('Unsupported domain operator "%s".') % operator)
        return domain

    def _clean_fields(self, model, fields_list):
        """Keep only existing, non-sensitive fields."""
        available = set(model._fields)
        cleaned = []
        for field_name in fields_list or []:
            if not isinstance(field_name, str) or field_name not in available:
                continue
            if field_name in self._SENSITIVE_FIELDS:
                continue
            cleaned.append(field_name)
        return cleaned

    def _sanitize_records(self, records, fields_list):
        """Return records as plain dicts with only the requested fields."""
        result = []
        for record in records:
            values = {}
            for field_name in fields_list:
                if field_name in self._SENSITIVE_FIELDS:
                    continue
                try:
                    values[field_name] = record[field_name]
                except Exception:  # noqa: BLE001
                    continue
            result.append(values)
        return result

    def _normalize_pagination(self, limit, offset):
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = self._DEFAULT_LIMIT
        limit = max(1, min(limit, self._MAX_LIMIT))
        try:
            offset = max(0, int(offset))
        except (TypeError, ValueError):
            offset = 0
        return limit, offset

    # ------------------------------------------------------------------
    # search_read
    # ------------------------------------------------------------------

    @ai_tool(
        name='generic.search_read',
        description=(
            'Search records of any Odoo model and return the requested '
            'fields. Use this tool to answer questions about business data '
            'such as customers, products, sales orders, invoices and other '
            'records. Provide the model name (e.g. res.partner, '
            'product.product, sale.order), an optional domain of simple '
            'field/operator/value tuples, the fields to return and the '
            'pagination window. Results are subject to the current user '
            'permissions and record rules.'),
        input_schema={
            'type': 'object',
            'properties': {
                'model': {
                    'type': 'string',
                    'description': 'Technical name of the Odoo model, e.g. res.partner.',
                },
                'domain': {
                    'type': 'array',
                    'items': {
                        'type': 'array',
                        'items': [{'type': 'string'}, {'type': 'string'}, {}],
                        'minItems': 3,
                        'maxItems': 3,
                    },
                    'description': 'List of simple conditions, e.g. [["name", "ilike", "acme"]].',
                },
                'fields': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Field names to return; sensitive fields are always removed.',
                },
                'limit': {
                    'type': 'integer',
                    'minimum': 1,
                    'maximum': 500,
                    'description': 'Maximum number of records (default 100, max 500).',
                },
                'offset': {
                    'type': 'integer',
                    'minimum': 0,
                    'description': 'Records to skip for pagination.',
                },
                'order': {
                    'type': 'string',
                    'description': 'Optional ordering expression, e.g. "id desc".',
                },
            },
            'required': ['model'],
            'additionalProperties': False,
        },
        output_schema={
            'type': 'object',
            'properties': {
                'records': {'type': 'array'},
                'total_count': {'type': 'integer'},
                'offset': {'type': 'integer'},
                'limit': {'type': 'integer'},
                'source_type': {'const': 'database'},
            },
        },
        category='generic',
        scope='global',
        required_permissions=['base.group_user'],
    )
    def _ai_search_read(self, params, context=None):
        model_name = self._resolve_model(params.get('model'))
        if not model_name:
            return self._tool_fail(
                404, _('Model "%s" does not exist or is not searchable.')
                % params.get('model'))
        model = self._get_model(model_name)
        try:
            domain = self._safe_domain(params.get('domain') or [])
            result = self._run_search_read(model, domain, params)
            return result
        except ValueError as exc:
            return self._tool_fail(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            return self._tool_fail(500, _('Unexpected error: %s') % exc)

    def _run_search_read(self, model, domain, params):
        fields_list = self._clean_fields(model, params.get('fields') or ['id', 'name'])
        limit, offset = self._normalize_pagination(
            params.get('limit'), params.get('offset'))
        order = params.get('order') or 'id'
        try:
            records = model.search(
                domain, limit=limit, offset=offset, order=order)
            total = model.search_count(domain)
        except Exception as exc:  # noqa: BLE001
            return self._tool_fail(
                500, _('The query failed: %s') % exc)
        return {
            'status': 'success',
            'message': _('Found %s matching records.') % total,
            'data': {
                'records': self._sanitize_records(records, fields_list),
                'total_count': total,
                'offset': offset,
                'limit': limit,
                'source_type': 'database',
            },
        }

    # ------------------------------------------------------------------
    # search_count
    # ------------------------------------------------------------------

    @ai_tool(
        name='generic.search_count',
        description=(
            'Count the records of any Odoo model matching a domain. Use this '
            'tool when the answer only needs a number, such as how many '
            'customers, open sales orders or draft invoices exist. Provide '
            'the model name and an optional domain of simple '
            'field/operator/value tuples. Results respect the current user '
            'permissions and record rules.'),
        input_schema={
            'type': 'object',
            'properties': {
                'model': {
                    'type': 'string',
                    'description': 'Technical name of the Odoo model, e.g. sale.order.',
                },
                'domain': {
                    'type': 'array',
                    'items': {
                        'type': 'array',
                        'items': [{'type': 'string'}, {'type': 'string'}, {}],
                        'minItems': 3,
                        'maxItems': 3,
                    },
                    'description': 'List of simple conditions.',
                },
            },
            'required': ['model'],
            'additionalProperties': False,
        },
        output_schema={
            'type': 'object',
            'properties': {
                'count': {'type': 'integer'},
                'source_type': {'const': 'database'},
            },
        },
        category='generic',
        scope='global',
        required_permissions=['base.group_user'],
    )
    def _ai_search_count(self, params, context=None):
        model_name = self._resolve_model(params.get('model'))
        if not model_name:
            return self._tool_fail(
                404, _('Model "%s" does not exist or is not searchable.')
                % params.get('model'))
        model = self._get_model(model_name)
        try:
            domain = self._safe_domain(params.get('domain') or [])
        except ValueError as exc:
            return self._tool_fail(400, str(exc))
        try:
            count = model.search_count(domain)
        except Exception as exc:  # noqa: BLE001
            return self._tool_fail(
                500, _('The query failed: %s') % exc)
        return {
            'status': 'success',
            'message': _('Counted %s records.') % count,
            'data': {
                'count': count,
                'source_type': 'database',
            },
        }

    # ------------------------------------------------------------------
    # group_by
    # ------------------------------------------------------------------

    @ai_tool(
        name='generic.group_by',
        description=(
            'Group records of any Odoo model by a field and compute '
            'aggregates, such as sales orders grouped by state, or partner '
            'counts grouped by country. Provide the model name, the groupby '
            'field and the aggregate expression with a field name, for '
            'example "amount_total:sum" or "id:count". Results respect the '
            'current user permissions and record rules.'),
        input_schema={
            'type': 'object',
            'properties': {
                'model': {
                    'type': 'string',
                    'description': 'Technical name of the Odoo model, e.g. sale.order.',
                },
                'groupby': {
                    'type': 'string',
                    'description': 'Field to group by, e.g. state.',
                },
                'aggregates': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Aggregate expressions, e.g. ["id:count", "amount_total:sum"].',
                },
                'domain': {
                    'type': 'array',
                    'items': {
                        'type': 'array',
                        'items': [{'type': 'string'}, {'type': 'string'}, {}],
                        'minItems': 3,
                        'maxItems': 3,
                    },
                    'description': 'List of simple conditions.',
                },
            },
            'required': ['model', 'groupby', 'aggregates'],
            'additionalProperties': False,
        },
        output_schema={
            'type': 'object',
            'properties': {
                'groups': {'type': 'array'},
                'source_type': {'const': 'database'},
            },
        },
        category='generic',
        scope='global',
        required_permissions=['base.group_user'],
    )
    def _ai_group_by(self, params, context=None):
        model_name = self._resolve_model(params.get('model'))
        if not model_name:
            return self._tool_fail(
                404, _('Model "%s" does not exist or is not searchable.')
                % params.get('model'))
        model = self._get_model(model_name)
        groupby = params.get('groupby')
        if not isinstance(groupby, str) or groupby not in model._fields:
            return self._tool_fail(
                400, _('The groupby field "%s" does not exist on model "%s".')
                % (groupby, params.get('model')))
        aggregates = params.get('aggregates') or []
        validated = []
        for expression in aggregates:
            if not isinstance(expression, str) or ':' not in expression:
                return self._tool_fail(
                    400, _('Invalid aggregate expression "%s", expected '
                           '"field:aggregator".') % expression)
            field_name, aggregator = expression.split(':', 1)
            if field_name not in model._fields:
                return self._tool_fail(
                    400, _('The aggregate field "%s" does not exist on model '
                           '"%s".') % (field_name, params.get('model')))
            if aggregator not in ('sum', 'avg', 'min', 'max', 'count',
                                  'count_distinct', 'bool_and', 'bool_or'):
                return self._tool_fail(
                    400, _('Unsupported aggregator "%s".') % aggregator)
            validated.append('%s:%s' % (field_name, aggregator))
        try:
            domain = self._safe_domain(params.get('domain') or [])
        except ValueError as exc:
            return self._tool_fail(400, str(exc))
        try:
            data = model._read_group(
                domain, [groupby], validated or ['id:count'])
        except Exception as exc:  # noqa: BLE001
            return self._tool_fail(
                500, _('The grouping query failed: %s') % exc)
        groups = []
        for row in data:
            entry = {groupby: self._plain_value(row[0])}
            for index, expression in enumerate(validated or ['id:count']):
                entry[expression.replace(':', '_')] = self._plain_value(
                    row[index + 1])
            groups.append(entry)
        return {
            'status': 'success',
            'message': _('Grouped %s records into %s groups.')
            % (model.search_count(domain), len(groups)),
            'data': {
                'groups': groups,
                'source_type': 'database',
            },
        }

    def _tool_fail(self, code, message):
        return {
            'status': 'error',
            'code': code,
            'message': message,
            'data': {},
        }

    def _plain_value(self, value):
        """Convert recordset values into plain JSON-serializable data."""
        ids = getattr(value, 'ids', None)
        if ids is not None:
            return ids
        return value
