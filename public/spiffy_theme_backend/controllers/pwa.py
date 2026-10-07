# -*- coding: utf-8 -*-
# Part of Bizople Solutions Pvt. Ltd.
# Licensed under the Bizople Proprietary License v1.0.
# Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

from odoo import http
from odoo.http import request
from odoo.addons.web.controllers import webmanifest

class WebManifest(webmanifest.WebManifest):
    def _get_webmanifest(self):
        manifest = super()._get_webmanifest()
        company = request.env.company

        manifest.update({
            "name": company.app_name_pwa or manifest.get("name"),
            "short_name": company.short_name_pwa or manifest.get("short_name"),
            "description": company.description_pwa or manifest.get("description"),
            "start_url": company.start_url_pwa or manifest.get("start_url"),
            "background_color": company.background_color_pwa or manifest.get("background_color"),
            "theme_color": company.theme_color_pwa or manifest.get("theme_color"),
        })
        manifest["icons"] = [
            {
                "src": f"/web/image/res.company/{company.id}/image_192_pwa/192x192",
                "sizes": "192x192",
                "type": "image/png",
            },
            {
                "src": f"/web/image/res.company/{company.id}/image_512_pwa/512x512",
                "sizes": "512x512",
                "type": "image/png",
            }
        ]

        shortcuts = []
        for sc in company.pwa_shortcuts_ids:
            shortcuts.append({
                "name": sc.name,
                "short_name": sc.short_name,
                "description": sc.description,
                "url": sc.url,
                "icons": [{
                    "src": f"/web/image/pwa.shortcuts/{sc.id}/image_192_shortcut/100x100",
                    "sizes": "100x100",
                    "type": "image/png",
                }]
            })

        manifest["shortcuts"] = shortcuts
        return manifest