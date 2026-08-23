# -*- coding: utf-8 -*-
{
    'name': 'AI Base',
    'version': '19.0.1.0.0',
    'category': 'Productivity/AI',
    'summary': 'Odoo 19 AI foundation: providers, prompts, tools, chat',
    'description': """
AI Base
=======

Generic, multi-company AI foundation for Odoo 19. Business modules call this
layer instead of talking to vendors directly.

* Vendor providers (OpenAI-compatible, Qwen, Ernie, DeepSeek, Ollama, private)
* Model pool and prompt templates with versioning
* Registered Agent tools (Python / ORM / HTTP) with ACL and audit logs
* Chat sessions, jsonrpc + NDJSON streaming and OWL chat widget

Knowledge bases and RAG live in the optional ``ai_knowledge`` module.
This module does not depend on OCA ``queue_job``.
""",
    'author': 'Odoo AI Capability Building Team',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/ai_base_security.xml',
        'security/ir.model.access.csv',
        'data/ai_base_data.xml',
        'views/ai_provider_views.xml',
        'views/ai_model_views.xml',
        'views/ai_prompt_views.xml',
        'views/ai_tool_views.xml',
        'views/ai_session_views.xml',
        'views/ai_request_log_views.xml',
        'views/ai_config_views.xml',
        'views/ai_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ai_base/static/src/scss/ai_base.scss',
            'ai_base/static/src/xml/ai_systray.xml',
            'ai_base/static/src/js/ai_systray.js',
            'ai_base/static/src/xml/ai_chat.xml',
            'ai_base/static/src/js/ai_view_context.js',
            'ai_base/static/src/js/ai_chat.js',
            'ai_base/static/src/xml/ai_chat_dialog.xml',
            'ai_base/static/src/js/ai_chat_dialog.js',
            'ai_base/static/src/xml/ai_formatted_text.xml',
            'ai_base/static/src/js/ai_formatted_text.js',
            'ai_base/static/src/js/ai_markdown.js',
            'ai_base/static/src/xml/ai_tool_card.xml',
            'ai_base/static/src/js/ai_tool_card.js',
            'ai_base/static/src/xml/ai_prompt_dialog.xml',
            'ai_base/static/src/js/ai_prompt_dialog.js',
            'ai_base/static/src/xml/ai_user_settings_dialog.xml',
            'ai_base/static/src/js/ai_user_settings_dialog.js',
        ],
        'web.assets_unit_tests': [
            'ai_base/static/tests/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}
