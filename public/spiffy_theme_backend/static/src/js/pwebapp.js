/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { rpc } from "@web/core/network/rpc";

rpc('/pwa/enabled',{}).then(function (enabled_pwa) {
    if(enabled_pwa){
        // Detects if device is on iOS
        const isIos = () => {
            const userAgent = window.navigator.userAgent.toLowerCase();
            return /iphone|ipad|ipod/.test( userAgent );
        }
        // Detects if device is in standalone mode
        const isInStandaloneMode = () => ('standalone' in window.navigator) && (window.navigator.standalone);

        // Checks if should display install popup notification:
        if (isIos() && !isInStandaloneMode()) {
            var iosPrompt = $(".ios-prompt");
            iosPrompt.show();
            $(iosPrompt).click(function() {
                iosPrompt.hide();
            });
        }

        if ('serviceWorker' in navigator) {
            if(!navigator.onLine){
                var app_offline = $('.pwa_offline');
                if(app_offline){
                    app_offline.show();
                }
            }
            navigator.serviceWorker.register('/service_worker.js');
        }
    }else{
        if (navigator.serviceWorker) {
            // TODO: fix _.each reference error
            navigator.serviceWorker.getRegistrations().then(function (registrations) {
                registrations.forEach((swregistration) => {
                    swregistration.unregister();
                    console.log('ServiceWorker removed Peacefully');
                });
            }).catch(function (error) {
                console.log('Service worker unregistration failed: ', error);
            });
        }
    }
});