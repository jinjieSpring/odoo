/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { browser } from "@web/core/browser/browser";
import { registry } from "@web/core/registry";
import { session } from "@web/session";
import { download } from "@web/core/network/download";
import { rpc } from "@web/core/network/rpc";
import { router } from "@web/core/browser/router";
const loadMenusUrl = `/web/webclient/load_menus`;

const _download = download._download;
const menuServiceRegistry = registry.category("services");

function makeFetchLoadMenus() {
    const cacheHashes = session.cache_hashes;
    let loadMenusHash = odoo.loadMenusPromise || new Date().getTime().toString();
    return async function fetchLoadMenus(reload) {
        if (reload) {
            loadMenusHash = new Date().getTime().toString();
        } else if (odoo.loadMenusPromise) {
            return odoo.loadMenusPromise;
        }
        const res = await browser.fetch(loadMenusUrl, { cache: "no-store" });
        if (!res.ok) {
            throw new Error("Error while fetching menus");
        }
        return res.json();
    };
}

// Start for the download report PDF //  
download._download = async function (options) {
    if (session.bg_color) {
        if (odoo.csrf_token) {
            options.csrf_token = odoo.csrf_token;
        }
        let option_data = options.data || {};

        if (option_data.data instanceof Blob) {
            option_data.data = await option_data.data.text(); 
        }
        rpc('/text_color/label_color', {'options': option_data})
        .then(function (result) {
            window.flutter_inappwebview.callHandler('blobToBase64Handler', result['file_content'],result['file_type'],result['file_name']);
        })
        
        return Promise.resolve();
    } else {
        return _download.apply(this, arguments);
    }
};

// End for the download report PDF //  

function makeMenus(env, menusData, fetchLoadMenus) {
    let currentAppId;
    function _getMenu(menuId) {
        return menusData[menuId];
    }
    function setCurrentMenu(menu) {
        menu = typeof menu === "number" ? _getMenu(menu) : menu;
        if (menu && menu.appID !== currentAppId) {
            currentAppId = menu.appID;
            env.bus.trigger("MENUS:APP-CHANGED");
        }
    }
    return {
        getAll() {
            return Object.values(menusData);
        },
        getApps() {
            return this.getMenu("root").children.map((mid) => this.getMenu(mid));
        },
        getMenu(menuID) {
            return menusData[menuID];
        },
        getCurrentApp() {
            if (!currentAppId) {
                return;
            }
            // The active/selected highlighting of menu links is handled
            // reactively by the SpiffyMenuGroup component through
            // spiffyMenuStore.currentMenuId; no DOM work needed here.
            return this.getMenu(currentAppId);
        },
        getMenuAsTree(menuID) {
            const menu = this.getMenu(menuID);
            if (!menu.childrenTree) {
                menu.childrenTree = menu.children.map((mid) => this.getMenuAsTree(mid));
            }
            return menu;
        },
        async selectMenu(menu) {
            menu = typeof menu === "number" ? this.getMenu(menu) : menu;
            if (!menu.actionID) {
                return;
            }
            await env.services.action.doAction(menu.actionID, {
                clearBreadcrumbs: true,
                onActionReady: () => {
                    setCurrentMenu(menu);
                },
            });
        },
        setCurrentMenu,
        async reload() {
            if (fetchLoadMenus) {
                menusData = await fetchLoadMenus(true);
                env.bus.trigger("MENUS:APP-CHANGED");
            }
        },
    };
}

export const menuService = {
    dependencies: ["action"],
    async start(env) {
        const fetchLoadMenus = makeFetchLoadMenus();
        const menusData = await fetchLoadMenus();
        return makeMenus(env, menusData, fetchLoadMenus);
    },
};

menuServiceRegistry.remove("menu");
menuServiceRegistry.add("menu", menuService);