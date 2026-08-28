# -*- coding: utf-8 -*-
from odoo import models


class AiChat(models.AbstractModel):
    _inherit = 'ai.chat'

    def session_payload(self, session):
        payload = super().session_payload(session)
        agent = session.agent_id
        run = session._active_agent_run()
        payload['session'].update({
            'agent_id': agent.id if agent else False,
            'agent_run_mode': agent.run_mode if agent else 'chat',
            'agent_run': run._payload() if run else False,
        })
        return payload

    def send_message(self, session, content, options=None):
        session.ensure_one()
        if session._is_goal_run():
            return self.env['ai.agent.run']._start_from_chat(
                session, content, options)
        return super().send_message(session, content, options)
