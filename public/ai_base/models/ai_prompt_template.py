# -*- coding: utf-8 -*-
import json
import logging
from collections.abc import Mapping

from jinja2 import Environment, StrictUndefined, UndefinedError, TemplateError, meta

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
    _order = 'name'
    _check_company_auto = True

    name = fields.Char(string='Name', required=True, translate=True)
    code = fields.Char(
        string='Key', required=True, index=True,
        help='Stable key used by business modules, e.g. sale.email.draft')
    description = fields.Text(string='Description')
    system_prompt = fields.Text(string='System Prompt')
    user_template = fields.Text(
        string='User Template',
        help='Supports {{var_name}} placeholders and record fields.')
    default_params = fields.Json(string='Default Parameters', default=dict)
    is_active = fields.Boolean(string='Active', default=True)
    version = fields.Integer(string='Version', default=1, readonly=True)
    company_id = fields.Many2one('res.company', string='Company', index=True)
    history_ids = fields.One2many(
        'ai.prompt.template.history', 'template_id', string='Version History')
    preview_context = fields.Text(
        string='Preview Context (JSON)',
        help='Sample JSON used by Preview. Leave empty to fill typical values automatically.')
    preview_result = fields.Text(string='Preview Result', readonly=True)

    def _combined_content(self):
        self.ensure_one()
        return '\n\n'.join(
            part for part in (self.system_prompt, self.user_template) if part)

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
            'user': _one(self.user_template),
        }

    @api.model
    def _get_by_code(self, code, company=None):
        if not code:
            return self.browse()
        company = company or self.env.company
        domain = [('code', '=', code), ('is_active', '=', True)]
        return self.search(domain + [
            '|', ('company_id', '=', False), ('company_id', '=', company.id),
        ], order='company_id desc', limit=1)

    def _preview_defaults(self, source):
        """Typical values so Preview can run without hand-written JSON."""
        names = meta.find_undeclared_variables(_JINJA.parse(source or ''))
        names -= {'user', 'company', 'record', 'value'}
        samples = {
            'items': [{
                'citation': '[SOURCE:demo]',
                'page': 1,
                'source_document': 'demo.pdf',
                'content': 'Sample knowledge excerpt.',
            }],
            'query': 'Sample question',
            'text': 'Sample text',
            'lang': self.env.lang or 'en_US',
            'who': 'Ada',
            'name': 'Ada',
        }
        return {name: samples.get(name, 'sample') for name in names}

    def _preview_error_message(self, exc):
        text = str(exc)
        if 'is undefined' in text and "'" in text:
            name = text.split("'")[1]
            return _(
                'The template needs a value for "%s". Add it to the JSON '
                'on the Preview tab, for example: {"%s": "sample"}.'
            ) % (name, name)
        return _('Could not render this template: %s') % text

    def action_preview(self):
        self.ensure_one()
        context = self._preview_defaults(self._combined_content())
        if self.preview_context:
            try:
                parsed = json.loads(self.preview_context)
            except ValueError as exc:
                raise UserError(_('Preview context is not valid JSON.')) from exc
            if not isinstance(parsed, dict):
                raise UserError(_('Preview context must be a JSON object.'))
            context.update(parsed)
        elif context:
            self.preview_context = json.dumps(context, ensure_ascii=False, indent=2)
        try:
            parts = self.render_parts(context)
            blocks = []
            if parts.get('system'):
                blocks.append('%s\n%s' % (_('System Prompt'), parts['system']))
            if parts.get('user'):
                blocks.append('%s\n%s' % (_('User Template'), parts['user']))
            self.preview_result = '\n\n'.join(blocks)
        except UserError as exc:
            self.preview_result = self._preview_error_message(exc)
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
        })
        return True

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record._save_history()
        return records

    def write(self, vals):
        tracked = {'system_prompt', 'user_template'}
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

    def action_restore(self):
        self.ensure_one()
        self.template_id.action_rollback(self.id)
        return True
