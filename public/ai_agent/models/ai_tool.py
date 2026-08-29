# -*- coding: utf-8 -*-
from odoo import models


class AiTool(models.Model):
    _inherit = 'ai.tool'

    def allowed_tools(self, session=None):
        tools = super().allowed_tools(session=session)
        if session is None:
            return tools
        allowed = session._restricted_tool_names()
        if allowed is None:
            return tools
        return [tool for tool in tools if tool.get('name') in allowed]
