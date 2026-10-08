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
            document.querySelectorAll(".ios-prompt").forEach((iosPrompt) => {
                iosPrompt.style.display = "block";
                iosPrompt.addEventListener("click", () => {
                    iosPrompt.style.display = "none";
                });
            });
        }

        if ('serviceWorker' in navigator) {
            if(!navigator.onLine){
                document.querySelectorAll(".pwa_offline").forEach((appOffline) => {
                    appOffline.style.display = "block";
                });
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