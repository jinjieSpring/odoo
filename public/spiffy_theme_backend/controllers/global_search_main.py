# -*- coding: utf-8 -*-
# Part of Bizople Solutions Pvt. Ltd.
# Licensed under the Bizople Proprietary License v1.0.
# Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import time

from odoo import http
from odoo.http import request

# Models that are either technical or too large to scan on each keystroke.
_SKIP_MODELS = {
    'ir.attachment',
    'ir.logging',
    'ir.model',
    'ir.model.fields',
    'ir.ui.menu',
    'ir.ui.view',
    'bus.bus',
    'mail.mail',
    'mail.message',
    'mail.notification',
}

# (dbname, uid, lang, menu write stamp, groups) -> [(model, label), ...]
_SEARCH_TARGET_CACHE = {}
_SEARCH_TARGET_CACHE_LIMIT = 64
# dbname -> (monotonic, menu write stamp). Avoids a menu query on every keystroke.
_MENU_STAMP_CACHE = {}
_MENU_STAMP_TTL = 60
# (dbname, uid) -> model names that recently returned rows, most recent first.
_HOT_MODELS = {}
_HOT_MODEL_LIMIT = 16
# A keystroke searches recent hits first, then stops after this many models
# or this much time once it already has rows.
_MAX_MODELS_PER_SEARCH = 30
_SEARCH_BUDGET_SEC = 0.2


class SpiffySpaceSearch(http.Controller):

    def _menu_stamp(self, env):
        now = time.monotonic()
        cached = _MENU_STAMP_CACHE.get(env.cr.dbname)
        if cached and now - cached[0] < _MENU_STAMP_TTL:
            return cached[1]
        menu_stamp = env['ir.ui.menu'].sudo().search_read(
            [], ['write_date'], order='write_date desc', limit=1,
        )
        stamp = menu_stamp[0]['write_date'] if menu_stamp else False
        _MENU_STAMP_CACHE[env.cr.dbname] = (now, stamp)
        return stamp

    def _ordered_targets(self, targets):
        hot = _HOT_MODELS.get((request.env.cr.dbname, request.env.uid), ())
        rank = {name: index for index, name in enumerate(hot)}
        return sorted(targets, key=lambda item: rank.get(item[0], len(rank)))

    def _remember_hit(self, model_name):
        key = (request.env.cr.dbname, request.env.uid)
        hot = [name for name in _HOT_MODELS.get(key, ()) if name != model_name]
        hot.insert(0, model_name)
        _HOT_MODELS[key] = tuple(hot[:_HOT_MODEL_LIMIT])

    def _search_targets(self):
        """Models behind menus the user can open, with a stored name field."""
        env = request.env
        stamp = self._menu_stamp(env)
        groups = tuple(sorted(env.user.group_ids.ids))
        key = (env.cr.dbname, env.uid, env.lang, stamp, groups)
        cached = _SEARCH_TARGET_CACHE.get(key)
        if cached is not None:
            return cached

        menu_rows = env['ir.ui.menu'].search_read(
            [('action', '!=', False)], ['action'],
        )
        action_ids = []
        seen_actions = set()
        for row in menu_rows:
            action = row.get('action') or ''
            if not action.startswith('ir.actions.act_window,'):
                continue
            action_id = int(action.split(',', 1)[1])
            if action_id in seen_actions:
                continue
            seen_actions.add(action_id)
            action_ids.append(action_id)

        targets = []
        if action_ids:
            action_rows = env['ir.actions.act_window'].sudo().browse(action_ids).read(['res_model'])
            model_by_action = {row['id']: row['res_model'] for row in action_rows}
            seen_models = set()
            for action_id in action_ids:
                model_name = model_by_action.get(action_id)
                if (
                    not model_name
                    or model_name in seen_models
                    or model_name in _SKIP_MODELS
                    or model_name not in env
                ):
                    continue
                Model = env[model_name]
                if Model._abstract or Model._transient:
                    continue
                rec_name = Model._rec_name
                field = Model._fields.get(rec_name) if rec_name else None
                if not field or not field.store or field.type not in ('char', 'text'):
                    continue
                if not Model.has_access('read'):
                    continue
                seen_models.add(model_name)
                targets.append((model_name, Model._description or model_name))

        if len(_SEARCH_TARGET_CACHE) >= _SEARCH_TARGET_CACHE_LIMIT:
            _SEARCH_TARGET_CACHE.clear()
        _SEARCH_TARGET_CACHE[key] = targets
        return targets

    @http.route('/spiffy/global/search', type='jsonrpc', auth='user')
    def colon_search(self, search):
        search = (search or '').strip()
        if len(search) < 2:
            return []

        results = []
        started = time.monotonic()
        scanned = 0
        for model_name, model_label in self._ordered_targets(self._search_targets()):
            if len(results) >= 10 or scanned >= _MAX_MODELS_PER_SEARCH:
                break
            if scanned >= 8 and results and (time.monotonic() - started) >= _SEARCH_BUDGET_SEC:
                break
            scanned += 1
            try:
                pairs = request.env[model_name].name_search(search, operator='ilike', limit=3)
            except Exception:
                continue
            if pairs:
                self._remember_hit(model_name)
            for rec_id, display_name in pairs:
                results.append({
                    'model': model_name,
                    'model_name': model_label,
                    'id': rec_id,
                    'display_name': display_name,
                    'action': f"/web#model={model_name}&id={rec_id}&view_type=form",
                })
                if len(results) >= 10:
                    break
        return results
