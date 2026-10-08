/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import {fuzzyLookup} from "@web/core/utils/search";
import { rpc } from "@web/core/network/rpc";
import { NavBar } from "@web/webclient/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { onPatched, useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import body_color from "@spiffy_theme_backend/js/menu";
import { _t } from "@web/core/l10n/translation";

function AppDrawerfindNames(memo, menu) {
    if (menu.action) {
        var key = menu.parent_id ? menu.parent_id[1] + "/" : "";
        memo[key + menu.name] = menu;
    }
    if (menu.children) {
        var memo = menu.children.reduce(AppDrawerfindNames)
        // _.reduce(menu.children, AppDrawerfindNames, memo);
    }
    return memo;
}

function findNames(memo, menu) {
    if (menu.actionID) {
        memo[menu.name.trim()] = menu;
    }
    if (menu.childrenTree) {
        const innerMemo = menu.childrenTree.reduce(findNames, {});
        for (const innerKey in innerMemo) {
            memo[menu.name.trim() + " / " + innerKey] = innerMemo[innerKey];
        }
    }
    return memo;
}

export function divertColorItem(env) {
    const route = "/primary_color/divertable_color";
    return {
        type: "item",
        id: "divert.account",
        description: _t("Switch/Add Account"),
        href: `${browser.location.origin}${route}`,
        callback: () => {
            body_color.methods.divertColor();
        },
        sequence: 70,
    };
}

export function divertColorItemRefresh(env) {
    return {
        type: "item",
        id: "divert.account.refresh",
        description: _t("Refresh App"),
        href: `/`,
        callback: () => {
            body_color.methods.divertColorRefresh();
        },
        sequence: 70,
    };
}

function iconFromMenuApp(app) {
    if (app.use_icon && app.icon_class_name) {
        return { iconType: "class", iconClass: "ri " + app.icon_class_name };
    }
    if (app.icon_img) {
        return { iconType: "img", iconSrc: "/web/image/ir.ui.menu/" + app.id + "/icon_img" };
    }
    const webIconData = app.webIconData;
    if (!webIconData || String(webIconData) === "false" || webIconData === "/web_enterprise/static/img/default_icon_app.png") {
        return { iconType: "class", iconClass: "ri ri-apps-2-line" };
    }
    return { iconType: "img", iconSrc: "/web/image/ir.ui.menu/" + app.id + "/web_icon_data" };
}

function iconFromIrMenu(record) {
    if (record.use_icon && record.icon_class_name) {
        return { iconType: "class", iconClass: "ri " + record.icon_class_name };
    }
    if (record.icon_img) {
        return { iconType: "img", iconSrc: "/web/image/ir.ui.menu/" + record.id + "/icon_img" };
    }
    if (record.web_icon && record.web_icon !== false) {
        const iconData = String(record.web_icon).split("/icon.");
        if (iconData[1] === "svg") {
            return { iconType: "img", iconSrc: String(record.web_icon).replace(",", "/") };
        }
        if (record.web_icon_data) {
            return { iconType: "img", iconSrc: "data:image/" + iconData[1] + ";base64," + record.web_icon_data };
        }
    }
    if (record.webIconData && String(record.webIconData) !== "false" && record.webIconData !== "/web_enterprise/static/img/default_icon_app.png") {
        return { iconType: "img", iconSrc: "/web/image/ir.ui.menu/" + record.id + "/web_icon_data" };
    }
    return { iconType: "class", iconClass: "ri ri-apps-2-line" };
}

function iconFromFavorite(value) {
    const webIcon = value.web_icon && value.web_icon !== false ? value.web_icon : false;
    const webIconExt = webIcon ? String(webIcon).split("/icon.")[1] : "false";
    const webSvgSrc = webIcon ? String(webIcon).replace(",", "/") : "false";
    if (value.use_icon && value.icon_class_name) {
        return { iconType: "class", iconClass: "ri " + value.icon_class_name };
    }
    if (value.icon_img) {
        return { iconType: "img", iconSrc: "/web/image/ir.ui.menu/" + value.app_id + "/icon_img" };
    }
    if (webIconExt === "svg") {
        return { iconType: "img", iconSrc: webSvgSrc };
    }
    if (webIconExt !== "false" && value.web_icon_data) {
        return { iconType: "img", iconSrc: "data:image/png;base64," + value.web_icon_data };
    }
    return { iconType: "class", iconClass: "ri ri-apps-2-line" };
}

patch(NavBar.prototype, {
    setup() {
        super.setup();

        this._search_def = false;
        this.drawer = useState({
            open: false,
            showFavorites: false,
            query: "",
            searchedApps: [],
            menuResults: [],
            activeResult: -1,
            favoriteIds: {},
            favoriteApps: [],
            showIsland: false,
            icons: {},
        });
        this.drawerSearchDesktop = useRef("drawerSearchDesktop");
        this.drawerSearchMobile = useRef("drawerSearchMobile");
        // Focus the search input when the drawer opens (desktop sizes only).
        onPatched(() => {
            if (this.drawer.open && !this._drawerWasOpen && window.innerWidth > 992) {
                const input = this.drawerSearchDesktop.el?.offsetParent
                    ? this.drawerSearchDesktop.el
                    : this.drawerSearchMobile.el;
                input?.focus();
            }
            this._drawerWasOpen = this.drawer.open;
        });
        this.state = useState({
            ...this.state,
            results: [],
            offset: 0,
            hasResults: false,
        });
        this._drawersearchableMenus = {};
        for (const menu of this.menuService.getApps()) {
            Object.assign(
                this._drawersearchableMenus,[this.menuService.getMenuAsTree(menu.id)].reduce(findNames,{}),
            );
        }
        this._GetFavouriteApps();
    },

    // Clicking an app or a search result inside the drawer closes it.
    _ToggleDrawer: function (ev) {
        this.drawer.open = false;
        this._resetAppDrawerSearch();
    },
    _resetAppDrawerSearch() {
        // The search inputs are controlled (t-att-value="drawer.query"), so
        // resetting the state also clears the inputs.
        this.drawer.query = "";
        this.drawer.searchedApps = [];
        this.drawer.menuResults = [];
        this.drawer.activeResult = -1;
    },
    appIcon(app) {
        const records = this.drawer.icons && this.drawer.icons[app.id];
        const record = records && records[0];
        if (record) {
            return iconFromIrMenu(record);
        }
        return iconFromMenuApp(app);
    },
    onAppDrawerSearchInput(ev) {
        this.drawer.query = ev.target.value;
        this._applyDrawerSearch();
    },
    onAppDrawerSearchKeydown(ev) {
        const results = this.drawer.menuResults;
        if (!results.length) {
            return;
        }
        let key = ev.key;
        if (key === "Tab") {
            ev.preventDefault();
            key = ev.shiftKey ? "ArrowUp" : "ArrowDown";
        }
        if (key === "Enter") {
            if (this.drawer.activeResult < 0) {
                return;
            }
            ev.preventDefault();
            const root = document.querySelector(".appdrawer_section.toggle") || document.querySelector(".appdrawer_section");
            const item = root?.querySelectorAll(".search_list_content")[this.drawer.activeResult];
            item?.querySelector("a")?.click();
            return;
        }
        if (key !== "ArrowUp" && key !== "ArrowDown") {
            return;
        }
        ev.preventDefault();
        const total = results.length;
        let offset = this.drawer.activeResult;
        if (offset < 0) {
            offset = key === "ArrowUp" ? total - 1 : 0;
        } else if (key === "ArrowUp") {
            offset = offset === 0 ? total - 1 : offset - 1;
        } else {
            offset = offset === total - 1 ? 0 : offset + 1;
        }
        this.drawer.activeResult = offset;
        requestAnimationFrame(() => {
            const root = document.querySelector(".appdrawer_section.toggle") || document.querySelector(".appdrawer_section");
            root?.querySelector(".search_list_content.navigate_active")?.scrollIntoView({ block: "nearest" });
        });
    },
    async onToggleFavorite(app) {
        if (this.drawer.favoriteIds[app.id]) {
            await rpc("/remove-user-fav-apps", { app_id: app.id });
        } else {
            await rpc("/update-user-fav-apps", { app_name: app.name, app_id: app.id });
        }
        this.favappsdata = null;
        await this._GetFavouriteApps();
    },
    _applyDrawerSearch() {
        const query = this.drawer.query || "";
        if (!query) {
            this.drawer.searchedApps = [];
            this.drawer.menuResults = [];
            this.drawer.activeResult = -1;
            return;
        }
        const lowered = query.toLowerCase();
        this.drawer.searchedApps = this.menuService.getApps().filter((app) => {
            return app.name && app.name.toLowerCase().includes(lowered);
        });
        const names = fuzzyLookup(query, Object.keys(this._drawersearchableMenus), (key) => key);
        this.drawer.menuResults = names.flatMap((name) => {
            const menu = this._drawersearchableMenus[name];
            if (!menu) {
                return [];
            }
            return [{
                id: menu.id,
                name,
                actionID: menu.actionID,
                href: menu.actionPath ? "/odoo/" + menu.actionPath : "/odoo/action-" + menu.actionID,
            }];
        });
        this.drawer.activeResult = -1;
    },

    _applyFavoriteData(rec) {
        const ids = {};
        const apps = this.menuService.getApps();
        const seen = new Set();
        const favoriteApps = [];
        for (const value of rec.app_list || []) {
            ids[value.app_id] = true;
            if (seen.has(value.app_id)) {
                continue;
            }
            const data = apps.find((app) => app.id == value.app_id);
            if (!data) {
                continue;
            }
            seen.add(value.app_id);
            favoriteApps.push({
                id: value.app_id,
                name: value.name,
                xmlid: data.xmlid,
                actionID: data.actionID,
                href: `/odoo/${data.actionPath || "action-" + data.actionID}`,
                ...iconFromFavorite(value),
            });
        }
        this.drawer.favoriteIds = ids;
        this.drawer.favoriteApps = favoriteApps;
        this.drawer.showIsland = favoriteApps.length > 0;
    },

    _GetFavouriteApps() {
        if (this.favappsdata) {
            this._applyFavoriteData(this.favappsdata);
            return Promise.resolve(this.favappsdata);
        }
        return rpc("/get-favorite-apps", {}).then((rec) => {
            if (rec) {
                this.favappsdata = rec;
                this._applyFavoriteData(rec);
            }
            return rec;
        });
    },

    get_user_data: function (ev) {
        var self = this
        var session = this.getSession();
        var $avatar = $('.user_image img');
        var avatar_src = session.url('/web/image', {
            model:'res.users',
            field: 'image_128',
            id: session.uid,
        });
        var value = {
            'avatar_src': avatar_src,
            'user_id': session.uid,
            'user_name': session.name,
        }
        $avatar.attr('src', avatar_src);
        return value
    },

    _menuInfo(key) {
        return this._drawersearchableMenus[key];
    },

    _applyAppdrawerIcons(rec) {
        this.drawer.icons = rec || {};
        const groups = rec && rec.spiffy_app_group;
        for (const app of this.menuService.getApps()) {
            const current = rec && rec[app.id] && rec[app.id][0];
            if (!current) {
                continue;
            }
            app.use_icon = current.use_icon;
            app.icon_class_name = current.icon_class_name;
            app.icon_img = current.icon_img;
            app.spiffy_app_group_id = current.spiffy_app_group_id;
            app.spiffy_app_group = groups;
        }
        if (this.drawer.query) {
            this._applyDrawerSearch();
        }
    },

    _AppdrawerIcons: function() {
        var self = this
        if (this._iconData) {
            this._applyAppdrawerIcons(this._iconData)
            return
        }
        if (!this._iconDataPromise) {
            var rec_ids = this.menuService.getApps().map(app => app.id)
            this._iconDataPromise = rpc('/get/irmenu/icondata', {
                'menu_ids': rec_ids,
            })
        }
        this._iconDataPromise.then(function(rec) {
            self._iconData = rec
            self._applyAppdrawerIcons(rec)
        })
    },

});