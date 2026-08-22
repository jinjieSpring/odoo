# -*- coding: utf-8 -*-
{
    'name': 'Keycloak OAuth Authentication',
    'version': '1.0',
    'category': 'Hidden/Tools',
    'summary': 'OAuth2/OIDC integration with Keycloak IAM',
    'description': """
Keycloak IAM Integration for Odoo
===================================

Extends auth_oauth to support Keycloak and other OIDC providers with:

* Authorization Code flow (recommended for production)
* Implicit flow (for POC / legacy clients)
* Pre-provisioned user binding by email
* Per-provider control of automatic user creation
* Keycloak-branded login button icon
    """,
    'depends': ['auth_oauth'],
    'data': [
        'data/auth_oauth_keycloak_data.xml',
        'views/auth_oauth_provider_views.xml',
        'views/res_config_settings_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'auth_oauth_keycloak/static/src/scss/auth_oauth_keycloak.scss',
        ],
    },
    'installable': True,
    'author': 'Odoo Community',
    'license': 'LGPL-3',
}
