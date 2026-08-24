# -*- coding: utf-8 -*-
from odoo import models


class AiTool(models.Model):
    _inherit = 'ai.tool'

    def action_get_manifest_for_user(self, session=None):
        manifest = super().action_get_manifest_for_user(session=session)
        if session is None:
            return manifest
        allowed = session._restricted_tool_names()
        if allowed is None:
            return manifest
        return [tool for tool in manifest if tool.get('name') in allowed]
