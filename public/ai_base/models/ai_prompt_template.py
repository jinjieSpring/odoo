# -*- coding: utf-8 -*-
import logging
from collections.abc import Mapping

from jinja2 import Environment, StrictUndefined, UndefinedError, TemplateError

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_JINJA = Environment(undefined=StrictUndefined, autoescape=False)


def _record_context(record):
    """Expose ORM record fields as a plain dict for template rendering."""
    values = {}
    if not record:
        return values
    record.ensure_one()
    values['record'] = record
    for name, field in record._fields.items():
        if name in ('id', 'display_name', 'name'):
            values[name] = record[name]
            continue
        if field.type in ('binary', 'html'):
            continue
        try:
            value = record[name]
        except Exception:  # noqa: BLE001
            continue
        if field.type == 'many2one':
            values[name] = value.display_name if value else ''
        elif field.type in ('one2many', 'many2many'):
            continue
        else:
            values[name] = value
    return values


class AiPromptTemplate(models.Model):
    _name = 'ai.prompt.template'
    _description = 'AI Prompt Template'
    _order = 'category, name'
    _check_company_auto = True

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(
        string='Key', required=True, index=True,
        help='Stable key used by business modules, e.g. sale.email.draft')
    description = fields.Text(string='Description')
    category = fields.Char(string='Category')
    system_prompt = fields.Text(string='System Prompt')
    user_template = fields.Text(
        string='User Template',
        help='Supports {{var_name}} placeholders and record fields.')
    content = fields.Text(
        string='Template Body',
        help='Combined template used by render(). Falls back to system + user.')
    default_params = fields.Json(string='Default Parameters', default=dict)
    lang = fields.Char(string='Language Code', help='e.g. zh_CN, en_US')
    is_active = fields.Boolean(string='Active', default=True)
    version = fields.Integer(string='Version', default=1, readonly=True)
    default_model_code = fields.Char(string='Default Model Code')
    default_temperature = fields.Float(string='Default Temperature')
    company_id = fields.Many2one('res.company', string='Company', index=True)
    history_ids = fields.One2many(
        'ai.prompt.template.history', 'template_id', string='History')
    preview_context = fields.Text(
        string='Preview Context (JSON)',
        help='JSON object used by the Preview button.')
    preview_result = fields.Text(string='Preview Result', readonly=True)

    def _combined_content(self):
        self.ensure_one()
        if self.content:
            return self.content
        parts = [part for part in (self.system_prompt, self.user_template) if part]
        return '\n\n'.join(parts)

    def _prepare_context(self, values=None, record=None):
        ctx = {}
        if record:
            ctx.update(_record_context(record))
        if values:
            if isinstance(values, Mapping):
                ctx.update(values)
            else:
                ctx['value'] = values
        ctx.setdefault('user', self.env.user.name)
        ctx.setdefault('company', self.env.company.name)
        return ctx

    def render(self, context=None, record=None):
        """Render the template. Missing variables raise UserError."""
        self.ensure_one()
        if not self.is_active:
            raise UserError(_('Prompt "%s" is disabled.') % self.display_name)
        source = self._combined_content() or ''
        ctx = self._prepare_context(context, record)
        try:
            return _JINJA.from_string(source).render(ctx)
        except (UndefinedError, TemplateError) as exc:
            raise UserError(_('Prompt "%s" failed to render: %s') % (
                self.display_name, exc)) from exc

    def render_parts(self, context=None, record=None):
        """Return ``{'system': ..., 'user': ...}`` for chat construction."""
        self.ensure_one()
        ctx = self._prepare_context(context, record)
        def _one(source):
            if not source:
                return ''
            try:
                return _JINJA.from_string(source).render(ctx)
            except (UndefinedError, TemplateError) as exc:
                raise UserError(_('Prompt "%s" failed to render: %s') % (
                    self.display_name, exc)) from exc
        return {
            'system': _one(self.system_prompt),
            'user': _one(self.user_template or self.content),
        }

    @api.model
    def _get_by_code(self, code, company=None, lang=None):
        if not code:
            return self.browse()
        company = company or self.env.company
        domain = [('code', '=', code), ('is_active', '=', True)]
        if lang:
            found = self.search(domain + [
                ('lang', '=', lang),
                '|', ('company_id', '=', False), ('company_id', '=', company.id),
            ], order='company_id desc', limit=1)
            if found:
                return found
        return self.search(domain + [
            '|', ('company_id', '=', False), ('company_id', '=', company.id),
        ], order='company_id desc', limit=1)

    def action_preview(self):
        self.ensure_one()
        context = {}
        if self.preview_context:
            import json
            try:
                context = json.loads(self.preview_context)
            except ValueError as exc:
                raise UserError(_('Preview context is not valid JSON.')) from exc
            if not isinstance(context, dict):
                raise UserError(_('Preview context must be a JSON object.'))
        self.preview_result = self.render(context)
        return True

    def action_rollback(self, history_id=None):
        self.ensure_one()
        history = self.env['ai.prompt.template.history'].browse(
            history_id).exists() if history_id else self.history_ids[:1]
        if not history:
            raise UserError(_('No history version to restore.'))
        self.write({
            'system_prompt': history.system_prompt,
            'user_template': history.user_template,
            'content': history.content,
        })
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record._save_history()
        return records

    def write(self, vals):
        tracked = {'system_prompt', 'user_template', 'content'}
        bump = bool(tracked.intersection(vals))
        res = super().write(vals)
        if bump:
            for record in self:
                super(AiPromptTemplate, record).write({
                    'version': record.version + 1,
                })
                record._save_history()
        return res

    def _save_history(self):
        self.ensure_one()
        self.env['ai.prompt.template.history'].create({
            'template_id': self.id,
            'version': self.version,
            'system_prompt': self.system_prompt or '',
            'user_template': self.user_template or '',
            'content': self._combined_content() or '',
        })


class AiPromptTemplateHistory(models.Model):
    _name = 'ai.prompt.template.history'
    _description = 'AI Prompt Template History'
    _order = 'version desc, id desc'

    template_id = fields.Many2one(
        'ai.prompt.template', string='Template', required=True,
        ondelete='cascade', index=True)
    version = fields.Integer(string='Version', required=True)
    system_prompt = fields.Text(string='System Prompt')
    user_template = fields.Text(string='User Template')
    content = fields.Text(string='Template Body')

    def action_restore(self):
        self.ensure_one()
        self.template_id.action_rollback(self.id)
        return True
