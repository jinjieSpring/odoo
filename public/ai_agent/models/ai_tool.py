# -*- coding: utf-8 -*-
from odoo import models


class AiTool(models.Model):
    _inherit = 'ai.tool'

    def action_get_manifest_for_user(self, session=None):
        manifest = super().action_get_manifest_for_user(session=session)
        if session is None or not session.agent_id or not session.agent_id.tool_ids:
            return manifest
        allowed = set(session.agent_id.tool_ids.mapped('name'))
        return [tool for tool in manifest if tool.get('name') in allowed]
