# -*- coding: utf-8 -*-
import json

from odoo import api, models
from odoo.exceptions import AccessDenied
from odoo.addons.auth_signup.models.res_users import SignupError
from odoo.exceptions import UserError


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _auth_oauth_signin(self, provider, validation, params):
        oauth_provider = self.env['auth.oauth.provider'].browse(provider)
        oauth_uid = validation['user_id']
        oauth_user = self.search([
            ('oauth_uid', '=', oauth_uid),
            ('oauth_provider_id', '=', provider),
        ])
        if oauth_user:
            oauth_user.write({'oauth_access_token': params['access_token']})
            return oauth_user.login

        email = validation.get('email') or validation.get('preferred_username')
        if email and not oauth_provider.allow_user_creation:
            existing_user = self.search([
                ('login', '=', email),
                ('oauth_provider_id', 'in', [False, provider]),
            ], limit=1)
            if existing_user:
                existing_user.write({
                    'oauth_provider_id': provider,
                    'oauth_uid': oauth_uid,
                    'oauth_access_token': params['access_token'],
                })
                return existing_user.login

        if self.env.context.get('no_user_creation'):
            return None

        state = json.loads(params['state'])
        token = state.get('t')
        values = self._generate_signup_values(provider, validation, params)
        try:
            login, _ = self.signup(values, token)
            return login
        except (SignupError, UserError):
            raise AccessDenied() from None
