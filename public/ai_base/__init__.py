# -*- coding: utf-8 -*-

from . import tools
from . import models
from . import controllers


def post_init_hook(env):
    """Register every ``@ai_tool`` decorated method into the tool registry."""
    env['ai.tool']._sync_registry()
    env['ai.audit.log']._migrate_from_request_logs()
