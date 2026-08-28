# -*- coding: utf-8 -*-
{
    'name': 'AI Agent',
    'version': '19.0.1.1.0',
    'category': 'Productivity/AI',
    'summary': 'Configurable agents with memory and background goal runs',
    'description': """
AI Agent
========

Optional agent layer on top of AI Base.

* Named agents with a system prompt and optional tool subset
* Systray chat has no agent; dedicated menus set session.agent_id on create
* Per-agent, per-user memory injected into the system prompt
* Goal mode: accept a task in chat and continue it in the background

Uninstalling this module leaves AI Base chat, providers, tools and usage logs
intact.
""",
    'author': 'Odoo AI Capability Building Team',
    'license': 'LGPL-3',
    'depends': ['ai_base'],
    'data': [
        'security/ai_agent_security.xml',
        'security/ir.model.access.csv',
        'data/ai_agent_data.xml',
        'views/ai_agent_views.xml',
        'views/ai_session_views.xml',
        'views/ai_audit_log_views.xml',
        'views/ai_menus.xml',
    ],
    'assets': {
        'web.assets_unit_tests': [
            'ai_agent/static/tests/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
}
