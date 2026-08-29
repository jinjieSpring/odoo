# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

_ACTIVE_STATES = ('pending', 'running')


class AiAgentRun(models.Model):
    """One background goal execution on a session.

    Work continues after the chat UI is closed. The send request only
    records the run; steps run via cron (or OCA queue_job when installed).
    A session has at most one active run; starting a new goal cancels the
    previous. Runs are not nested and do not dispatch to other agents.
    """
    _name = 'ai.agent.run'
    _description = 'AI Agent Run'
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char(string='Name', required=True)
    agent_id = fields.Many2one(
        'ai.agent', string='Agent', required=True, ondelete='cascade', index=True)
    session_id = fields.Many2one(
        'ai.chat.session', string='Session', required=True, ondelete='cascade',
        index=True)
    user_id = fields.Many2one(
        'res.users', string='User', required=True, ondelete='cascade',
        default=lambda self: self.env.user, index=True)
    company_id = fields.Many2one(
        'res.company', string='Company', index=True,
        default=lambda self: self.env.company)
    goal = fields.Text(string='Goal', required=True)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('waiting_user', 'Waiting for User'),
        ('done', 'Done'),
        ('error', 'Error'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='pending', required=True, index=True)
    step_count = fields.Integer(string='Steps', default=0)
    error_message = fields.Char(string='Error')
    plan = fields.Json(string='Plan', default=list)

    @api.model
    def _start_from_chat(self, session, content, options=None):
        session.ensure_one()
        content = (content or '').strip()
        agent = session.agent_id
        active = self.search([
            ('session_id', '=', session.id),
            ('state', 'in', _ACTIVE_STATES),
        ], limit=1)
        if active:
            self.env['ai.chat.message'].create({
                'session_id': session.id,
                'role': 'user',
                'content': content,
            })
            self.env['ai.chat.message'].create({
                'session_id': session.id,
                'role': 'assistant',
                'content': _(
                    "I'm still working on the previous task:\n\n%s\n\n"
                    "Wait for it to finish, or cancel it first."
                ) % (active.goal or ''),
            })
            return self.env['ai.chat'].result(session)
        self.env['ai.chat.message'].create({
            'session_id': session.id,
            'role': 'user',
            'content': content,
        })
        if session.name == _('New Session'):
            session.name = content[:30]
        self.env['ai.chat.message'].create({
            'session_id': session.id,
            'role': 'assistant',
            'content': _(
                "I'll keep working on this even if you leave this chat. "
                "Progress will appear here.\n\nTask: %s"
            ) % content,
        })
        run = self.create({
            'name': (content or _('Agent run'))[:80],
            'agent_id': agent.id,
            'session_id': session.id,
            'user_id': session.user_id.id,
            'company_id': session.company_id.id,
            'goal': content,
            'state': 'pending',
        })
        session.write({'state': 'open'})
        run._audit('agent_start', input_summary=(content or '')[:4000])
        run._notify()
        run._schedule_step()
        return self.env['ai.chat'].result(session)

    def _audit(self, event_type, **vals):
        self.ensure_one()
        vals.setdefault('session_id', self.session_id.id)
        vals.setdefault('agent_id', self.agent_id.id)
        vals.setdefault('run_id', self.id)
        vals.setdefault('status', 'success' if event_type != 'agent_error' else 'error')
        return self.env['ai.audit.log']._record(event_type, **vals)

    def action_cancel(self):
        for run in self.filtered(lambda rec: rec.state in _ACTIVE_STATES):
            run.write({'state': 'cancelled'})
            run._audit('agent_cancelled', input_summary=(run.goal or '')[:4000])
            run._post_status(_('Stopped the background task.'))
            run._notify()
        return True

    def _notify(self):
        for run in self:
            partner = run.user_id.partner_id
            if not partner:
                continue
            self.env['bus.bus']._sendone(partner, 'ai_agent/run', {
                'session_id': run.session_id.id,
                'run_id': run.id,
                **run._payload(),
            })

    def _payload(self):
        self.ensure_one()
        return {
            'id': self.id,
            'state': self.state,
            'agent_id': self.agent_id.id,
            'goal': (self.goal or '')[:200],
            'step_count': self.step_count,
            'max_rounds': self.agent_id._effective_max_rounds(),
            'error_message': self.error_message or '',
        }

    def _post_status(self, content):
        self.ensure_one()
        if not content or not self.session_id:
            return
        self.env['ai.chat.message'].create({
            'session_id': self.session_id.id,
            'role': 'assistant',
            'content': content,
        })

    def _queue_job_available(self):
        return 'queue.job' in self.env

    def _should_delay(self):
        if self.env.context.get('queue_job__no_delay'):
            return False
        return self._queue_job_available()

    def _cron(self):
        return self.env.ref(
            'ai_agent.ir_cron_agent_runs', raise_if_not_found=False)

    def _schedule_step(self):
        """Continue without keeping the chat request or UI open."""
        runs = self.filtered(lambda rec: rec.state in _ACTIVE_STATES)
        if not runs:
            return
        if runs._should_delay():
            for run in runs:
                run.with_delay(
                    description=_('AI Agent run: %s') % run.display_name,
                    identity_key='ai_agent_run_%s' % run.id,
                )._step()
            return
        cron = runs._cron()
        if cron:
            cron.sudo()._trigger()

    def _step(self):
        self.ensure_one()
        if self.state not in _ACTIVE_STATES:
            return
        locked = self.try_lock_for_update(allow_referencing=True)
        if not locked:
            return
        agent = self.agent_id
        session = self.session_id
        if not agent.active or not session:
            self.write({
                'state': 'error',
                'error_message': _('The agent or session is no longer available.'),
            })
            self._audit(
                'agent_error', status='error',
                error_message=_('The agent or session is no longer available.'),
                input_summary=(self.goal or '')[:4000])
            self._post_status(_(
                'The background task stopped because the agent or session '
                'is no longer available.'))
            self._notify()
            return
        max_steps = max(1, agent._effective_max_rounds())
        self.write({
            'state': 'running',
            'step_count': self.step_count + 1,
            'error_message': False,
        })
        per_tick = min(3, max_steps)
        last = self.step_count >= max_steps
        options = {
            'max_rounds': per_tick,
            'skip_memory': True,
        }
        service = self.env['ai.agent.service'].with_user(self.user_id).with_company(
            self.company_id or self.env.company).with_context(
            ai_run_id=self.id, ai_session_id=session.id)
        try:
            result = service.chat(
                self.goal,
                session=session.with_user(self.user_id).with_company(
                    self.company_id or self.env.company),
                persist_user=False,
                options=options,
                scenario='agent',
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception('ai_agent run %s failed', self.id)
            self.write({
                'state': 'error',
                'error_message': str(exc)[:500],
            })
            self._audit(
                'agent_error', status='error',
                error_message=str(exc)[:500],
                input_summary=(self.goal or '')[:4000])
            self._post_status(_('The background task failed: %s') % str(exc)[:500])
            self._notify()
            return
        error = result.get('error') if isinstance(result, dict) else False
        last_cards = ((result.get('rounds') or [{}])[-1].get('cards') or [])
        finished = last or bool(error) or not last_cards
        vals = {}
        if error:
            vals['state'] = 'error'
            vals['error_message'] = (error.get('message') or str(error))[:500]
        elif finished:
            vals['state'] = 'done'
        if vals:
            self.write(vals)
            if vals.get('state') == 'error':
                self._audit(
                    'agent_error', status='error',
                    error_message=vals.get('error_message') or '',
                    input_summary=(self.goal or '')[:4000])
                self._post_status(_(
                    'The background task failed: %s'
                ) % (vals.get('error_message') or ''))
            if vals.get('state') == 'done':
                self._audit(
                    'agent_done',
                    input_summary=(self.goal or '')[:4000],
                    output_summary=(result.get('reply') or '')[:4000])
                if agent.memory_enabled:
                    self.env['ai.agent.memory'].sudo()._remember_from_turn(
                        agent, self.goal, result.get('reply') or '',
                        user=self.user_id,
                        company=self.company_id or self.env.company)
        self._notify()
        if self.state in _ACTIVE_STATES:
            self._schedule_step()

    @api.model
    def _cron_step_runs(self, batch_size=5):
        runs = self.search(
            [('state', 'in', list(_ACTIVE_STATES))],
            order='id', limit=batch_size)
        if runs._should_delay():
            runs._schedule_step()
            return
        for run in runs:
            try:
                run._step()
            except Exception:  # noqa: BLE001
                _logger.exception('ai_agent cron step failed for run %s', run.id)
