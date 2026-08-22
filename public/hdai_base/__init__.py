# -*- coding: utf-8 -*-

from . import models
from . import controllers


def post_init_hook(env):
    """Register every @ai_tool decorated method into the tool registry."""
    env['hdai.tool']._sync_registry()
