# -*- coding: utf-8 -*-
from odoo import _, models


class AiBaseService(models.AbstractModel):
    _inherit = 'ai.base.service'

    def stream_chat(self, content, session, options=None):
        """流式聊天钩子：goal 模式改走后台 run，chat 模式交给父类工具循环。

        入参:
            content (str): 用户本轮原文。
            session: ``ai.chat.session``，需带 ``agent_id``。
            options (dict): 调用选项，转给 ``_start_from_chat`` 或父类。
        返回:
            dict: ``result`` / ``events`` / ``error``。goal 模式立即回一条
            「已接下任务」类助手文案，真正执行在 ``ai.agent.run``。
        """
        if session and session._is_goal_run():
            payload = self.env['ai.chat'].send_message(
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
        """把当前 session 上 agent 的人设和记忆拼进 system prompt。

        入参:
            session: ``ai.chat.session``；无 ``agent_id`` 则不注入。
            query (str): 本轮用户问题，供 prompt 模板渲染。
        返回:
            list[str]: 文本块列表（模板或 ``system_prompt``，再加上记忆）。
            无 agent 时返回 ``[]``。
        """
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
        """执行工具前按 agent.tool_ids 白名单拦截；名单为空则不限制。

        入参:
            name (str): 工具 name。
            arguments (dict): 模型给出的参数。
            session: 当前会话，读 ``session.agent_id.tool_ids``。
        返回:
            tuple: ``(card, status, result_data)``。不在白名单时
            ``status='blocked'``；否则交给父类真正调用。
        """
        if session:
            allowed = session._restricted_tool_names()
            if allowed is not None and name not in allowed:
                tool = self.env['ai.tool'].sudo().search(
                    [('name', '=', name)], limit=1)
                card = {
                    'name': name,
                    'label': tool._tool_label() if tool else name,
                    'status': 'blocked',
                    'arguments': arguments,
                    'error': {
                        'message': _(
                            'Tool "%s" is not enabled for this agent.') % (
                                tool._tool_label() if tool else name),
                    },
                }
                return card, 'blocked', {}
        return super()._execute_loop_call(name, arguments, session=session)

    def on_ai_request_done(self, payload, result):
        """一轮 chat 成功后，把本轮问答总结进 agent 记忆。

        入参:
            payload (dict): 请求包，读 ``options`` / ``session`` / ``content`` /
                ``scenario``。
            result (dict): 本轮结果，读 ``reply``。
        返回:
            dict: 原样或父类改过的 result。以下情况不写记忆：
            ``skip_memory``、``scenario='summary'``、无 agent、未开记忆、goal 模式。
        """
        result = super().on_ai_request_done(payload, result)
        options = payload.get('options') or {}
        if options.get('skip_memory') or payload.get('scenario') == 'summary':
            return result
        session = payload.get('session')
        if not session or not session.agent_id or not session.agent_id.memory_enabled:
            return result
        if session._is_goal_run():
            return result
        self.env['ai.agent.memory']._remember_from_turn(
            session.agent_id,
            payload.get('content'),
            (result or {}).get('reply'),
        )
        return result
