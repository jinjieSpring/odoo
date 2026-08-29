# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class AiBaseJsonRpcController(http.Controller):
    """JSON-RPC endpoints for the OWL chat widget."""

    @http.route('/ai_base/defaults', type='jsonrpc', auth='user')
    def defaults(self):
        return request.env['ai.chat.session'].action_get_defaults()

    @http.route('/ai_base/session/create', type='jsonrpc', auth='user')
    def session_create(self, name=None, content=None, res_model=None, res_id=None):
        if content:
            session_id = request.env['ai.chat.session'].action_create_from_input(
                content, res_model=res_model, res_id=res_id)
            return {'id': session_id}
        vals = {}
        if name:
            vals['name'] = name
        if res_model:
            vals['res_model'] = res_model
        if res_id:
            vals['res_id'] = res_id
        session = request.env['ai.chat.session'].create(vals)
        return {'id': session.id}

    @http.route('/ai_base/session/list', type='jsonrpc', auth='user')
    def session_list(self):
        return request.env['ai.chat.session'].action_list_sessions()

    @http.route('/ai_base/session/get', type='jsonrpc', auth='user')
    def session_get(self, session_id):
        session = request.env['ai.chat.session'].browse(int(session_id)).exists()
        if not session:
            return {'error': 'Session not found'}
        return session.action_get_session()

    @http.route('/ai_base/session/send', type='jsonrpc', auth='user')
    def session_send(self, session_id, content, options=None):
        session = request.env['ai.chat.session'].browse(int(session_id)).exists()
        if not session:
            return {'error': {'message': 'Session not found', 'code': 'not_found'}}
        return session.action_send_message(content, options or {})

    @http.route('/ai_base/session/delete', type='jsonrpc', auth='user')
    def session_delete(self, session_id):
        session = request.env['ai.chat.session'].browse(int(session_id)).exists()
        if session:
            session.unlink()
        return True

    @http.route('/ai_base/session/options', type='jsonrpc', auth='user')
    def session_options(self, session_id, options):
        session = request.env['ai.chat.session'].browse(int(session_id)).exists()
        if not session:
            return {'error': 'Session not found'}
        return session.action_set_options(options or {})
