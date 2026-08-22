# -*- coding: utf-8 -*-
{
    'name': 'AI Base',
    'version': '19.0.1.0.0',
    'category': 'Productivity/AI',
    'summary': 'Odoo 19 AI foundation: adapters, prompts, RAG, tools, chat',
    'description': """
AI Base
=======

Generic, multi-company AI foundation for Odoo 19. Business modules call this
layer instead of talking to vendors directly.

* Vendor adapters (OpenAI-compatible, Qwen, Ernie, DeepSeek, Ollama, private)
* Model pool, prompt templates with versioning, RAG knowledge bases
* Registered Agent tools (Python / ORM / HTTP) with ACL and audit logs
* Chat sessions, jsonrpc + SSE streaming, OWL chat widget and field enhancer

Requires PostgreSQL. For production RAG, install the ``vector`` extension::

    CREATE EXTENSION IF NOT EXISTS vector;

Install does not fail if the extension is unavailable.
""",
    'author': 'Odoo AI Capability Building Team',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'mail'],
    'data': [
        'security/ai_base_security.xml',
        'security/ir.model.access.csv',
        'data/ai_base_data.xml',
        'views/ai_adapter_views.xml',
        'views/ai_model_views.xml',
        'views/ai_prompt_views.xml',
        'views/ai_knowledge_views.xml',
        'views/ai_tool_views.xml',
        'views/ai_session_views.xml',
        'views/ai_request_log_views.xml',
        'views/ai_async_job_views.xml',
        'views/ai_config_views.xml',
        'views/ai_menus.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ai_base/static/src/scss/ai_base.scss',
            'ai_base/static/src/xml/ai_systray.xml',
            'ai_base/static/src/js/ai_systray.js',
            'ai_base/static/src/xml/ai_chat.xml',
            'ai_base/static/src/js/ai_chat.js',
            'ai_base/static/src/xml/ai_field.xml',
            'ai_base/static/src/js/ai_field.js',
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
