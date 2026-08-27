# -*- coding: utf-8 -*-
import json
import time

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AiAuditLog(models.Model):
    """Append-only action audit. Usage and prompt text stay on ``ai.request.log``."""

    _name = 'ai.audit.log'
    _description = 'AI 审计日志'
    _order = 'create_date desc, id desc'
    _check_company_auto = True

    create_date = fields.Datetime(string='创建时间', readonly=True)
    company_id = fields.Many2one(
        'res.company', string='公司', index=True,
        default=lambda self: self.env.company)
    user_id = fields.Many2one(
        'res.users', string='用户', required=True, index=True,
        ondelete='restrict', default=lambda self: self.env.user)
    session_id = fields.Many2one(
        'ai.chat.session', string='对话会话', ondelete='set null', index=True)
    event_type = fields.Selection([
        ('tool_call', '工具调用'),
        ('tool_blocked', '工具拦截'),
        ('agent_start', '智能体已启动'),
        ('agent_done', '智能体已完成'),
        ('agent_error', '智能体错误'),
        ('agent_cancelled', '智能体已取消'),
        ('memory_write', '写入记忆'),
    ], string='事件', required=True, index=True)
    tool_name = fields.Char(string='工具名称', index=True)
    status = fields.Selection([
        ('success', '成功'),
        ('error', '错误'),
        ('blocked', '已拦截'),
    ], string='状态', default='success', required=True, index=True)
    error_code = fields.Integer(string='错误码')
    error_message = fields.Char(string='错误')
    latency_ms = fields.Integer(string='耗时（毫秒）', default=0)
    input_summary = fields.Text(string='输入')
    output_summary = fields.Text(string='输出')

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
