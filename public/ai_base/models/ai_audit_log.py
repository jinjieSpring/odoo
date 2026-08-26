# -*- coding: utf-8 -*-
import json
import time

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AiAuditLog(models.Model):
    """Append-only action audit. Usage and prompt text stay on ``ai.request.log``."""

    _name = 'ai.audit.log'
    _description = 'AI Audit Log'
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    create_date = fields.Datetime(string='Created On', readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Company', index=True,
        default=lambda self: self.env.company)
    user_id = fields.Many2one(
        'res.users', string='User', required=True, index=True,
        ondelete='restrict', default=lambda self: self.env.user)
    session_id = fields.Many2one(
        'ai.chat.session', string='Chat Session', ondelete='set null', index=True)
    event_type = fields.Selection([
        ('tool_call', 'Tool Call'),
        ('tool_blocked', 'Tool Blocked'),
        ('agent_start', 'Agent Started'),
        ('agent_done', 'Agent Finished'),
        ('agent_error', 'Agent Error'),
        ('agent_cancelled', 'Agent Cancelled'),
        ('memory_write', 'Memory Write'),
    ], string='Event', required=True, index=True)
    tool_name = fields.Char(string='Tool Name', index=True)
    status = fields.Selection([
        ('success', 'Success'),
        ('error', 'Error'),
        ('blocked', 'Blocked'),
    ], string='Status', default='success', required=True, index=True)
    error_code = fields.Integer(string='Error Code')
    error_message = fields.Char(string='Error')
    latency_ms = fields.Integer(string='Latency (ms)', default=0)
    input_summary = fields.Text(string='Input')
    output_summary = fields.Text(string='Output')

    def write(self, vals):
        if self.env.context.get('_ai_audit_mutable'):
            return super().write(vals)
        self.check_access('write')
        raise UserError(_('Audit logs cannot be modified.'))

    def unlink(self):
        if self.env.context.get('_ai_audit_mutable') or self.env.context.get(
                'install_mode'):
            return super().unlink()
        self.check_access('unlink')
        raise UserError(_('Audit logs cannot be deleted.'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super(AiAuditLog, self.with_context(
            _ai_audit_mutable=True)).create(vals_list)
        return records.with_env(self.env)

    @api.model
    def _record(self, event_type, **vals):
        """Append one audit row as superuser. Extra keys are ignored if unknown.

        入参:
            event_type (str): ``tool_call`` / ``tool_blocked`` / ``agent_*`` 等。
            **vals: 字段，缺 ``user_id`` / ``company_id`` / ``session_id`` 时
                从当前环境和 ``ai_session_id`` context 补。
        返回:
            ai.audit.log: 新建记录。
        """
        vals = dict(vals)
        vals['event_type'] = event_type
        vals.setdefault('user_id', self.env.user.id)
        vals.setdefault('company_id', self.env.company.id)
        if not vals.get('session_id') and self.env.context.get('ai_session_id'):
            vals['session_id'] = self.env.context['ai_session_id']
        if 'run_id' in self._fields and not vals.get('run_id') \
                and self.env.context.get('ai_run_id'):
            vals['run_id'] = self.env.context['ai_run_id']
        session_id = vals.get('session_id')
        if session_id and 'agent_id' in self._fields and not vals.get('agent_id'):
            session = self.env['ai.chat.session'].browse(session_id)
            if 'agent_id' in session._fields and session.agent_id:
                vals['agent_id'] = session.agent_id.id
        known = set(self._fields)
        vals = {key: value for key, value in vals.items() if key in known}
        return self.sudo().create(vals)

    @api.model
    def _record_tool(self, event_type, tool_name, params=None, result=None,
                     started=None, status=None, error_code=None, message=None,
                     session=None):
        """Write a tool_call or tool_blocked row from an invoke attempt."""
        result = result or {}
        if not status:
            if event_type == 'tool_blocked':
                status = 'blocked'
            elif result.get('status') == 'success':
                status = 'success'
            else:
                status = 'error'
        latency = 0
        if started is not None:
            latency = int((time.time() - started) * 1000)
        return self._record(
            event_type,
            tool_name=tool_name,
            session_id=session.id if session else False,
            status=status,
            error_code=error_code if error_code is not None else (
                result.get('code') if status != 'success' else False),
            error_message=message or (
                result.get('message') if status != 'success' else False),
            latency_ms=latency,
            input_summary=json.dumps(params or {}, ensure_ascii=False)[:2000],
            output_summary=json.dumps(result, ensure_ascii=False)[:2000]
            if result else False,
        )

    @api.model
    def _migrate_from_request_logs(self):
        """Copy legacy ``request_type=tool`` usage rows into this table."""
        logs = self.env['ai.request.log'].sudo().search([
            ('request_type', '=', 'tool'),
        ])
        if not logs:
            return
        vals_list = []
        for log in logs:
            vals_list.append({
                'event_type': 'tool_call',
                'user_id': log.user_id.id,
                'company_id': log.company_id.id if log.company_id else False,
                'session_id': log.session_id.id if log.session_id else False,
                'tool_name': log.tool_name,
                'status': log.status if log.status in ('success', 'error')
                else 'error',
                'error_message': log.error_message,
                'latency_ms': log.latency_ms,
                'input_summary': log.input_summary,
                'output_summary': log.output_summary,
                'create_date': log.create_date,
            })
        self.sudo().create(vals_list)
        logs.unlink()
