# -*- coding: utf-8 -*-
"""Whitelist of models the AI assistant may open in views, plus the search
view blueprint used by the NL open-view flow (P1-G8, design 3.2/3.3)."""

import json
import xml.etree.ElementTree as ET

from odoo import _, api, fields, models

from odoo.addons.hdai_base.models.hdai_tool import ai_tool
from odoo.addons.hdai_base.models.hdai_tools import (
    ToolError,
    resolve_domain,
)


class HdaiNlviewModel(models.Model):
    _name = 'hdai.nlview.model'
    _description = 'AI Open View Model'
    _order = 'sequence, id'

    model_id = fields.Many2one(
        'ir.model', string='Model', required=True, ondelete='cascade',
        help='Model that the AI may open in a view from a natural language '
             'question. Users still need their normal read access.')
    name = fields.Char(
        string='Name', related='model_id.name', readonly=True)
    model = fields.Char(
        string='Technical Name', related='model_id.model', readonly=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)

    _VIEW_TYPES = ('list', 'kanban', 'pivot', 'graph')
    _SEARCHABLE_TYPES = (
        'char', 'text', 'selection', 'many2one', 'integer', 'float',
        'monetary', 'boolean', 'date', 'datetime',
    )
    _MEASURE_TYPES = ('integer', 'float', 'monetary')

    # ------------------------------------------------------------------
    # Search view blueprint
    # ------------------------------------------------------------------

    @api.model
    def _search_blueprint(self, model_name):
        """Parse the model's search view into a plain-data blueprint:
        ``searchable_fields``, ``filters`` (name/string/domain) and
        ``groupbys``, plus ``measures`` (aggregatable numeric fields).
        Returns ``None`` when the model does not exist."""
        try:
            model = self.env[model_name]
        except KeyError:
            return None
        fields_info = model._fields
        searchable = [
            name for name, field in fields_info.items()
            if not name.startswith('_')
            and field.type in self._SEARCHABLE_TYPES
            and getattr(field, 'searchable', True)
        ]
        measures = [
            name for name, field in fields_info.items()
            if not name.startswith('_')
            and field.type in self._MEASURE_TYPES
            and getattr(field, 'store', True) is not False
        ]
        filters = []
        groupbys = []
        # The search view architecture is technical metadata; reading it
        # for the prompt must not depend on the caller's ir.ui.view ACL.
        view = self.env['ir.ui.view'].sudo().search(
            [('model', '=', model_name), ('type', '=', 'search')],
            limit=1)
        if view and view.arch:
            try:
                root = ET.fromstring(view.arch)
            except ET.ParseError:
                root = None
            if root is not None:
                for element in root.iter('filter'):
                    domain = (element.get('domain') or '').strip()
                    name = element.get('name') or ''
                    if domain and name:
                        filters.append({
                            'name': name,
                            'string': element.get('string') or name,
                            'domain': domain,
                        })
                for element in root.iter('groupby'):
                    name = element.get('name') or ''
                    if name and name in fields_info:
                        groupbys.append(name)
        return {
            'model': model_name,
            'description': model._description or model_name,
            'searchable_fields': searchable,
            'filters': filters,
            'groupbys': groupbys,
            'measures': measures,
        }

    @api.model
    def action_get_nlview_manifest(self):
        """Per-user manifest of whitelisted models the caller may open.

        Each entry carries the model name/description and its search view
        blueprint, used to instruct the model in the chat prompt (design
        3.2: inject the readable model CSV + search blueprint)."""
        manifest = []
        for whitelist in self.search([('active', '=', True)]):
            model_name = whitelist.model
            try:
                model = self.env[model_name]
                model.check_access('read')
            except Exception:  # noqa: BLE001
                continue
            blueprint = self._search_blueprint(model_name)
            if not blueprint:
                continue
            manifest.append(blueprint)
        return manifest

    @api.model
    def _nlview_prompt(self):
        """Compact CSV-style prompt text describing the models the current
        user may open, their searchable fields, filters and groupbys."""
        manifest = self.action_get_nlview_manifest()
        if not manifest:
            return ''
        lines = ['Models you may open in views (whitelisted):']
        for entry in manifest:
            parts = [
                'model=%s' % entry['model'],
                'label=%s' % (entry['description'] or entry['model']),
            ]
            if entry['searchable_fields']:
                parts.append('searchable=%s' % ','.join(
                    entry['searchable_fields'][:24]))
            if entry['filters']:
                parts.append('filters=%s' % ','.join(
                    filter_def['name'] for filter_def in
                    entry['filters'][:10]))
            if entry['groupbys']:
                parts.append('groupbys=%s' % ','.join(
                    entry['groupbys'][:12]))
            if entry['measures']:
                parts.append('measures=%s' % ','.join(
                    entry['measures'][:12]))
            lines.append('; '.join(parts))
        lines.append(
            'To open a view, call the open_view tool with the model, an '
            'optional domain, view_type (list/kanban/pivot/graph), optional '
            'group_by and measures. Only whitelisted models and plain '
            'single-field names (no dotted chains) are allowed.')
        return '\n'.join(lines)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def _allowed_model(self, model_name):
        whitelist = self.search([
            ('model', '=', model_name), ('active', '=', True)], limit=1)
        return bool(whitelist)

    def _plain_field(self, model, field_path):
        """Reject dotted field chains and unknown fields (design 3.2)."""
        if not isinstance(field_path, str) or '.' in field_path:
            raise ToolError(
                'invalid_parameter',
                _('Field path "%s" is not allowed: only plain field names '
                  'may be used.') % field_path)
        if field_path not in model._fields:
            raise ToolError(
                'invalid_parameter',
                _('Field "%s" does not exist on %s.') % (
                    field_path, model._description))
        return field_path

    def _validate_domain(self, env, model, domain):
        """Validate a domain; dotted paths are rejected for the NL view
        flow (only plain fields, matching the blueprint)."""
        if domain is None:
            return []
        if not isinstance(domain, list):
            raise ToolError(
                'invalid_parameter',
                _('The filter must be a list of conditions.'))
        for node in domain:
            if node in ('&', '|', '!'):
                continue
            if not isinstance(node, (tuple, list)) or len(node) != 3:
                raise ToolError(
                    'invalid_parameter',
                    _('Malformed filter condition.'))
            self._plain_field(model, node[0])
        return resolve_domain(env, model, domain)

    def _validate_group_measures(self, model, group_by, measures):
        group_by = [self._plain_field(model, name) for name in (group_by or [])]
        measures = [self._plain_field(model, name) for name in (measures or [])]
        for name in measures:
            field = model._fields[name]
            if field.type not in self._MEASURE_TYPES:
                raise ToolError(
                    'invalid_measure',
                    _('Field "%s" is not a numeric measure.') % name)
        return group_by, measures

    # ------------------------------------------------------------------
    # open_view tool (read-only: opens a view, never writes)
    # ------------------------------------------------------------------

    @ai_tool(
        name='open_view',
        description=(
            'Open a whitelisted Odoo model in a view (list, kanban, pivot '
            'or graph) with an optional domain, grouping and measures. Use '
            'this tool when the user asks to open or look at a model, apply '
            'a filter, group by a field, or show a pivot/graph with '
            'measures. The view is opened read-only; the current user '
            'permissions apply.'),
        input_schema={
            'type': 'object',
            'properties': {
                'model': {
                    'type': 'string',
                    'description': 'Whitelisted model technical name.',
                },
                'view_type': {
                    'type': 'string',
                    'enum': ['list', 'kanban', 'pivot', 'graph'],
                    'description': 'View type to open (default list).',
                },
                'domain': {
                    'type': 'array',
                    'description': 'List of simple field/operator/value '
                                   'conditions (plain fields only).',
                },
                'group_by': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Fields to group by (plain fields only).',
                },
                'measures': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Numeric fields to show as measures in '
                                   'pivot/graph views.',
                },
                'label': {
                    'type': 'string',
                    'description': 'Optional action title.',
                },
            },
            'required': ['model'],
            'additionalProperties': False,
        },
        output_schema={
            'type': 'object',
            'properties': {
                'action': {'type': 'object'},
            },
            'required': ['action'],
        },
        category='generic',
        scope='global',
        required_permissions=['base.group_user'],
    )
    def _ai_open_view(self, params, context=None):
        """Validate and build the act_window for the NL open-view flow."""
        context = context or {}
        model_name = params.get('model')
        if not self._allowed_model(model_name):
            raise ToolError(
                'not_whitelisted',
                _('The model "%s" is not enabled for opening views.') % (
                    model_name),
                _('Ask an administrator to enable it under AI Assistant -> '
                  'Open View Models.'))
        try:
            model = self.env[model_name]
        except KeyError:
            raise ToolError(
                'model_missing',
                _('The model %s does not exist in this database.') % (
                    model_name))
        if model._transient or model._abstract:
            raise ToolError(
                'invalid_parameter',
                _('Transient or abstract models cannot be opened.'))
        try:
            model.check_access_rights('read')
        except Exception:  # noqa: BLE001
            raise ToolError(
                'no_read_access',
                _('You do not have read access to %s.') % model._description)
        view_type = params.get('view_type') or 'list'
        if view_type not in self._VIEW_TYPES:
            raise ToolError(
                'invalid_parameter',
                _('View type "%s" is not supported.') % view_type)
        domain = self._validate_domain(self.env, model, params.get('domain'))
        group_by, measures = self._validate_group_measures(
            model, params.get('group_by'), params.get('measures'))
        action = {
            'type': 'ir.actions.act_window',
            'name': (params.get('label') or '').strip()
            or model._description,
            'res_model': model_name,
            'view_mode': view_type,
            'views': [[False, view_type]],
            'domain': domain,
            'target': 'current',
            'context': {},
        }
        if group_by:
            action['context']['group_by'] = group_by
        if measures:
            action['context']['pivot_measures'] = measures
        # Audit (hdai_base action log, append-only).
        self.env['hdai.action.log'].create({
            'user_id': self.env.user.id,
            'session_id': context.get('session_id') or False,
            'action': 'open_view',
            'query': (params.get('label') or '').strip(),
            'model_name': model_name,
            'result': json.dumps({
                'view_type': view_type,
                'domain': domain,
                'group_by': group_by,
                'measures': measures,
            }, ensure_ascii=False)[:1000],
        })
        # Bus closed loop: notify any open chat client that the requested
        # view parameters should be applied, tagged with the session id so
        # concurrent sessions never apply each other's requests.
        if context.get('session_id'):
            self.env['bus.bus']._sendone(
                self.env.user.partner_id, 'hdai_base/nlview', {
                    'session_id': context['session_id'],
                    'action': action,
                })
        return {
            'status': 'success',
            'message': _('Opened %s (%s).') % (
                model._description, view_type),
            'data': {},
            'action': action,
        }
