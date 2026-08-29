# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class AiAsyncJob(models.Model):
    """Leftover local queue for knowledge parse / index.

    Parse / Index buttons still run inline, or via OCA ``queue_job`` when
    that module is installed. Do not grow this model; keep it for leftover
    rows and the 5-minute cron.
    """

    _name = 'ai.async.job'
    _description = 'AI Asynchronous Job'
    _order = 'id desc'
    _check_company_auto = True

    name = fields.Char(string='Name', required=True)
    job_type = fields.Selection([
        ('parse_document', 'Parse Document'),
        ('index_document', 'Index Document'),
        ('summarize', 'Summarize'),
        ('custom', 'Custom'),
    ], string='Type', required=True, default='custom')
    state = fields.Selection([
        ('pending', 'Pending'),
        ('running', 'Running'),
        ('done', 'Done'),
        ('error', 'Error'),
    ], string='Status', default='pending', required=True, index=True)
    company_id = fields.Many2one(
        'res.company', string='Company',
        default=lambda self: self.env.company)
    user_id = fields.Many2one(
        'res.users', string='User', default=lambda self: self.env.user)
    res_model = fields.Char(string='Target Model')
    res_id = fields.Integer(string='Target ID')
    payload = fields.Json(string='Payload', default=dict)
    result = fields.Text(string='Result')
    error_message = fields.Char(string='Error')
    attempt = fields.Integer(string='Attempts', default=0)
    max_attempts = fields.Integer(string='Max Attempts', default=3)

    def action_run(self):
        for job in self.filtered(lambda rec: rec.state in ('pending', 'error')):
            job._run()
        return True

    def _run(self):
        self.ensure_one()
        self.write({
            'state': 'running',
            'attempt': self.attempt + 1,
            'error_message': False,
        })
        try:
            result = self._dispatch()
            self.write({
                'state': 'done',
                'result': (result or '')[:8000],
            })
        except Exception as exc:  # noqa: BLE001
            _logger.exception('ai_knowledge async job %s failed', self.id)
            vals = {
                'error_message': str(exc)[:500],
                'state': 'pending' if self.attempt < self.max_attempts else 'error',
            }
            self.write(vals)

    def _dispatch(self):
        self.ensure_one()
        document = self.env['ai.knowledge.document']
        if self.job_type == 'parse_document' and self.res_id:
            rec = document.browse(self.res_id)
            if rec.exists():
                rec.with_context(ai_knowledge_force_sync=True)._parse_one()
            return _('Parsed')
        if self.job_type == 'index_document' and self.res_id:
            rec = document.browse(self.res_id)
            if rec.exists():
                rec.with_context(ai_knowledge_force_sync=True)._index_one()
            return _('Indexed')
        if self.job_type == 'summarize':
            text = (self.payload or {}).get('text') or ''
            result = self.env['ai.chat.service'].chat(
                text, prompt_key='summary.default', scenario='summary')
            return result.get('reply') or ''
        return _('Nothing to do.')

    @api.model
    def enqueue(self, name, job_type, res_model=None, res_id=None, payload=None):
        return self.create({
            'name': name,
            'job_type': job_type,
            'res_model': res_model or False,
            'res_id': res_id or False,
            'payload': payload or {},
        })

    @api.model
    def _cron_run_jobs(self, batch_size=10):
        jobs = self.search([('state', '=', 'pending')], limit=batch_size)
        jobs.action_run()
