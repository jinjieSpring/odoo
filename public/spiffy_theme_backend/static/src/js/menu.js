/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { rpc } from "@web/core/network/rpc";
import { renderToElement } from "@web/core/utils/render";
import { ColorPallet } from "@spiffy_theme_backend/js/color_pallet";
import { NavBar } from "@web/webclient/navbar/navbar";
import { SwitchCompanyMenu } from "@web/webclient/switch_company_menu/switch_company_menu";
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { useService } from '@web/core/utils/hooks';
import { loadCSS } from "@web/core/assets";
import { onRendered, onWillUnmount, useEffect, useExternalListener, useState } from "@odoo/owl";
import { routerBus } from "@web/core/browser/router";
import { user } from "@web/core/user";
import { TodoSidebar } from "@spiffy_theme_backend/js/widgets/todo_sidebar";
import { ThemeConfigurator } from "@spiffy_theme_backend/js/widgets/theme_configurator";
import { SpiffyMenuGroup, spiffyMenuStore } from "@spiffy_theme_backend/js/widgets/menu_group";

// const websiteSystrayRegistry = registry.category('website_systray');
// websiteSystrayRegistry.add("UserMenu", { Component: UserMenu }, { sequence: 14 });

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
        // Body-level classes cannot be bound from a template; keep them in
        // sync with the OWL state through effects.
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
        useExternalListener(document, "fullscreenchange", this._clearFullscreenButton);
        useExternalListener(document, "webkitfullscreenchange", this._clearFullscreenButton);
        useExternalListener(document, "mozfullscreenchange", this._clearFullscreenButton);
        useExternalListener(document, "msfullscreenchange", this._clearFullscreenButton);

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
        this.addbookmarktags()

        // The app menu group data is loaded by the SpiffyMenuGroup component.
        this._GetLanguages()

        var size = $(window).width();
        var upTo1200 = size <= 1023.98

        this.isIpad = upTo1200
        var currentapp = this.menuService.getCurrentApp();
        spiffyMenuStore.currentMenuId = currentapp?.id ?? null;
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
    onBookmarkContextMenu(ev) {
        const origin = eventOrigin(ev);
        const tag = origin && closestAny(origin, ".bookmark_tag");
        if (!tag) {
            return;
        }
        this._showbookmarkoptions(withCurrentTarget(ev, tag));
    },
    _closeMagnifierOnOutsideClick(ev) {
        const magnifier = document.getElementById("magnifier");
        const origin = eventOrigin(ev);
        if (!magnifier || !magnifier.classList.contains("show") || origin?.closest(".magnifier_section")) {
            return;
        }
        $("#magnifier").collapse("hide");
    },
    _closeBookmarkOptionsOnOutsideClick(ev) {
        const origin = eventOrigin(ev);
        if (origin?.closest(".bookmark_options, .bookmark_rename_section")) {
            return;
        }
        $(".bookmark_list .bookmark_options, .bookmark_list .bookmark_rename_section").remove();
    },
    _clearFullscreenButton() {
        if (document.webkitIsFullScreen || document.mozFullScreen || document.msFullscreenElement || document.fullscreenElement) {
            return;
        }
        $(".fullscreen_section .full_screen").removeClass("fullscreen-exit");
    },
    getsubMenuItemHref(payload) {
        return `/odoo/${payload.actionPath || "action-" + payload.actionID}`;
    },
    _DebugToggler: function (ev) {
        $(ev.currentTarget).toggleClass('toggle');
        if ($(ev.currentTarget).hasClass('toggle')) {
            var current_href = window.location.href;
            window.location.search = "?debug=1"
        } else {
            window.location.search = "?debug="
        }
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
        var menu = this.menuService.getMenu($(ev.target).data('menu'))
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
        var self = this
        rpc('/get/dark/mode/data').then(function (rec) {
            var dark_mode = rec
            self._ChangeThemeMode(dark_mode)
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
        const removeAll = (selector) => {
            document.querySelectorAll(selector).forEach((el) => el.remove());
        };
        rpc('/get/model/record').then(function (rec) {
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
                addBodyClass(rec.darkmode);
            }
            if (rec.bookmark_panel) {
                // Synced to the body class by the bookmarkPanel effect.
                spiffyNavbar.bookmarkPanel.show = true;
            }
            if (rec.prevent_auto_save) {
                addBodyClass(rec.prevent_auto_save);
            }
            if (!rec.todo_list_enable) {
                removeAll(".header_to_do_list");
            }
            if (rec.pinned_sidebar) {
                addBodyClass(rec.pinned_sidebar);
                document.querySelectorAll("header .pin_sidebar").forEach((el) => el.classList.add("pinned"));
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

            if (!rec.show_edit_mode) {
                removeAll(".theme_selector");
            }
            if (!rec.is_admin) {
                removeAll(".debug_activator");
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
            // $('.o_main_navbar').removeClass('d-none');
        })
    },
    addbookmarktags: function() {
        const self = this;
        rpc('/get/bookmark/link', {}).then(function(rec) {
            $('.bookmark_list').empty()
            $.each(rec, function(key, value) {
                let urlParams = value.url.endsWith('?') ? value.url.slice(0, -1) : value.url;

                // var app_actionPath = `/odoo/${data.actionPath || "action-" + data.actionID}`;
                // href="#id=${Id}&amp;menu_id=${menu_id}&amp;action=${actionId}&amp;model=${model}&amp;view_type=${view_type}&amp;"
                var anchor_tag = `
                    <div class="d-inline-block bookmark_div">
                        <a role="menuitem"
                            href="${value.url}"
                            class="bookmark_tag btn-light btn demo_btn d-block o_app text-center"
                            bookmark-id="${value.id}"
                            bookmark-name="${value.name}"
                            title="${value.name}">
                            ${value.title}
                        </a>
                    </div>`;

                $('.bookmark_list').append(anchor_tag);
            })
            self._syncActiveBookmark();
        });
    },
    _syncActiveBookmark() {
        const clean = (url) => (url || "").replace(/\?$/, "");
        const path = window.location.pathname;
        const here = new Set([
            clean(path + window.location.search + window.location.hash),
            clean(path + "?" + window.location.hash),
            clean(path + window.location.hash),
        ]);
        document.querySelectorAll(".bookmark_list .bookmark_tag").forEach((tag) => {
            tag.classList.toggle("active", here.has(clean(tag.getAttribute("href"))));
        });
    },
    _getCurrentPageName: function () {
        var breadcrumbs = $('.o_control_panel ol.breadcrumb li')
        var bookmark_name = ""
        $(breadcrumbs).each(function (index) {
            if (index > 0) {
                bookmark_name = bookmark_name + ' | ' + $(this).text()
            } else {
                bookmark_name = $(this).text()
            }
        });

        $('input#bookmark_page_name').val(bookmark_name)
    },
    _saveBookmarkPage: function () {
        var self = this
        var pathname = window.location.pathname
        var hash = window.location.hash
        var url = pathname + '?' + hash
        var name = $('input#bookmark_page_name').val()
        var title = $('input#bookmark_page_name').val().substr(0, 2)
        rpc('/add/bookmark/link', {
            'name': name,
            'url': url,
            'title': title,
        }).then(function (rec) {
            self.addbookmarktags()
        });
    },
    _showbookmarkoptions: function (ev) {
        var self = this
        ev.preventDefault();
        var bookmark_id = $(ev.target).attr('bookmark-id')
        var bookmark_name = $(ev.target).attr('bookmark-name')
        $('.bookmark_list .bookmark_options').remove()
        $('.bookmark_list .bookmark_rename_section').remove()
        var bookmark_options = $(renderToElement("BookmarkOptions", {
            bookmark_id: bookmark_id,
        }))
        $(ev.target).parent().append(bookmark_options)
        $('.bookmark_list .rename_bookmark').on("click", function (e) {
            self._RenameBookmark(ev.target, bookmark_id, bookmark_name);
        });

        $('.bookmark_list .remove_bookmark').on("click", function (e) {
            self._RemoveBookmark(bookmark_id);
        });
        ev.preventDefault();
    },
    _RenameBookmark: function (elem, bookmark_id, bookmark_name) {
        var self = this
        var bookmark_rename = $(renderToElement("BookmarkRename", {
            bookmark_id: bookmark_id,
            bookmark_name: bookmark_name,
        }))
        $(elem).parent().append(bookmark_rename)

        $('.bookmark_list .bookmark_rename_cancel').on("click", function (e) {
            $('.bookmark_list .bookmark_rename_section').remove()
        });
        $('.bookmark_list .bookmark_rename').on("click", function (e) {
            var new_bookmark_name = $('input#bookmark_rename').val()
            self._UpdateBookmark(bookmark_id, new_bookmark_name);
        });
    },
    _RemoveBookmark: function (bookmark_id) {
        var self = this
        rpc('/remove/bookmark/link', {
            'bookmark_id': bookmark_id,
        }).then(function (rec) {
            self.addbookmarktags()
        });
    },
    _UpdateBookmark: function (bookmark_id, bookmark_name) {
        var self = this
        var title = bookmark_name.substr(0, 2)
        rpc('/update/bookmark/link', {
            'bookmark_id': bookmark_id,
            'bookmark_name': bookmark_name,
            'bookmark_title': title,
        }).then(function (rec) {
            self.addbookmarktags()
        });
    },
    _magnifierZoomOut: function () {
        var current_zoom = parseInt($('.zoom_value').text())
        var current_zoom = current_zoom - 10
        if (current_zoom > 20) {
            $('.zoom_value').text(current_zoom)
            var scale_value = current_zoom / 100
            var width_value = ((100 / current_zoom) * 100).toFixed(4)
            if ($('.o_content > div').length > 1) {
                var target = $('.o_action_manager > .o_view_controller > .o_content')
            } else {
                var target = $('.o_content > div')
            }
            $(target).css({
                'width': width_value + '%',
                'transform-origin': 'left top',
                'transform': 'scale(' + scale_value + ')',
            })
        }
    },
    _magnifierZoomIn: function () {
        var current_zoom = parseInt($('.zoom_value').text())
        var current_zoom = current_zoom + 10
        if (current_zoom < 210) {
            $('.zoom_value').text(current_zoom)
            var scale_value = current_zoom / 100
            var width_value = ((100 / current_zoom) * 100).toFixed(4)
            if ($('.o_content > div').length > 1) {
                var target = $('.o_action_manager > .o_view_controller > .o_content')
            } else {
                var target = $('.o_content > div')
            }
            $(target).css({
                'width': width_value + '%',
                'transform-origin': 'left top',
                'transform': 'scale(' + scale_value + ')',
            })
        }
    },
    _magnifierZoomReset: function () {
        $('.zoom_value').text('100')
        if ($('.o_content > div').length > 1) {
            var target = $('.o_action_manager > .o_view_controller > .o_content')
        } else {
            var target = $('.o_content > div')
        }
        $(target).css({
            'width': '100%',
            'transform-origin': 'left top',
            'transform': 'scale(1)',
        })
    },
    _FullScreenMode: function (ev) {
        var elem = document.documentElement;
        if ($(ev.currentTarget).hasClass('fullscreen-exit')) {
            if (document.exitFullscreen) {
                document.exitFullscreen();
                $(ev.currentTarget).removeClass('fullscreen-exit')
            } else if (document.webkitExitFullscreen) { /* Safari */
                document.webkitExitFullscreen();
                $(ev.currentTarget).removeClass('fullscreen-exit')
            } else if (document.msExitFullscreen) { /* IE11 */
                document.msExitFullscreen();
                $(ev.currentTarget).removeClass('fullscreen-exit')
            }
        } else {
            if (elem.requestFullscreen) {
                elem.requestFullscreen();
                $(ev.currentTarget).addClass('fullscreen-exit')
            } else if (elem.webkitRequestFullscreen) { /* Safari */
                elem.webkitRequestFullscreen();
                $(ev.currentTarget).addClass('fullscreen-exit')
            } else if (elem.msRequestFullscreen) { /* IE11 */
                elem.msRequestFullscreen();
                $(ev.currentTarget).addClass('fullscreen-exit')
            }
        }
    },
    // The configurator is the OWL component spiffy_theme_backend.ThemeConfigurator;
    // the NavBar only owns its visibility flag.
    _openConfigModal: function () {
        this.configuratorState.visible = !this.configuratorState.visible;
    },

    _ChangeThemeModeCLicked: function (ev) {
        $('body').toggleClass('dark_mode')
        if ($('body').hasClass('dark_mode')) {
            var darkmode = true
        } else {
            var darkmode = false
        }
        this._ChangeThemeMode(darkmode)
    },
    _ChangeThemeMode: function (darkmode) {
        if (darkmode) {
            rpc('/active/dark/mode', { 'dark_mode': 'on' })
                .then(function (data) {
                    if (data) {
                    }
                })
            $('body').addClass('dark_mode')
            $(':root').css('--biz-theme-primary-color', 'var(--dark-theme-primary-color)');
            $(':root').css('--biz-theme-primary-text-color', 'var(--dark-theme-primary-text-color)');
            $(':root').css('--biz-theme-secondary-color', 'var(--dark-theme-secondary-color)');
            $(':root').css('--biz-theme-secondary-text-color', 'var(--dark-theme-secondary-text-color)');
            $(':root').css('--biz-theme-body-color', 'var(--dark-theme-body-color)');
            $(':root').css('--biz-theme-body-text-color', 'var(--dark-theme-body-text-color)');
            $(':root').css('--biz-theme-primary-rgba', 'var(--primary-rgba)');
        }
        else {
            rpc('/active/dark/mode', { 'dark_mode': 'off' })
                .then(function (data) {
                    if (data) {
                    }
                })
            $('body').removeClass('dark_mode')
            $(':root').css('--biz-theme-primary-color', 'var(--light-theme-primary-color)');
            $(':root').css('--biz-theme-primary-text-color', 'var(--light-theme-primary-text-color)');
            $(':root').css('--biz-theme-secondary-color', 'var(--light-theme-secondary-color)');
            $(':root').css('--biz-theme-secondary-text-color', 'var(--light-theme-secondary-text-color)');
            $(':root').css('--biz-theme-body-color', 'var(--light-theme-body-color)');
            $(':root').css('--biz-theme-body-text-color', 'var(--light-theme-body-text-color)');
            $(':root').css('--biz-theme-primary-rgba', 'var(--primary-rgba)');
        }
    },
    _ChangeSidebarBehaviour: function (ev) {
        $(ev.target).toggleClass('pinned')
        $('body').toggleClass('pinned')
        if ($(ev.target).hasClass('pinned')) {
            var sidebar_pinned = true
        } else {
            var sidebar_pinned = false
        }
        rpc('/sidebar/behavior/update', {
            'sidebar_pinned': sidebar_pinned,
        }).then(function (data) {
            if (data) {
            }
        })
    },

    _GetLanguages: function () {
        var self = this
        var session = session;
        rpc('/get/active/lang').then(function (data) {
            var lang_list = data
            if (data && data.length > 1) {
                $('.active_lang').empty()
                $.each(lang_list, function (index, value) {
                    var searchedlang = $(renderToElement("Searchedlang", {
                        lang_name: value['lang_name'],
                        lang_code: value['lang_code'],
                        active_lang: user.context.lang
                    }))
                    $('.active_lang').append(searchedlang)
                    $('.biz_lang_btn').unbind().on('click', function (ev) {
                        var lang = $(ev.currentTarget)[0].lang
                        self.LangSelect(lang)
                    })
                });
                $('.o_user_lang').removeClass('d-none')
            } else {
                $('.o_user_lang').addClass('d-none')
            }
        })
    },

    LangSelect: function (lang) {
        var self = this;
        rpc('/change/active/lang', {
            'lang': lang,
        }).then(function (data) {
            self.actionService.doAction("reload_context");
        });
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

