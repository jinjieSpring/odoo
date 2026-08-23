# -*- coding: utf-8 -*-
from odoo import models


class AiAsyncJob(models.Model):
    _inherit = 'ai.async.job'

    def _dispatch(self):
        self.ensure_one()
        if self.job_type in ('parse_document', 'index_document') and self.res_id:
            document = self.env['ai.knowledge.document'].browse(self.res_id)
            if self.job_type == 'parse_document':
                document.action_parse()
            else:
                document.action_index()
            return document.state
        return super()._dispatch()
