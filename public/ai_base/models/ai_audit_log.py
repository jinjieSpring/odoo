# -*- coding: utf-8 -*-
import json
import time

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AiAuditLog(models.Model):
    """Append-only action audit. Conversation usage lives on ``ai.chat.message``."""

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
        'ai.chat.session', string='Session', ondelete='set null', index=True)
    event_type = fields.Selection([
        ('tool_call', '工具调用'),
        ('tool_blocked', '工具拦截'),
        ('policy_blocked', '策略拦截'),
        ('agent_start', '智能体已启动'),
        ('agent_done', '智能体已完成'),
        ('agent_error', '智能体错误'),
        ('agent_cancelled', '智能体已取消'),
        ('memory_write', '写入记忆'),
    ], string='事件', required=True, index=True)
    source = fields.Selection([
        ('user', '用户'),
        ('llm', '模型'),
        ('agent_run', '后台任务'),
    ], string='来源', index=True)
    tool_id = fields.Many2one('ai.tool', string='工具', ondelete='set null', index=True)
    tool_name = fields.Char(string='工具名称', index=True)
    message_id = fields.Many2one(
        'ai.chat.message', string='消息', ondelete='set null', index=True)
    res_model = fields.Char(string='业务模型', index=True)
    res_id = fields.Integer(string='记录 ID')
    res_name = fields.Char(compute='_compute_res_name', string='业务记录')
    block_reason = fields.Selection([
        ('unknown_tool', '未知工具'),
        ('no_permission', '无权限'),
        ('rate_limit', '工具超频'),
        ('agent_deny', '智能体未授权'),
        ('schema', '参数无效'),
        ('sensitive', '敏感词'),
        ('chat_limit', '对话限流'),
    ], string='拦截原因', index=True)
    status = fields.Selection([
        ('success', '成功'),
        ('error', '错误'),
        ('blocked', '已拦截'),
    ], string='状态', default='success', required=True, index=True)
    error_code = fields.Integer(string='错误码')
    error_message = fields.Char(string='错误')
    latency_ms = fields.Integer(string='执行耗时', default=0)
    input_summary = fields.Text(string='参数')
    output_summary = fields.Text(string='结果')

    _BLOCK_BY_CODE = {
        404: 'unknown_tool',
        421: 'no_permission',
        429: 'rate_limit',
        400: 'schema',
        403: 'no_permission',
    }

    @api.depends('res_model', 'res_id')
    def _compute_res_name(self):
        for audit in self:
            name = False
            if audit.res_model and audit.res_id and audit.res_model in self.env:
                record = self.env[audit.res_model].browse(audit.res_id).exists()
                name = record.display_name if record else False
            elif audit.res_model:
                name = audit.res_model
            audit.res_name = name

    def action_open_resource(self):
        self.ensure_one()
        if not self.res_model or not self.res_id or self.res_model not in self.env:
            return False
        record = self.env[self.res_model].browse(self.res_id).exists()
        if not record:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': self.res_name or _('Related Record'),
            'res_model': self.res_model,
            'res_id': record.id,
            'view_mode': 'form',
            'target': 'current',
        }

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
        vals.setdefault('source', self._infer_source())
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
        if vals.get('tool_name') and not vals.get('tool_id'):
            tool = self.env['ai.tool'].sudo().search(
                [('name', '=', vals['tool_name'])], limit=1)
            if tool:
                vals['tool_id'] = tool.id
        known = set(self._fields)
        vals = {key: value for key, value in vals.items() if key in known}
        return self.sudo().create(vals)

    @api.model
    def _infer_source(self, explicit=None):
        if explicit:
            return explicit
        if self.env.context.get('ai_run_id'):
            return 'agent_run'
        return self.env.context.get('ai_audit_source') or 'user'

    @api.model
    def _resource_from_params(self, params):
        params = params or {}
        model = params.get('model')
        if not isinstance(model, str) or not model:
            return {}
        res_id = params.get('id') or params.get('res_id')
        ids = params.get('ids')
        if not res_id and isinstance(ids, (list, tuple)) and len(ids) == 1:
            res_id = ids[0]
        vals = {'res_model': model}
        try:
            if res_id:
                vals['res_id'] = int(res_id)
        except (TypeError, ValueError):
            pass
        return vals

    @api.model
    def _record_policy(self, block_reason, message, session=None, input_summary=None):
        vals = {
            'status': 'blocked',
            'block_reason': block_reason,
            'source': 'user',
            'error_message': (message or '')[:500],
            'input_summary': (input_summary or '')[:2000],
        }
        if session:
            vals['session_id'] = session.id
        return self._record('policy_blocked', **vals)

    def _link_to_message(self, message):
        if not self or not message:
            return
        self.with_context(_ai_audit_mutable=True).write({
            'message_id': message.id,
        })

    @api.model
    def _record_tool(self, event_type, tool_name, params=None, result=None,
                     started=None, status=None, error_code=None, message=None,
                     session=None, block_reason=None, source=None, tool=None):
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
        code = error_code if error_code is not None else (
            result.get('code') if status != 'success' else False)
        reason = block_reason
        if not reason and status == 'blocked':
            reason = self._BLOCK_BY_CODE.get(code)
        elif not reason and status == 'error':
            reason = self._BLOCK_BY_CODE.get(code)
        extra = self._resource_from_params(params)
        if tool:
            extra['tool_id'] = tool.id
        return self._record(
            event_type,
            tool_name=tool_name,
            session_id=session.id if session else False,
            status=status,
            source=self._infer_source(source),
            block_reason=reason,
            error_code=code,
            error_message=message or (
                result.get('message') if status != 'success' else False),
            latency_ms=latency,
            input_summary=json.dumps(params or {}, ensure_ascii=False)[:2000],
            output_summary=json.dumps(result, ensure_ascii=False)[:2000]
            if result else False,
            **extra,
        )
