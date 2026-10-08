/** @odoo-module */

import { Component, onWillStart, reactive, useState } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";

// Shared reactive state for the spiffy app menu groups. The NavBar writes the
// layout flags (horizontal / mini / vertical) and the current menu id, the
// SpiffyMenuGroup components read everything and render from it.
export const spiffyMenuStore = reactive({
    loaded: false,
    horizontal: false,
    mini: false,
    vertical: false,
    groups: [],
    menus: [],
    openGroupId: null,
    expandedAppId: null,
    currentMenuId: null,
    activeChildId: null,
    blur: false,
    headerBg: false,
    _loading: null,

    load(menuService) {
        if (this._loading) {
            return this._loading;
        }
        this._loading = (async () => {
            const apps = menuService.getApps();
            const rec = await rpc("/get/irmenu/icondata", { menu_ids: apps.map((app) => app.id) });
            for (const app of apps) {
                const current = rec[app.id] && rec[app.id][0];
                if (!current) {
                    continue;
                }
                app.use_icon = current.use_icon;
                app.icon_class_name = current.icon_class_name;
                app.icon_img = current.icon_img;
                app.spiffy_app_group_id = current.spiffy_app_group_id;
            }
            this.groups = rec.spiffy_app_group || [];
            this.menus = apps;
            this.loaded = true;
        })().catch((error) => {
            this._loading = null;
            throw error;
        });
        return this._loading;
    },

    closeAll() {
        this.openGroupId = null;
        this.expandedAppId = null;
        this.blur = false;
        this.headerBg = false;
    },
});

export class SpiffyMenuGroup extends Component {
    static template = "spiffy_theme_backend.SpiffyMenuGroup";
    static props = {
        placement: { type: String }, // "sidebar" | "drawer"
    };

    setup() {
        this.menuService = useService("menu");
        this.store = useState(spiffyMenuStore);
        onWillStart(() => this.store.load(this.menuService));
    }

    // Only the container matching the current layout mode renders content,
    // mirroring the old "first matching container gets the menu" behavior.
    get isActive() {
        const expected = this.store.horizontal ? "drawer" : "sidebar";
        return this.props.placement === expected;
    }

    get ungroupedMenus() {
        return this.store.menus.filter((menu) => !menu.spiffy_app_group_id);
    }

    menusInGroup(group) {
        const ids = group.group_menu_list_ids || [];
        return this.store.menus.filter((menu) => ids.includes(menu.id));
    }

    getMenuItemHref(menu) {
        return `/odoo/${menu.actionPath || "action-" + menu.actionID}`;
    }

    isAppActive(menu) {
        return this.store.expandedAppId === menu.id || this.store.currentMenuId === menu.id;
    }

    submenuGroupClasses(group) {
        const open = this.store.openGroupId === group.id;
        return {
            "d-none": !open,
            active: open && this.store.horizontal,
            show: open && !this.store.horizontal,
        };
    }

    onGroupClick(group) {
        const store = this.store;
        const wasOpen = store.openGroupId === group.id;
        store.openGroupId = wasOpen ? null : group.id;
        if (store.mini) {
            store.blur = !wasOpen;
            store.headerBg = !wasOpen;
        }
    }

    onTopAppClick(menu, ev) {
        const store = this.store;
        if (store.horizontal) {
            // Clicking any app link closes the open group popup.
            store.openGroupId = null;
            return;
        }
        if (store.mini) {
            if (ev.target.classList.contains("dropdown-btn")) {
                ev.preventDefault();
            }
            store.expandedAppId = store.expandedAppId === menu.id ? null : menu.id;
            store.openGroupId = null;
            store.blur = false;
            store.headerBg = false;
            return;
        }
        if (store.vertical) {
            const wasOpen = store.expandedAppId === menu.id;
            store.expandedAppId = wasOpen ? null : menu.id;
            if (!menu.spiffy_app_group_id) {
                store.openGroupId = null;
            }
        }
    }

    // A click anywhere inside an open horizontal group popup closes it.
    onSubmenuGroupClick() {
        if (this.store.horizontal) {
            this.store.openGroupId = null;
        }
    }

    // Clicking a deep child keeps its top-level app expanded (vertical mode).
    onHeaderSubMenuClick(menu) {
        if (this.store.vertical) {
            this.store.expandedAppId = menu.id;
        }
    }

    // Used by the AllmenuRecursive template to highlight the ancestors of the
    // currently active child menu and keep their collapses open.
    hasActiveDescendant(menu) {
        const id = this.store.activeChildId;
        if (!id) {
            return false;
        }
        const walk = (node) => node.id === id || (node.childrenTree || []).some(walk);
        return (menu.childrenTree || []).some(walk);
    }

    onOverlayClick() {
        this.store.closeAll();
    }
}
