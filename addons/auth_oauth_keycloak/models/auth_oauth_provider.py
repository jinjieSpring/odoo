# -*- coding: utf-8 -*-
import logging

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class AuthOauthProvider(models.Model):
    _inherit = 'auth.oauth.provider'

    flow_type = fields.Selection(
        selection=[
            ('implicit', 'Implicit Grant (POC)'),
            ('authorization_code', 'Authorization Code (Recommended)'),
        ],
        string='OAuth Flow',
        default='authorization_code',
        required=True,
        help="Implicit grant is suitable for POC only. "
             "Use Authorization Code for production Keycloak clients.",
    )
    client_secret = fields.Char(
        string='Client Secret',
        help="Required for Authorization Code flow with a confidential Keycloak client.",
    )
    token_endpoint = fields.Char(
        string='Token URL',
        help="OIDC token endpoint, e.g. "
             "https://iam.example.com/realms/myrealm/protocol/openid-connect/token",
    )
    allow_user_creation = fields.Boolean(
        string='Allow Automatic User Creation',
        default=False,
        help="When disabled, only pre-existing Odoo users can sign in. "
             "On first login, the account is linked by matching email/login.",
    )

    @api.constrains('flow_type', 'token_endpoint', 'client_secret')
    def _check_authorization_code_config(self):
        for provider in self:
            if provider.flow_type != 'authorization_code':
                continue
            if not provider.token_endpoint:
                raise UserError(self.env._(
                    "Token URL is required for provider %(name)s when using Authorization Code flow.",
                    name=provider.name,
                ))

    @api.model
    def _keycloak_endpoints(self, base_url):
        """Build standard Keycloak OIDC endpoints from a realm base URL."""
        base = base_url.rstrip('/')
        return {
            'auth_endpoint': f'{base}/protocol/openid-connect/auth',
            'token_endpoint': f'{base}/protocol/openid-connect/token',
            'validation_endpoint': f'{base}/protocol/openid-connect/userinfo',
        }

    def exchange_authorization_code(self, code, redirect_uri):
        """Exchange an authorization code for an access token."""
        self.ensure_one()
        if self.flow_type != 'authorization_code':
            raise UserError(self.env._("Provider %(name)s is not configured for Authorization Code flow.", name=self.name))
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'client_id': self.client_id,
            'redirect_uri': redirect_uri,
        }
        if self.client_secret:
            data['client_secret'] = self.client_secret
        try:
            response = requests.post(self.token_endpoint, data=data, timeout=10)
        except requests.RequestException as exc:
            _logger.warning("OAuth token exchange failed for provider %s: %s", self.name, exc)
            raise UserError(self.env._("Could not reach the OAuth token endpoint.")) from exc
        if not response.ok:
            _logger.warning(
                "OAuth token exchange failed for provider %s: %s %s",
                self.name, response.status_code, response.text,
            )
            raise UserError(self.env._("OAuth token exchange was rejected by the identity provider."))
        payload = response.json()
        access_token = payload.get('access_token')
        if not access_token:
            raise UserError(self.env._("OAuth token response did not contain an access token."))
        return access_token
