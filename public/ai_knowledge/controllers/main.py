# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class AiKnowledgeJsonRpcController(http.Controller):

    @http.route('/ai_knowledge/search', type='jsonrpc', auth='user')
    def knowledge_search(self, query, top_k=5, document_ids=None, knowledge_ids=None):
        return request.env['ai.base.service'].retrieve(
            query, top_k=top_k, document_ids=document_ids,
            knowledge_ids=knowledge_ids)
