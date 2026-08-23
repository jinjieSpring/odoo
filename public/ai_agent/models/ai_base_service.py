# -*- coding: utf-8 -*-
from odoo import _, models


class AiBaseService(models.AbstractModel):
    _inherit = 'ai.base.service'

    def stream_chat(self, content, session, options=None):
        if session and session.agent_id and session.agent_id.run_mode == 'goal':
            payload = self.env['ai.agent.run']._start_from_chat(
                session, content, options)
            accepted = ''
            messages = payload.get('messages') or []
            for message in reversed(messages):
                if message.get('role') == 'assistant':
                    accepted = message.get('content') or ''
                    break
            return {
                'result': {'reply': accepted, 'usage': {}, 'rounds': []},
                'events': (
                    [{'type': 'delta', 'delta': accepted}] if accepted else []
                ),
                'error': False,
            }
        return super().stream_chat(content, session, options)

    def _agent_system_parts(self, session, query):
        if not session or not session.agent_id:
            return []
        agent = session.agent_id
        parts = []
        if agent.prompt_id:
            try:
                parts.append(agent.prompt_id.render({
                    'user': self.env.user.name,
                    'company': self.env.company.name,
                    'query': query or '',
                }))
            except Exception:  # noqa: BLE001
                parts.append(agent.prompt_id._combined_content() or '')
        elif (agent.system_prompt or '').strip():
            parts.append(agent.system_prompt.strip())
        memory = self.env['ai.agent.memory']._prompt_text(agent)
        if memory:
            parts.append(memory)
        return parts

    def _execute_loop_call(self, name, arguments, session=None):
        if session and session.agent_id and session.agent_id.tool_ids:
            allowed = set(session.agent_id.tool_ids.mapped('name'))
            if name not in allowed:
                card = {
                    'name': name,
                    'status': 'blocked',
                    'arguments': arguments,
                    'error': {
                        'message': _(
                            'Tool "%s" is not enabled for this agent.') % name,
                    },
                }
                return card, 'blocked', {}
        return super()._execute_loop_call(name, arguments, session=session)

    def on_ai_request_done(self, payload, result):
        result = super().on_ai_request_done(payload, result)
        options = payload.get('options') or {}
        if options.get('skip_memory') or payload.get('scenario') == 'summary':
            return result
        session = payload.get('session')
        if not session or not session.agent_id or not session.agent_id.memory_enabled:
            return result
        if session.agent_id.run_mode == 'goal':
            return result
        self.env['ai.agent.memory']._remember_from_turn(
            session.agent_id,
            payload.get('content'),
            (result or {}).get('reply'),
        )
        return result
