# -*- coding: utf-8 -*-
{
    'name': 'HD AI Base',
    'version': '19.0.1.0.0',
    'category': 'Productivity/AI',
    'summary': 'AI foundation: model providers, tool framework and systray chat',
    'description': """
HD AI Base
==========

- Unified model access layer: DeepSeek (cloud) and vLLM (local) providers
  over the OpenAI-compatible protocol, with token usage metering and
  priority/failover configuration.
- AI tool framework: @ai_tool decorator, tool registry and metadata, and the
  generic read-only tools search_read / search_count / group_by with audit
  logging.
- System tray AI chat with streaming output and business record context
  awareness.

This module is the foundation of the hdai_* module family. All backend tools
are strictly read-only; any data modification goes through the standard Odoo
flow after explicit user confirmation on the frontend.
""",
    'author': 'Odoo AI Capability Building Team',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/hdai_security.xml',
        'security/ir.model.access.csv',
        'data/hdai_data.xml',
        'views/hdai_provider_views.xml',
        'views/hdai_model_views.xml',
        'views/hdai_tool_views.xml',
        'views/hdai_session_views.xml',
        'views/hdai_nlview_views.xml',
        'views/hdai_menus.xml',
        'views/hdai_settings.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'hdai_base/static/src/scss/hdai_base.scss',
            'hdai_base/static/src/xml/hdai_systray.xml',
            'hdai_base/static/src/js/hdai_systray.js',
            'hdai_base/static/src/xml/hdai_chat.xml',
            'hdai_base/static/src/js/hdai_view_context.js',
            'hdai_base/static/src/js/hdai_chat.js',
            'hdai_base/static/src/xml/hdai_chat_dialog.xml',
            'hdai_base/static/src/js/hdai_chat_dialog.js',
            'hdai_base/static/src/xml/hdai_chat_action.xml',
            'hdai_base/static/src/js/hdai_chat_action.js',
            'hdai_base/static/src/xml/hdai_formatted_text.xml',
            'hdai_base/static/src/js/hdai_formatted_text.js',
            'hdai_base/static/src/js/hdai_markdown.js',
            'hdai_base/static/src/xml/hdai_tool_card.xml',
            'hdai_base/static/src/js/hdai_tool_card.js',
            'hdai_base/static/src/xml/hdai_prompt_dialog.xml',
            'hdai_base/static/src/js/hdai_prompt_dialog.js',
            'hdai_base/static/src/xml/hdai_user_settings_dialog.xml',
            'hdai_base/static/src/js/hdai_user_settings_dialog.js',
        ],
        'web.assets_unit_tests': [
            'hdai_base/static/tests/**/*',
        ],
    },
    'installable': True,
    'application': True,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}
