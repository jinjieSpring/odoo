# -*- coding: utf-8 -*-
{
    'name': 'AI Knowledge',
    'version': '19.0.1.0.0',
    'category': 'Productivity/AI',
    'summary': 'Knowledge bases, embeddings and RAG for AI Base',
    'description': """
AI Knowledge
============

Optional RAG layer on top of AI Base.

* Knowledge bases, documents, chunking and vector stores
* Default embedding model on the AI configuration page
* Knowledge grid in the chat sidebar
* RAG retrieval injected into chat when a session enables the knowledge base

Uninstalling this module leaves AI Base chat, providers, tools and usage logs
intact. The chat sidebar hides the knowledge panel automatically.
""",
    'author': 'Odoo AI Capability Building Team',
    'license': 'LGPL-3',
    'depends': ['ai_base'],
    'data': [
        'security/ai_knowledge_security.xml',
        'security/ir.model.access.csv',
        'data/ai_knowledge_data.xml',
        'views/ai_knowledge_views.xml',
        'views/ai_config_views.xml',
        'views/ai_session_views.xml',
        'views/ai_menus.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
