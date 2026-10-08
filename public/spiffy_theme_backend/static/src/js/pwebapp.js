/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { rpc } from "@web/core/network/rpc";

// PWA bootstrap: register the service worker when PWA is enabled for this
// database, otherwise unregister any leftover workers from a previous setup.
// The install prompt itself is handled by the browser.
rpc('/pwa/enabled', {}).then(function (enabled_pwa) {
    if (enabled_pwa) {
        if ('serviceWorker' in navigator) {
            navigator.serviceWorker.register('/service_worker.js');
        }
    } else if (navigator.serviceWorker) {
        navigator.serviceWorker.getRegistrations().then(function (registrations) {
            registrations.forEach((swregistration) => {
                swregistration.unregister();
                console.log('ServiceWorker removed Peacefully');
            });
        }).catch(function (error) {
            console.log('Service worker unregistration failed: ', error);
        });
    }
});
