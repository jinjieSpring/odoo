/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { rpc } from "@web/core/network/rpc";
import { ColorPallet } from "@spiffy_theme_backend/js/color_pallet";
import { NavBar } from "@web/webclient/navbar/navbar";
import { SwitchCompanyMenu } from "@web/webclient/switch_company_menu/switch_company_menu";
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { useService } from '@web/core/utils/hooks';
import { loadCSS } from "@web/core/assets";
import { onRendered, onWillUnmount, reactive, useEffect, useExternalListener, useState } from "@odoo/owl";
import { routerBus } from "@web/core/browser/router";
import { user } from "@web/core/user";
import { TodoSidebar } from "@spiffy_theme_backend/js/widgets/todo_sidebar";
import { ThemeConfigurator } from "@spiffy_theme_backend/js/widgets/theme_configurator";
import { SpiffyMenuGroup, spiffyMenuStore } from "@spiffy_theme_backend/js/widgets/menu_group";

// Shared reactive theme state. The NavBar fills it from the backend config
// and syncs the matching body classes through effects; the SwitchCompanyMenu
// reads it to conditionally render its header buttons and the language list.
export const spiffyThemeState = reactive({
    darkMode: false,
    sidebarPinned: false,
    todoEnabled: true,
    showEditMode: true,
    isAdmin: true,
    languages: [],
    activeLang: null,
});

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

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

var session_dict = { 'demo': 'demo' }
var methods = {}
let spiffyNavbar = null;

function eventOrigin(ev) {
    const target = ev.target;
    if (!target) {
        return null;
    }
    return target.nodeType === 1 ? target : target.parentElement;
}

function closestAny(node, selector) {
    let best = null;
    for (const part of selector.split(",")) {
        const match = node.closest(part.trim());
        if (!match) {
            continue;
        }
        if (!best || best.contains(match)) {
            best = match;
        }
    }
    return best;
}

function withCurrentTarget(ev, currentTarget) {
    if (ev.currentTarget === currentTarget) {
        return ev;
    }
    return new Proxy(ev, {
        get(target, prop) {
            if (prop === "currentTarget") {
                return currentTarget;
            }
            const value = Reflect.get(target, prop, target);
            return typeof value === "function" ? value.bind(target) : value;
        },
    });
}

// Dynamic menu nodes are inserted after render, and one click can match several
// selectors. Keep the old document-delegation order on the navbar root.
// The app menu groups are rendered by the OWL component
// spiffy_theme_backend.SpiffyMenuGroup; only generic child-menu and drawer
// clicks are still routed through delegation here.
const SPIFFY_MENU_CLICK_ROUTES = [
    [".o_navbar_apps_menu .child_menus", "_childMenuClick"],
    [".o_menu_sections .o_menu_entry_lvl_2, .o_menu_sections .o_nav_entry", "_childMenuClick"],
    [".appdrawer_section .app-box .o_app, .appdrawer_section .search_list_content a", "_ToggleDrawer"],
];
/**
 * Responsible for invoking native methods which called from JavaScript
 *
 * @param {String} name name of action want to perform in mobile
 * @param {Object} args extra arguments for mobile
 *
 * @returns Promise Object
 */

methods['divertColor'] = function () {
    return divertColor('divert_color', session_dict);
};
methods['divertColorRefresh'] = function () {
    return divertColorRefresh('divert_color_refresh', session_dict);
};

NavBar.components = { ...NavBar.components, TodoSidebar, ThemeConfigurator, SpiffyMenuGroup };

patch(NavBar.prototype, {
    async setup(parent, menuData) {
        super.setup();
        var self = this
        spiffyNavbar = this;
        this.todoSidebarState = useState({ visible: false });
        this.configuratorState = useState({ visible: false });
        this.mobileMenu = useState({ open: false });
        this.bookmarkPanel = useState({ show: false });
        this.bookmarks = useState({
            list: [],
            newName: "",
            optionsFor: null,
            renamingFor: null,
            renameValue: "",
        });
        this.zoom = useState({ value: 100 });
        this.magnifier = useState({ open: false });
        this.fullscreen = useState({ active: false });
        this.spiffyTheme = useState(spiffyThemeState);
        // Body-level classes and the zoom target cannot be bound from a
        // template; keep them in sync with the OWL state through effects.
        useEffect(
            (open) => {
                document.body.classList.toggle("backdrop", open);
            },
            () => [this.mobileMenu.open]
        );
        useEffect(
            (show) => {
                document.body.classList.toggle("bookmark_panel_show", show);
            },
            () => [this.bookmarkPanel.show]
        );
        useEffect(
            (darkMode) => {
                document.body.classList.toggle("dark_mode", darkMode);
            },
            () => [spiffyThemeState.darkMode]
        );
        useEffect(
            (pinned) => {
                document.body.classList.toggle("pinned", pinned);
            },
            () => [spiffyThemeState.sidebarPinned]
        );
        useEffect(
            (value) => {
                this._applyZoom(value);
            },
            () => [this.zoom.value]
        );
        this._onBookmarkRouteChange = () => {
            this._syncActiveBookmark();
            // Keep the active app highlight in SpiffyMenuGroup up to date.
            spiffyMenuStore.currentMenuId = this.menuService.getCurrentApp()?.id ?? null;
        };
        routerBus.addEventListener("ROUTE_CHANGE", this._onBookmarkRouteChange);
        onWillUnmount(() => {
            routerBus.removeEventListener("ROUTE_CHANGE", this._onBookmarkRouteChange);
            if (spiffyNavbar === this) {
                spiffyNavbar = null;
            }
        });
        useExternalListener(document, "click", this._closeMagnifierOnOutsideClick);
        useExternalListener(document, "click", this._closeBookmarkOptionsOnOutsideClick, { capture: true });
        useExternalListener(document, "fullscreenchange", this._syncFullscreenState);
        useExternalListener(document, "webkitfullscreenchange", this._syncFullscreenState);
        useExternalListener(document, "mozfullscreenchange", this._syncFullscreenState);
        useExternalListener(document, "msfullscreenchange", this._syncFullscreenState);

        // This function is added for the menu to fix layout issues caused by width rendering problems
        onRendered(() => {
            sleep(150).then(() => {
                self.adapt()
            });
        });
        self.menuService = useService("menu");
        this.currentCompany = user.activeCompany;

        this._searchableMenus = {};
        var menu = this.menuService.getApps()
        for (const menu of this.menuService.getApps()) {
            Object.assign(
                this._searchableMenus,[this.menuService.getMenuAsTree(menu.id)].reduce(findNames,{}),
            );
        }

        this._search_def = false;

        // on reload get mode color
        this._getModeData();
        // on reload add backend theme class
        this.addconfiguratorclass()
        // on reload add bookmark tags in menu
        this._loadBookmarks()

        // The app menu group data is loaded by the SpiffyMenuGroup component.
        // The language list is loaded by the SwitchCompanyMenu patch.

        var size = window.innerWidth;
        var upTo1200 = size <= 1023.98

        this.isIpad = upTo1200
        var currentapp = this.menuService.getCurrentApp();
        spiffyMenuStore.currentMenuId = currentapp?.id ?? null;
        spiffyThemeState.activeLang = user.context.lang;
    },
    onSpiffyMenuClick(ev) {
        const origin = eventOrigin(ev);
        if (!origin) {
            return;
        }
        for (const [selector, method] of SPIFFY_MENU_CLICK_ROUTES) {
            const match = closestAny(origin, selector);
            if (!match) {
                continue;
            }
            this[method](withCurrentTarget(ev, match));
        }
    },
    _closeMagnifierOnOutsideClick(ev) {
        const origin = eventOrigin(ev);
        if (!this.magnifier.open || origin?.closest(".magnifier_section")) {
            return;
        }
        this.magnifier.open = false;
    },
    _closeBookmarkOptionsOnOutsideClick(ev) {
        const origin = eventOrigin(ev);
        if (origin?.closest(".bookmark_options, .bookmark_rename_section")) {
            return;
        }
        this.bookmarks.optionsFor = null;
        this.bookmarks.renamingFor = null;
    },
    _syncFullscreenState() {
        this.fullscreen.active = Boolean(
            document.fullscreenElement ||
            document.webkitIsFullScreen ||
            document.mozFullScreen ||
            document.msFullscreenElement
        );
    },
    getsubMenuItemHref(payload) {
        return `/odoo/${payload.actionPath || "action-" + payload.actionID}`;
    },
    _DebugToggler: function (ev) {
        window.location.search = this.env.debug ? "?debug=" : "?debug=1";
    },

    _mobileHeaderClose: function (ev) {
        this.mobileMenu.open = false;
    },
    // The drawer open/close state lives in this.drawer (apps_menu.js) and is
    // bound to the templates with t-att-class.
    _OpenAppdrawer: function (ev) {
        this._AppdrawerIcons()
        this.drawer.open = !this.drawer.open;
        if (!this.drawer.open) {
            this._resetAppDrawerSearch?.();
        }
    },
    _OpenFavAppdrawer: function (ev) {
        if (!this.drawer.open) {
            this._OpenAppdrawer(ev);
        }
        this.drawer.showFavorites = true;
    },
    _ToggleBookmarkPanel: function (ev) {
        this.bookmarkPanel.show = !this.bookmarkPanel.show;
        rpc('/update/bookmark/panel/show', {
            'bookmark_panel': this.bookmarkPanel.show,
        })
    },

    _CloseAppdrawer: function (ev) {
        this.drawer.open = false;
        this.drawer.showFavorites = false;
        this._resetAppDrawerSearch?.();
        spiffyMenuStore.closeAll();
    },


    _childMenuClick: function (ev) {
        ev.preventDefault();
        var menu = this.menuService.getMenu(ev.currentTarget.dataset.menu)
        // The mini-mode flyout overlays are driven by spiffyMenuStore.
        spiffyMenuStore.headerBg = false;
        if (menu) {
            spiffyMenuStore.activeChildId = menu.id;
            this.onNavBarDropdownItemSelection(menu)
        }
        if (spiffyMenuStore.mini && ev.target.closest('.submenu-group.show')) {
            spiffyMenuStore.openGroupId = null;
            spiffyMenuStore.blur = false;
        }
    },


    _getModeData: function () {
        rpc('/get/dark/mode/data').then((darkMode) => {
            spiffyThemeState.darkMode = Boolean(darkMode);
        })
    },
    addconfiguratorclass: function () {
        const addBodyClass = (name) => {
            if (typeof name !== "string" || !name) {
                return;
            }
            for (const part of name.split(/\s+/)) {
                if (part) {
                    document.body.classList.add(part);
                }
            }
        };
        const setHtmlAttr = (name, value) => {
            if (value == null || value === false) {
                return;
            }
            document.documentElement.setAttribute(name, value);
        };
        const setStyleAttr = (selector, style) => {
            document.querySelectorAll(selector).forEach((el) => el.setAttribute("style", style));
        };
        rpc('/get/model/record').then((rec) => {
            const record = rec.record_dict[0];
            addBodyClass(record.separator);
            addBodyClass(record.tab);
            addBodyClass(record.checkbox);
            addBodyClass(record.button);
            addBodyClass(record.radio);
            addBodyClass(record.popup);
            addBodyClass(record.font_size);
            addBodyClass(record.login_page_style);
            addBodyClass(record.chatter_position);
            addBodyClass(record.list_view_density);
            addBodyClass(record.input_style);

            // Load Font size file based on selected option
            if (rec.record_dict[0].font_size) {
                loadCSS(`/spiffy_theme_backend/static/src/scss/font_sizes/${rec.record_dict[0].font_size}.css`);
            }

            var size = document.documentElement.clientWidth;
            if (size <= 992) {
                addBodyClass("top_menu_horizontal");
                setHtmlAttr("data-menu-position", "top_menu_horizontal");
                setHtmlAttr("data-view-type", "mobile");
                if (record.top_menu_position == "top_menu_vertical_mini") {
                    addBodyClass("top_menu_vertical_mini_mobile");
                }
            } else {
                addBodyClass(record.top_menu_position);
                setHtmlAttr("data-menu-position", record.top_menu_position);
                setHtmlAttr("data-view-type", "desktop");
            }

            // The SpiffyMenuGroup components pick their container and click
            // behavior from these flags.
            spiffyMenuStore.horizontal = document.body.classList.contains("top_menu_horizontal");
            spiffyMenuStore.mini = document.body.classList.contains("top_menu_vertical_mini");
            spiffyMenuStore.vertical = document.body.classList.contains("top_menu_vertical");

            addBodyClass(record.theme_style);
            addBodyClass(record.shape_style);
            addBodyClass(record.loader_style);
            addBodyClass("font_family_" + record.google_font_family);
            var fontLinks = rec.font_dict;
            // Keep fonts local. fonts.googleapis.com fails and can block rendering
            // when the backend has no access to the public internet.
            const systemFontStack = '-apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif';
            const selectedFont = Array.isArray(fontLinks) && fontLinks.length
                ? fontLinks[fontLinks.length - 1]
                : null;
            if (selectedFont && selectedFont.name) {
                document.body.style.fontFamily = `'${selectedFont.name}', ${systemFontStack}`;
            } else {
                document.body.style.fontFamily = systemFontStack;
            }

            setHtmlAttr("data-font-size", record.font_size);
            setHtmlAttr("data-theme-style", record.theme_style);

            if (record.use_custom_drawer_color) {
                addBodyClass("custom_drawer_color");
            } else {
                addBodyClass(record.drawer_color_pallet);
            }

            if (record.attachment_in_tree_view) {
                addBodyClass("show_attachment");
            }
            if (rec.darkmode) {
                spiffyThemeState.darkMode = true;
            }
            if (rec.bookmark_panel) {
                // Synced to the body class by the bookmarkPanel effect.
                this.bookmarkPanel.show = true;
            }
            if (rec.prevent_auto_save) {
                addBodyClass(rec.prevent_auto_save);
            }
            // These flags drive t-if conditions in the SwitchCompanyMenu
            // template instead of removing already-rendered elements.
            spiffyThemeState.todoEnabled = Boolean(rec.todo_list_enable);
            spiffyThemeState.showEditMode = Boolean(rec.show_edit_mode);
            spiffyThemeState.isAdmin = Boolean(rec.is_admin);
            if (rec.pinned_sidebar) {
                spiffyThemeState.sidebarPinned = true;
            }
            if (record.list_view_sticky_header) {
                addBodyClass("list_view_sticky_header");
            }
            if (record.apply_menu_shape_style) {
                addBodyClass("apply_menu_shape_style");
            }
            if (record.vertical_background) {
                addBodyClass("vertical_background");
            }
            if (record.apply_light_bg_img) {
                if (record.light_bg_image) {
                    setStyleAttr(".appdrawer_section", "background-image: url('/web/image/backend.config/" + record.id + "/light_bg_image')");
                }
            }

            if (rec.record_dict[0].vertical_background && rec.record_dict[0].top_menu_position === 'top_menu_vertical') {
                const record = rec.record_dict[0];
                const bgKey = record.top_menu_bg_vertical;
                const imageMap = {
                    top_menu_vertical_bg1: {
                        field: "vertical_mini_bg_image_one",
                        fallback: "/spiffy_theme_backend/static/description/top-menu-v2-bg1.jpg"
                    },
                    top_menu_vertical_bg2: {
                        field: "vertical_mini_bg_image_two",
                        fallback: "/spiffy_theme_backend/static/description/top-menu-v2-bg2.jpg"
                    },
                    top_menu_vertical_bg3: {
                        field: "vertical_mini_bg_image_three",
                        fallback: "/spiffy_theme_backend/static/description/top-menu-v2-bg3.jpg"
                    },
                    top_menu_vertical_bg4: {
                        field: "top_menu_custom_bg_vertical",
                        fallback: "/spiffy_theme_backend/static/description/top-menu-v2-bg4.jpg"
                    }
                };

                const config = imageMap[bgKey];
                if (config) {
                    const imageExists = record[config.field];
                    const imageUrl = imageExists
                        ? `/web/image/backend.config/${record.id}/${config.field}`
                        : config.fallback;

                    const style = `background: linear-gradient(to bottom, rgba(27, 27, 27, 1) 0%, rgba(27, 27, 27, 0.7) 60%, rgba(27, 27, 27, 0) 100%), url('${imageUrl}') !important; background-size: cover !important; background-position: center !important;`;

                    requestAnimationFrame(()=>{
                        setStyleAttr(".o_main_navbar", style);
                        setStyleAttr(".top_menu_vertical.top_menu_vertical_mini_mobile .o_main_navbar", style);
                    })
                }
            }

            var pallet_name = rec.record_dict[0].color_pallet
            var apply_color = new ColorPallet(this)
            if (rec.record_dict[0].use_custom_colors) {
                apply_color['custom_color_pallet'](rec.record_dict[0])

            } else {
                apply_color[pallet_name]()
            }

            var app_drawer_pallet_name = rec.record_dict[0].drawer_color_pallet
            var app_drawer_apply_color = new ColorPallet(this)
            if (rec.record_dict[0].use_custom_drawer_color) {
                app_drawer_apply_color['custom_app_drawer_color_pallet'](rec.record_dict[0])
            }

            var menu_shape_apply_color = new ColorPallet(this)
            menu_shape_apply_color['menu_shape_color_pallet'](rec.record_dict[0])

            document.body.setAttribute("headerMode", "visible");
        })
    },
    async _loadBookmarks() {
        const rec = await rpc('/get/bookmark/link', {});
        this.bookmarks.list = (rec || []).map((value) => ({
            id: value.id,
            name: value.name,
            title: value.title,
            url: value.url,
            active: false,
        }));
        this._syncActiveBookmark();
    },
    _syncActiveBookmark() {
        const clean = (url) => (url || "").replace(/\?$/, "");
        const path = window.location.pathname;
        const here = new Set([
            clean(path + window.location.search + window.location.hash),
            clean(path + "?" + window.location.hash),
            clean(path + window.location.hash),
        ]);
        for (const bookmark of this.bookmarks.list) {
            bookmark.active = here.has(clean(bookmark.url));
        }
    },
    _getCurrentPageName: function () {
        const items = document.querySelectorAll(".o_control_panel ol.breadcrumb li");
        this.bookmarks.newName = [...items]
            .map((li) => li.textContent.trim())
            .filter(Boolean)
            .join(" | ");
    },
    _saveBookmarkPage: async function () {
        var pathname = window.location.pathname
        var hash = window.location.hash
        var url = pathname + '?' + hash
        var name = this.bookmarks.newName
        await rpc('/add/bookmark/link', {
            'name': name,
            'url': url,
            'title': name.substr(0, 2),
        });
        this.bookmarks.newName = "";
        await this._loadBookmarks();
    },
    _showbookmarkoptions: function (bookmark, ev) {
        ev.preventDefault();
        this.bookmarks.renamingFor = null;
        this.bookmarks.optionsFor = bookmark.id;
    },
    _startRenameBookmark: function (bookmark) {
        this.bookmarks.optionsFor = null;
        this.bookmarks.renamingFor = bookmark.id;
        this.bookmarks.renameValue = bookmark.name;
    },
    _cancelRenameBookmark: function () {
        this.bookmarks.renamingFor = null;
    },
    _RemoveBookmark: async function (bookmark_id) {
        this.bookmarks.optionsFor = null;
        await rpc('/remove/bookmark/link', {
            'bookmark_id': bookmark_id,
        });
        await this._loadBookmarks();
    },
    _UpdateBookmark: async function (bookmark_id, bookmark_name) {
        await rpc('/update/bookmark/link', {
            'bookmark_id': bookmark_id,
            'bookmark_name': bookmark_name,
            'bookmark_title': bookmark_name.substr(0, 2),
        });
        this.bookmarks.renamingFor = null;
        await this._loadBookmarks();
    },
    // The zoom is applied to the action content, which lives outside the
    // NavBar's OWL tree, so the effect above pushes the style onto it
    // whenever the reactive zoom value changes.
    _zoomTarget: function () {
        const children = document.querySelectorAll(".o_content > div");
        if (children.length > 1) {
            return document.querySelector(".o_action_manager > .o_view_controller > .o_content");
        }
        return children[0];
    },
    _applyZoom: function (value) {
        const target = this._zoomTarget();
        if (!target) {
            return;
        }
        if (value === 100) {
            target.style.width = "";
            target.style.transformOrigin = "";
            target.style.transform = "";
            return;
        }
        target.style.width = ((100 / value) * 100).toFixed(4) + "%";
        target.style.transformOrigin = "left top";
        target.style.transform = `scale(${value / 100})`;
    },
    _toggleMagnifier: function () {
        this.magnifier.open = !this.magnifier.open;
    },
    _magnifierZoomOut: function () {
        if (this.zoom.value - 10 > 20) {
            this.zoom.value -= 10;
        }
    },
    _magnifierZoomIn: function () {
        if (this.zoom.value + 10 < 210) {
            this.zoom.value += 10;
        }
    },
    _magnifierZoomReset: function () {
        this.zoom.value = 100;
    },
    _FullScreenMode: function (ev) {
        var elem = document.documentElement;
        if (this.fullscreen.active) {
            if (document.exitFullscreen) {
                document.exitFullscreen();
            } else if (document.webkitExitFullscreen) { /* Safari */
                document.webkitExitFullscreen();
            } else if (document.msExitFullscreen) { /* IE11 */
                document.msExitFullscreen();
            }
        } else {
            if (elem.requestFullscreen) {
                elem.requestFullscreen();
            } else if (elem.webkitRequestFullscreen) { /* Safari */
                elem.webkitRequestFullscreen();
            } else if (elem.msRequestFullscreen) { /* IE11 */
                elem.msRequestFullscreen();
            }
        }
        // this.fullscreen.active is synced by the fullscreenchange listener.
    },
    // The configurator is the OWL component spiffy_theme_backend.ThemeConfigurator;
    // the NavBar only owns its visibility flag.
    _openConfigModal: function () {
        this.configuratorState.visible = !this.configuratorState.visible;
    },

    _ChangeThemeModeCLicked: function (ev) {
        this._ChangeThemeMode(!spiffyThemeState.darkMode)
    },
    _ChangeThemeMode: function (darkmode) {
        // The body class is synced by an effect and the theme variables are
        // plain CSS under body.dark_mode; only the state and the persisted
        // user preference are handled here.
        spiffyThemeState.darkMode = Boolean(darkmode);
        rpc('/active/dark/mode', { 'dark_mode': darkmode ? 'on' : 'off' })
    },
    _ChangeSidebarBehaviour: function (ev) {
        spiffyThemeState.sidebarPinned = !spiffyThemeState.sidebarPinned;
        rpc('/sidebar/behavior/update', {
            'sidebar_pinned': spiffyThemeState.sidebarPinned,
        })
    },

    _menuInfo: function (key) {
        return this._drawersearchableMenus[key];
    },

    _showSearchbarModal: function (ev) {
        if (this.env && this.env.services && this.env.services.command) {
            const commandService = this.env.services.command;
            if (commandService) {
                commandService.openMainPalette();
            }
        }
        if (ev) {
            ev.preventDefault();
            ev.stopPropagation();
        }
    },

    //  TO DO LIST FUNCTIONS
    // The sidebar is the OWL component spiffy_theme_backend.TodoSidebar; the
    // NavBar only owns its visibility flag.
    _openToDoList: function () {
        this.todoSidebarState.visible = !this.todoSidebarState.visible;
    },
});


patch(SwitchCompanyMenu.prototype, {
    setup() {
        super.setup();
        this.spiffyTheme = useState(spiffyThemeState);
        this.actionService = useService("action");
        this._loadSpiffyLanguages();
    },
    async _loadSpiffyLanguages() {
        const langs = await rpc('/get/active/lang');
        spiffyThemeState.languages = Array.isArray(langs) ? langs : [];
        spiffyThemeState.activeLang = user.context.lang;
    },
    async _selectLanguage(lang) {
        await rpc('/change/active/lang', { 'lang': lang });
        this.actionService.doAction("reload_context");
    },
    _DebugToggler(ev) {
        spiffyNavbar?._DebugToggler(ev);
    },
    _openConfigModal(ev) {
        spiffyNavbar?._openConfigModal(ev);
    },
    _ChangeSidebarBehaviour(ev) {
        spiffyNavbar?._ChangeSidebarBehaviour(ev);
    },
    _openToDoList(ev) {
        spiffyNavbar?._openToDoList(ev);
    },
    _ChangeThemeModeCLicked(ev) {
        spiffyNavbar?._ChangeThemeModeCLicked(ev);
    },
});


function divertColor(name, session_dict) {
    var result = ""

    window.flutter_inappwebview.callHandler('blobToBase64Handler', 'Hello from WebView!', result);
    var is_body_color = session.bg_color
    return is_body_color
}

function divertColorRefresh(name, session_dict) {
    var result = ""

    window.flutter_inappwebview.callHandler('blobToBase64Handler', 'Hello from WebView Refresh!', result);
    var is_body_color = session.bg_color
    return is_body_color
}

export default {
    session_dict: session_dict,
    methods: methods
};
