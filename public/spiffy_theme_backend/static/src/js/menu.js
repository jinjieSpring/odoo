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
import { onRendered, onWillUnmount, useExternalListener } from "@odoo/owl";
import { routerBus } from "@web/core/browser/router";
import { user } from "@web/core/user";

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
const SPIFFY_MENU_CLICK_ROUTES = [
    ["body.top_menu_vertical .o_navbar_apps_menu a", "_ShowCurrentMenus"],
    ["body.top_menu_vertical_mini .o_navbar_apps_menu .main_link", "_ShowCurrentMenusNew"],
    ["body.top_menu_vertical_mini .o_navbar_apps_menu .parent-menu", "_ShowCurrent"],
    [".o_navbar_apps_menu .spiffy-menu-group-list", "_SpiffyMenuGroupList"],
    [".o_navbar_apps_menu .spiffy_main_app", "_SpiffyMenuGroup"],
    [".o_navbar_apps_menu .parent-main-menu", "_ParentMainMenu"],
    [".o_navbar_apps_menu .app_menu_group", "_onMenuGroupClick"],
    [".o_navbar_apps_menu .submenu-link", "_SpiffyMainGroup"],
    [".o_navbar_apps_menu .spiffy-submenu-group", "_SpiffySubMenuGroup"],
    [".o_navbar_apps_menu .child_menus", "_childMenuClick"],
    [".o_menu_sections .o_menu_entry_lvl_2, .o_menu_sections .o_nav_entry", "_childMenuClick"],
    [".mobile-header-toggle #mobileMenuToggleBtn", "_mobileHeaderToggle"],
    [".current_app_sections a[data-menu], .child_menus", "_markCurrentMenuActive"],
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

patch(NavBar.prototype, {
    async setup(parent, menuData) {
        super.setup();
        var self = this
        spiffyNavbar = this;
        this._onBookmarkRouteChange = () => this._syncActiveBookmark();
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
        this.addFontManager();
        // on reload add backend theme class
        this.addconfiguratorclass()
        // on reload add bookmark tags in menu
        this.addbookmarktags()

        // get all apps menu data
        await this._all_apps_menu_data()
        this._GetLanguages()

        var size = $(window).width();
        var upTo1200 = size <= 1023.98

        this.isIpad = upTo1200
        var currentapp = this.menuService.getCurrentApp();
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
    onDynamicDataClick(ev) {
        const origin = eventOrigin(ev);
        const checkbox = origin && closestAny(origin, ".font-checkbox");
        if (!checkbox) {
            return;
        }
        this._onCheckboxChange(withCurrentTarget(ev, checkbox));
    },
    _markCurrentMenuActive(ev) {
        const current = ev.currentTarget;
        $(".current_app_sections a[data-menu], .nav-item > p > a, .nav-item > a").removeClass("active");
        $(current).addClass("active");
        $(current).parents(".nav-item").children("p, a").addClass("active");
        $(current).parents(".collapse").addClass("show");
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

    _on_secondary_menu_click: function (menu_id, action_id) {
        this._super.apply(this, arguments);
        $('.o_menu_sections').removeClass('toggle');
        $('body').removeClass('backdrop');
    },

    _mobileHeaderToggle: function (ev) {
        var menu_brand = $('.o_main_navbar > a.o_menu_brand').clone()
        $('.o_menu_sections > a.o_menu_brand').remove()
        $('#mobileMenuclose').before(menu_brand)
        $('.o_menu_sections').addClass('toggle');
        $('body').addClass('backdrop');
    },
    _mobileHeaderClose: function (ev) {
        $('.o_menu_sections').removeClass('toggle');
        $('body').removeClass('backdrop');
    },
    _OpenAppdrawer: function (ev) {
        this._AppdrawerIcons()

        $('.o_main_navbar').toggleClass('appdrawer-toggle')
        // $(ev.currentTarget).toggleClass('toggle')
        $('.appdrawer_section').toggleClass('toggle')

        if ($(".appdrawer_section").hasClass('toggle')) {
            var size = $(window).width();
            if (size > 992) {
                setTimeout(() => $(".appdrawer_section input").focus(), 100);
            }
        } else {
            this._resetAppDrawerSearch?.();
        }
        this._all_apps_menu_data()
    },
    _OpenFavAppdrawer: function (ev) {
        this._OpenAppdrawer(ev)
        $('.appdrawer_section').toggleClass('show_favourite_apps')
        $('.apps-list').addClass('d-none')
        $('.favourite_apps').removeClass('d-none')
    },
    _ToggleBookmarkPanel: function (ev) {
        $('body').toggleClass('bookmark_panel_show')
        if ($('body').hasClass('bookmark_panel_show')) {
            var bookmark_panel = true
        } else {
            var bookmark_panel = false
        }
        rpc('/update/bookmark/panel/show', {
            'bookmark_panel': bookmark_panel,
        })
    },

    _CloseAppdrawer: function (ev) {
        $('.o_main_navbar').removeClass('appdrawer-toggle')
        $('.appdrawer_section').removeClass('show_favourite_apps')
        $('.apps-list').removeClass('d-none')
        $('.favourite_apps').addClass('d-none')
        $('.appdrawer_section').removeClass('toggle')
        this._resetAppDrawerSearch?.();
        var $target = $(ev.currentTarget).siblings('.submenu-group');
    
        if ($target.hasClass('active')) {
            $target.removeClass('active').hide();
        }
        this._all_apps_menu_data()
    },

    _ShowCurrentMenus: function (ev) {
        var $clicked = $(ev.currentTarget);
        // Group buttons are toggled by _onMenuGroupClick. Closing them here
        // and opening them again there makes the top-level button unable to collapse.
        if ($clicked.closest('.app_menu_group').length) {
            return;
        }
        var $menuItem = $clicked.closest('.col-1, .col-2').children('.spiffy_main_app, .spiffy_main_group');
        var clickedTopButton = $menuItem.length && ($clicked.is($menuItem) || $.contains($menuItem[0], ev.target));
        // Only the open item is touched. slideUp/slideDown on every app forces a layout
        // pass and waits 200ms, which is why the menu bar felt slow.
        $('.spiffy_main_app.active, .spiffy_main_group.active').each(function () {
            if (this !== $menuItem[0]) {
                $(this).removeClass('active').next('.header-sub-menus').removeClass('show').addClass('d-none');
            }
        });
        if (clickedTopButton && $menuItem.hasClass('active')) {
            $menuItem.removeClass('active').next('.header-sub-menus').removeClass('show').addClass('d-none');
        } else if (!$menuItem.hasClass('active')) {
            $menuItem.addClass('active').next('.header-sub-menus').removeClass('d-none').addClass('show');
        }
        if (!$clicked.closest('.col-2').length) {
            $('.app_menu_group.active').removeClass('active');
            $('.spiffy-submenu-group.show').removeClass('show').addClass('d-none');
        }
    },

    _ShowCurrentMenusNew: function (ev) {
        $('.header-sub-menus .collapse').addClass('show');
        var $blurOverlay = $('#blur-overlay');
        var $backgroundOverlay = $('.top-menu-vertical-mini');
        if ($(ev.target).hasClass('dropdown-btn')) {
            ev.preventDefault();
        }

        if ($(ev.target).hasClass('active')) {
            $(ev.target).removeClass('active')
            if ($(ev.target).next().hasClass('header-sub-menus') && $(ev.target).next().hasClass('show')) {
                $(ev.target).next().removeClass('show')
            }
            if ($(ev.target).next().hasClass('submenu-group') && $(ev.target).next().hasClass('show')) {
                $(ev.target).next().removeClass('show')
                $(ev.currentTarget).prev($backgroundOverlay).removeClass('header-background').show();  
            }
        } else {
            $(ev.target).parent().parent().find('ul').removeClass('show')
            $(ev.target).parent().parent().find('a.main_link').removeClass('active')
            $(ev.target).parent().find('ul').addClass('show')
            $(ev.target).addClass('active')
        }
        this._all_apps_menu_data()
    },

    _ShowCurrent: function (ev) {
        var $backgroundOverlay = $('.top-menu-vertical-mini');
        $backgroundOverlay.removeClass('header-background').hide();  
        this._all_apps_menu_data()
    },
    
    _all_apps_menu_data: function () {
        if (this._spiffyMenuDataLoading) {
            return this._spiffyMenuDataLoading;
        }
        const load = async () => {
            const menu_data = this.menuService.getApps();
            const rec_ids = menu_data.map((app) => app.id);
            const rec = await rpc('/get/irmenu/icondata', { menu_ids: rec_ids });
            const spiffy_app_group = rec.spiffy_app_group;
            let app_menu_list = [];
            for (const value of menu_data) {
                const target_tag = '.o_navbar_apps_menu a.main_link[data-menu=' + value.id + ']';
                $(this.root.el).find(target_tag).find('.app_icon').empty();
                const current_record = rec[value.id] && rec[value.id][0];
                if (!current_record) {
                    continue;
                }
                value.use_icon = current_record.use_icon;
                value.icon_class_name = current_record.icon_class_name;
                value.icon_img = current_record.icon_img;
                value.spiffy_app_group_id = current_record.spiffy_app_group_id;
                value.spiffy_app_group = spiffy_app_group;
                if (!app_menu_list.length && current_record.app_menu_list) {
                    try {
                        app_menu_list = JSON.parse(current_record.app_menu_list);
                    } catch (e) {
                        app_menu_list = [];
                    }
                }
            }

            const options = {
                group_info: spiffy_app_group,
                menu_info: menu_data,
                getMenuItemHref: this.getMenuItemHref,
                menuService: this.menuService,
                app_menu_list,
            };
            const selector = $('body').hasClass('top_menu_horizontal')
                ? ".spiffy-app-group"
                : ".all-apps-menus";
            const renderMenu = () => {
                const container = $(selector);
                if (!container.length || container.data('menu-rendered')) {
                    return Boolean(container.data('menu-rendered'));
                }
                container.empty().append($(renderToElement("spiffy_theme_backend.AppMenuGroup", options)));
                container.data('menu-rendered', true);
                return true;
            };
            if (renderMenu()) {
                return;
            }
            let attempts = 0;
            const retry = () => {
                if (renderMenu() || attempts++ > 60) {
                    return;
                }
                requestAnimationFrame(retry);
            };
            requestAnimationFrame(retry);
        };
        this._spiffyMenuDataLoading = load().catch((error) => {
            this._spiffyMenuDataLoading = null;
            throw error;
        });
        return this._spiffyMenuDataLoading;
    },
    
    

    _childMenuClick: function (ev) {
        ev.preventDefault();
        var menu = this.menuService.getMenu($(ev.target).data('menu'))
        var $blurOverlay = $('#blur-overlay');
        var $backgroundOverlay = $('.top-menu-vertical-mini');
        $backgroundOverlay.removeClass('header-background').hide(); 
        if (menu) {
            this.onNavBarDropdownItemSelection(menu)
        }
        if ($('body').hasClass('top_menu_vertical_mini')) {
            if ($(ev.target).parents('.submenu-group').hasClass('show')) {
                $(ev.target).parents('.submenu-group').removeClass('show')
                $(ev.target).parents('.submenu-group').next().removeClass('active')
            }
        }
    },

    _SpiffyMenuGroupList: function (ev) {
        ev.preventDefault();
        var $blurOverlay = $('#blur-overlay');
        var $backgroundOverlay = $('.top-menu-vertical-mini');

        if ($('body').hasClass('top_menu_vertical_mini')) {
            if ($(ev.target).hasClass('background-blur')) {
                $('.submenu-group').removeClass('show').hide();
                $('.parent-menu').removeClass('active').hide();
                $blurOverlay.removeClass('background-blur').hide(); 
                ($backgroundOverlay).removeClass('header-background').hide();  
            }else{
                $blurOverlay.removeClass('background-blur').hide(); 
            }
        }
    },

    _SpiffyMenuGroup: function (ev) {
        var $blurOverlay = $('#blur-overlay');
        var $backgroundOverlay = $('.top-menu-vertical-mini');

        if ($('body').hasClass('top_menu_vertical_mini')) {
            $('.submenu-group').removeClass('show').hide();
            $('.parent-menu').removeClass('active').hide();
            $blurOverlay.removeClass('background-blur').hide(); 
            ($backgroundOverlay).removeClass('header-background').hide();  
        }
    },

    _ParentMainMenu: function (ev) {
        var $blurOverlay = $('#blur-overlay');
        if ($('body').hasClass('top_menu_vertical_mini')) {
            
            if ($(ev.currentTarget).hasClass('parent-main-menu')) {
                $blurOverlay.removeClass('background-blur').show();  
            } else {
                $blurOverlay.removeClass('background-blur').hide();  
            }
            
        }
    },

    _onMenuGroupClick: function (ev) {
        ev.preventDefault();

        if ($('body').hasClass('top_menu_horizontal')) {
            var $target = $(ev.currentTarget).siblings('.spiffy-submenu-group');
            
            if ($target.hasClass('active')) {
                $target.removeClass('active').hide();
            } else {
                $('.spiffy-submenu-group').not($target).removeClass('active').hide();
                $target.addClass('active').show();
            }
        }

        if ($('body').hasClass('top_menu_vertical_mini')) {
            var $target = $(ev.currentTarget).siblings('.spiffy-submenu-group');
            var $blurOverlay = $('#blur-overlay');
            var $backgroundOverlay = $('.top-menu-vertical-mini');

            // If target is already open, close it
            if ($target.hasClass('show')) {
                $target.removeClass('show').addClass('d-none').hide();
                $blurOverlay.removeClass('background-blur').hide();
                $backgroundOverlay.removeClass('header-background').hide();
            } else {
                // Close any other open submenu
                $('.spiffy-submenu-group.show').not($target).removeClass('show').addClass('d-none').hide();

                // Open the clicked submenu
                $target.removeClass('d-none').addClass('show').show();
                $blurOverlay.addClass('background-blur').show();
                $backgroundOverlay.addClass('header-background').show();
            }
        }
        
        if ($('body').hasClass('top_menu_vertical')) {
            var $clicked = $(ev.currentTarget);
            var $submenuGroup = $clicked.siblings('.spiffy-submenu-group');

            if ($clicked.hasClass('active')) {
                $clicked.removeClass('active');
                $submenuGroup.removeClass('show').addClass('d-none');
                return;
            }

            $('.app_menu_group').not($clicked).removeClass('active')
            .siblings('.spiffy-submenu-group').removeClass('show').addClass('d-none');

            $clicked.addClass('active');
            $submenuGroup.removeClass('d-none').addClass('show');

        }
    },
        
    _SpiffyMainGroup: function (ev) {
        if ($('body').hasClass('top_menu_horizontal')) {
            // $('.appdrawer_section').removeClass('toggle');
            $('.submenu-group').addClass('d-none');
            $('.submenu-group').removeClass('active');
        }
        if ($('body').hasClass('top_menu_vertical_mini')) {
            var $target = $(ev.currentTarget).siblings('.spiffy-submenu-group');
            var $blurOverlay = $('#blur-overlay');
            var $backgroundOverlay = $('.top-menu-vertical-mini');
            $('.submenu-group').removeClass('show').hide();            
            $blurOverlay.removeClass('background-blur').hide(); 
            $backgroundOverlay.removeClass('header-background').hide();   
            
        }
    },
    _SpiffySubMenuGroup: function (ev) {
        if ($('body').hasClass('top_menu_horizontal')) {
            $('.spiffy-submenu-group').addClass('d-none').removeClass('active');
        }
    },
    
    change_menu_section: function (primary_menu_id) {
        this._super.apply(this, arguments);
        var target_tag = '.o_navbar_apps_menu a.main_link[data-menu=' + primary_menu_id + ']'
        var $tagtarget = $(target_tag)
        $tagtarget.parent().find('ul').addClass('show')
        $tagtarget.addClass('active')
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
                addBodyClass("bookmark_panel_show");
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
    _openConfigModal: function () {
        var self = this
        self.showeditmodal();
        $('.dynamic_data').toggleClass('visible')
        $('body.o_web_client').toggleClass('backdrop')
    },
    showeditmodal: function (ev) {
        $.get('/color/pallet/data/', {}).then(function (data) {

            $(".dynamic_data").empty()
            $(".dynamic_data").append(data)

            $('#theme_color_pallets #use_custom_color_config').unbind().on('change', function (e) {
                if ($(this).prop("checked") == true) {
                    $('#theme_color_pallets .custom_color_config').removeClass('d-none')
                    $('#theme_color_pallets .predefined_color_pallets').addClass('d-none')
                } else {
                    $('#theme_color_pallets .custom_color_config').addClass('d-none')
                    $('#theme_color_pallets .predefined_color_pallets').removeClass('d-none')
                }
            });


            $('#app_drawer #use_custom_drawer_color').unbind().on('change', function (e) {
                if ($(this).prop("checked") == true) {
                    $('#app_drawer .custom_color_config').removeClass('d-none')
                    $('#app_drawer .predefined_color_pallets').addClass('d-none')
                } else {
                    $('#app_drawer .custom_color_config').addClass('d-none')
                    $('#app_drawer .predefined_color_pallets').removeClass('d-none')
                }
            });

            $('#apply_menu_shape_style').unbind().on('change', function (e) {
                if ($(this).prop("checked") == true) {
                    $('.apply_menu_shape').removeClass('d-none')
                } else {
                    $('.apply_menu_shape').addClass('d-none')
                }
            });

            $('#vertical_background').unbind().on('change', function (e) {
                if ($(this).prop("checked") == true) {
                    $('.vertical-menu').removeClass('d-none')
                    $("body").addClass("vertical_background");
                } else {
                    $('.vertical-menu').addClass('d-none');
                    $("body").removeClass("vertical_background");
                }
            });

            $('#app_drawer #apply_light_bg').unbind().on('change', function (e) {
                if ($(this).prop("checked") == true) {
                    $('#app_drawer .app-drawer-bg-image-content').removeClass('d-none')
                } else {
                    $('#app_drawer .app-drawer-bg-image-content').addClass('d-none')
                }
            });

            $('.top_menu_style').unbind().on('click ', function (e) {
                if ($(this).val() == 'top_menu_vertical') {
                    $('.vertical-background').removeClass('d-none');
                    if ($("body").hasClass("vertical_background")) {
                        $('.vertical-menu').removeClass('d-none')
                    }
                }
                else {
                    $('.vertical-background').addClass('d-none');
                    $('.vertical-menu').addClass('d-none');
                }
            });

            $('#apply_menu_bg').unbind().on('change', function (e) {
                if ($(this).prop("checked") == true) {
                    $('.menu-bg-image-content').removeClass('d-none')
                } else {
                    $('.menu-bg-image-content').addClass('d-none')
                }
            });

            $('.app_bg_img_light').unbind().on('change', function (e) {
                var upload_image = document.querySelector('#light_bg_image').files[0];
                var reader1 = new FileReader();
                var bg_data = reader1.readAsDataURL(upload_image);
                reader1.onload = function (e) {
                    var selected_bg_image = e.target.result;
                    window.app_light_bg_image = selected_bg_image
                }
                var fileName = $(this).val().split("\\").pop();
                $(this).siblings(".custom-file-label").addClass("selected").html(fileName);
            });


            $('.custom_app_bg_img_menu').unbind().on('change', function (e) {
                var upload_image = document.querySelector('#top_menu_custom_bg_vertical').files[0];
                var reader1 = new FileReader();
                var bg_data = reader1.readAsDataURL(upload_image);
                reader1.onload = function (e) {
                    var custom_selected_bg_image = e.target.result;
                    window.vertical_app_menu_bg_image = custom_selected_bg_image
                }
                var fileName = $(this).val().split("\\").pop();
                $(this).siblings(".custom-file-label-mini-2").addClass("selected").html(fileName);
            });

            $('.app_bg_img_dark').unbind().on('change', function (e) {
                var upload_image = document.querySelector('#dark_bg_image').files[0];
                var reader1 = new FileReader();
                var bg_data = reader1.readAsDataURL(upload_image);
                reader1.onload = function (e) {
                    var selected_bg_image = e.target.result;
                    window.app_dark_bg_image = selected_bg_image
                }
            });

            $('#separator').unbind().on('change', function () {
                $("#theme_separator_style .preview").removeClass("separator_style_4 separator_style_3 separator_style_2 separator_style_1");
                var current_separator_style = $('#separator').val()
                $("#theme_separator_style .preview").addClass(current_separator_style);
            });

            $('#tab').unbind().on('change', function () {
                $("#theme_tab_style .preview").removeClass("tab_style_4 tab_style_3 tab_style_2 tab_style_1");
                var current_tab_style = $('#tab').val()
                $("#theme_tab_style .preview").addClass(current_tab_style);
            });

            $('#checkbox').unbind().on('change', function () {
                $("#theme_checkbox_style .preview").removeClass("checkbox_style_4 checkbox_style_3 checkbox_style_2 checkbox_style_1");
                var current_checkbox_style = $('#checkbox').val()
                $("#theme_checkbox_style .preview").addClass(current_checkbox_style);
            });

            $('#radio').unbind().on('change', function () {
                $("#theme_radio_style .preview").removeClass("radio_style_4 radio_style_3 radio_style_2 radio_style_1");
                var current_radio_style = $('#radio').val()
                $("#theme_radio_style .preview").addClass(current_radio_style);
            });
            $('#button').unbind().on('change', function () {
                $("#theme_buttons_style .preview").removeClass("button_style_4 button_style_3 button_style_2 button_style_1");
                var current_button_style = $('#button').val()
                $("#theme_buttons_style .preview").addClass(current_button_style);
            });

            $('#popup').unbind().on('change', function () {
                $("#theme_popup_style .preview").removeClass("popup_style_4 popup_style_3 popup_style_2 popup_style_1");
                var current_popup_style = $('#popup').val()
                $("#theme_popup_style .preview").addClass(current_popup_style);
            });

            $(".selected_value").on('click', function () {
                var light_primary_bg_color = $("input[id='primary_bg']").val()
                var light_primary_text_color = $("input[id='primary_text']").val()
                var light_secondry_bg_color = $("input[id='secondry_bg']").val()
                var light_secondry_text_color = $("input[id='secondry_text']").val()

                var custom_color_pallet = $("input[id='use_custom_color_config']").is(':checked')
                var selected_color_pallet = $("input[name='color_pallets']:checked").val()

                var custom_drawer_bg = $("input[id='custom_drawer_bg']").val()
                var custom_drawer_text = $("input[id='custom_drawer_text']").val()

                var menu_shape_bg = $("input[id='menu_shape_bg']").val()
                var menu_shape_bg_color_opacity = $("input[id='menu_shape_bg_color_opacity']").val()

                var custom_drawer_color_pallet = $("input[id='use_custom_drawer_color']").is(':checked')
                var selected_drawer_color_pallet = $("input[name='drawer_color_pallets']:checked").val()

                var apply_light_bg_img = $("input[id='apply_light_bg']").is(':checked')
                var apply_menu_shape_style = $("input[id='apply_menu_shape_style']").is(':checked')
                var vertical_background = $("input[id='vertical_background']").is(':checked')

                var attachment_in_tree_view = $("input[id='attachment_in_tree_view']").is(':checked')

                if (window.app_light_bg_image) {
                    var app_light_bg_img = window.app_light_bg_image
                } else if ($("input[id='light_bg_image']").attr('value')) {
                    var app_light_bg_img = $("input[id='light_bg_image']").attr('value')
                }
                else {
                    var app_light_bg_img = false
                }

                if (window.vertical_app_menu_bg_image) {
                    var vertical_app_menu_bg_img = window.vertical_app_menu_bg_image
                } else if ($("input[id='top_menu_custom_bg_vertical']").attr('value')) {
                    var vertical_app_menu_bg_img = $("input[id='top_menu_custom_bg_vertical']").attr('value')
                }
                else {
                    var vertical_app_menu_bg_img = false
                }
                var light_body_bg_color = $("input[id='body_bg']").val()
                var light_body_text_color = $("input[id='body_text']").val()

                var dark_primary_bg_color = $("input[id='dark_primary_bg']").val()
                var dark_primary_text_color = $("input[id='dark_primary_text']").val()
                var dark_secondry_bg_color = $("input[id='dark_secondry_bg']").val()
                var dark_secondry_text_color = $("input[id='dark_secondry_text']").val()

                if (window.app_dark_bg_image) {
                    var app_dark_bg_img = window.app_dark_bg_image
                } else if ($("input[id='dark_bg_image']").attr('value')) {
                    var app_dark_bg_img = $("input[id='dark_bg_image']").attr('value')
                }
                else {
                    var app_dark_bg_img = false
                }
                var dark_body_bg_color = $("input[id='dark_body_bg']").val()
                var dark_body_text_color = $("input[id='dark_body_text']").val()

                var selected_separator = $("input[name='separator']:checked").val()
                var selected_tab = $("input[name='tab']:checked").val()
                var selected_checkbox = $("input[name='checkbox']:checked").val()
                var selected_radio = $("input[name='radio']:checked").val()
                var selected_popup = $("input[name='popup']:checked").val()
                var selected_loader = $("input[name='loader_style']:checked").val()
                var selected_login = $("input[name='login_page_style']:checked").val()
                // var selected_fonts = $("input[name='font_family']:checked").val()
                var selected_font_family = $("input[name='google_font_links_ids']:checked").val()
                var selected_fontsize = $("input[name='font_size']:checked").val()
                var selected_top_menu_position = $("input[name='top_menu_position']:checked").val()
                var selected_top_menu_bg_vertical = $("input[name='top_menu_bg_vertical']:checked").val()
                var selected_theme_style = $("input[name='theme_style']:checked").val()
                var selected_menu_shape = $("input[name='shape_style']:checked").val()
                var selected_list_view_density = $("input[name='list_view_density']:checked").val()
                var selected_list_view_sticky_header = $("input[id='list_view_sticky_header']:checked").val()
                var selected_input_style = $("input[name='input_style']:checked").val()

                rpc('/color/pallet/', {
                    'light_primary_bg_color': light_primary_bg_color,
                    'light_primary_text_color': light_primary_text_color,
                    'light_secondry_bg_color': light_secondry_bg_color,
                    'light_secondry_text_color': light_secondry_text_color,
                    'light_body_bg_color': light_body_bg_color,
                    'light_body_text_color': light_body_text_color,

                    'apply_light_bg_img': apply_light_bg_img,
                    'app_light_bg_image': app_light_bg_img,
                    'vertical_app_menu_bg_image': vertical_app_menu_bg_img,

                    'dark_primary_bg_color': dark_primary_bg_color,
                    'dark_primary_text_color': dark_primary_text_color,
                    'dark_secondry_bg_color': dark_secondry_bg_color,
                    'dark_secondry_text_color': dark_secondry_text_color,
                    'dark_body_bg_color': dark_body_bg_color,
                    'dark_body_text_color': dark_body_text_color,

                    'app_dark_bg_image': app_dark_bg_img,

                    'attachment_in_tree_view': attachment_in_tree_view,

                    'selected_separator': selected_separator,
                    'selected_tab': selected_tab,
                    'selected_checkbox': selected_checkbox,
                    'selected_radio': selected_radio,
                    'selected_popup': selected_popup,
                    'custom_color_pallet': custom_color_pallet,
                    'selected_color_pallet': selected_color_pallet,

                    'custom_drawer_bg': custom_drawer_bg,
                    'custom_drawer_text': custom_drawer_text,
                    'menu_shape_bg': menu_shape_bg,
                    'custom_drawer_color_pallet': custom_drawer_color_pallet,
                    'selected_drawer_color_pallet': selected_drawer_color_pallet,
                    'google_font_links_ids': selected_font_family,

                    'selected_loader': selected_loader,
                    'selected_login': selected_login,
                    // 'selected_fonts': selected_fonts,
                    'selected_fontsize': selected_fontsize,
                    // 'selected_chatter_position': selected_chatter_position,
                    'selected_top_menu_position': selected_top_menu_position,
                    'selected_top_menu_bg_vertical': selected_top_menu_bg_vertical,
                    'selected_theme_style': selected_theme_style,
                    'apply_menu_shape_style': apply_menu_shape_style,
                    'vertical_background': vertical_background,
                    'selected_menu_shape': selected_menu_shape,
                    'selected_list_view_density': selected_list_view_density,
                    'selected_list_view_sticky_header': selected_list_view_sticky_header,
                    'selected_input_style': selected_input_style,
                    'menu_shape_bg_color_opacity': menu_shape_bg_color_opacity,
                }).then(function (data) {
                    window.location.reload()
                })
                
            });
            $('.reset_backend_configurator').unbind().click(function (e) {
                rpc('/color/pallet/reset/', {}).then(function (data) {
                    if (data.status === "success") {
                        window.location.reload();
                    }
                });
            });
            
            $('.backend_configurator_close').unbind().click(function (e) {
                $('.dynamic_data').toggleClass('visible')
                $('body.o_web_client').toggleClass('backdrop')
            });


        })
        $('#myModal').modal("show")
    },
    addFontManager: function () {
        $(document).on("click", "#addFontBtn", function () {
            const fontUrl = $("#fontInput").val()?.trim();

            if (!fontUrl) {
                console.warn("No font URL entered.");
                return;
            }

            try {
                // Ensure it's a proper URL, otherwise will throw
                const google_font_url = new URL(fontUrl);
                const pathParts = google_font_url.pathname.split('/');

                let fontName = "Unknown Font";

                if (pathParts.includes('specimen')) {
                    const specimenIndex = pathParts.indexOf('specimen');
                    fontName = pathParts[specimenIndex + 1];
                } else if (pathParts.includes('css2')) {
                    const fontNameMatch = fontUrl.match(/family=([^&]+)/);
                    fontName = fontNameMatch ? fontNameMatch[1] : "Unknown Font";
                }

                fontName = decodeURIComponent(fontName).replace(/\+/g, ' ');
                if (fontName && fontName !== "Unknown Font") {
                    const googleFontCssLink = `https://fonts.googleapis.com/css2?family=${fontName}&display=swap`;
                    $('head').append(`<link href="${googleFontCssLink}" rel="stylesheet" id="font-link-${fontName}">`);

                    // Preview the font
                    $('#previewContent').css('font-family', `'${fontName}', -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`);
                    rpc('/add/google/font', { 
                        'name': fontName,
                        'url': fontUrl,
                    }).then(function (data) {
                        if (data.status == 'limit_reached') {
                            $('#addFontBtn').prop('disabled', true);  
                            $('#fontLimitMsg').show();                
                            return;
                        }
                    
                        if (data.status == 'success') {
                            const fontId = data.id || Math.floor(Math.random() * 100000);
                    
                            // Remove "checked" from all radio buttons first
                            $('input[name="google_font_links_ids"]').prop('checked', false);
                    
                            // Render and append new font
                            const NewFontFamilyAdd = $(renderToElement("spiffy_theme_backend.AddNewFontFamily", {
                                fontId: data.id,
                                fontName: data.name,
                            }));  
                            $(".font-list").append(NewFontFamilyAdd);
                    
                            // Automatically check the newly added radio
                            setTimeout(function () {
                                $(`#font_family_${data.name.toLowerCase()}`).prop('checked', true).trigger('change');
                            }, 100); // Slight delay to ensure element is in DOM
                    
                            $('#fontExistsMsg').hide();
                        } else {
                            // Even if it's duplicate, still check the existing font
                            $(`input[name="google_font_links_ids"]`).prop('checked', false);
                            $(`#font_family_${data.name.toLowerCase()}`).prop('checked', true).trigger('change');
                            $('#fontExistsMsg').show();         
                        }
                    });
                    
                }
            } catch (err) {
                alert("Please enter a valid Google Fonts URL, e.g. https://fonts.google.com/specimen/Lato");
            }
        });
    
        $(document).on("click", ".delete-font", function () {
            const fontId = $(this).data("id");
        
            rpc('/delete/google/font', { 'id': fontId }).then(function (response) {
                if (response.status === "success") {
                    $(`#font_container_${fontId}`).remove();
                } else {
                    console.log("Error: " , response.message);
                }
            }).catch(function (err) {
                console.error("RPC Error while deleting font:", err);
            });
        });
    },

    _onCheckboxChange: function (ev) {
        const checkbox = ev.currentTarget;
        const fontId = checkbox.dataset.id;
        const selectedFontFamily = checkbox.dataset.family;
        const backendConfigId = parseInt(checkbox.dataset.backendConfigId);

        document.querySelectorAll('.font-checkbox').forEach(cb => {
            if (cb.dataset.family !== selectedFontFamily) {
                cb.checked = false;
            }
        });
    
        rpc("/update_single_font_selection", {
            'font_id': parseInt(fontId),
            'backend_config_id': backendConfigId
        }).then((data) => {
            console.log("Updated font_id on server:", data.font_id);
        });
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
        this._all_apps_menu_data()
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
    biz_TodoList_events: function () {
        var self = this;
        $('#close_to_do_sidebar').unbind().on('click', function (ev) { self._closeToDoSidebar(ev); })
        $('.note-options .note-delete a').unbind().on('click', function (ev) { self._deleteNote(ev); })
        $('.note-options .note-edit a').unbind().on('click', function (ev) { self._editNote(ev); })
    },

    _closeToDoSidebar: function (ev) {
        $('.navbar_to_do_list_data').toggleClass('visible')
        $('body.o_web_client').toggleClass('backdrop')
    },

    _deleteNote: function (ev) {
        var deleteButton = $(ev.currentTarget);
        var noteID = deleteButton.data('note-id');
        var noteSection = deleteButton.parents(".note_content")

        rpc('/delete/todo', {
            'noteID': noteID,
        }).then(function (rec) {
            if (rec) {
                noteSection.remove();
            } else {
                // TODO: we can put some alert for issue in deleting the note here
            }
        });
    },

    _editNote: function (ev) {
        var editButton = $(ev.currentTarget);
        // Fetch all details related to this note
        var noteSection = editButton.parents(".note_content")
        var note_id = noteSection.data('note-id');
        var note_title = noteSection.find('.note-details .note-title h2').text();
        var note_description_element = noteSection.find('.note-details .note-description .description-main');
        var note_description = note_description_element.html()

        var note_color_pallet = editButton.data('note-color');

        // Add all details of the note to edit dialog
        var edit_list = $('.to-do-sidebar-body .add-list');
        var edit_list_outer = $('.to-do-sidebar-body .add-list .add-list-outer');
        edit_list.find('input[name="note_id"]').attr('value', note_id);
        edit_list.find('input[name="note_id"]').val(note_id);
        edit_list_outer.find('.note-colors-option label[color-pallet="' + note_color_pallet + '"]').click();

        edit_list_outer.find('.note-title input').val(note_title);
        edit_list_outer.find('.note-description .note-description-input').html(note_description);
        edit_list_outer.find('.note-save-update #note-create').addClass('d-none');
        edit_list_outer.find('.note-save-update #note-update').removeClass('d-none');

        // Open the edit dialog after adding all the note details
        $('.to-do-sidebar-body').find('.add-new-list-btn').click();
    },



    _openToDoList: function () {
        var self = this
        self.showToDoSidebar();
        $('.navbar_to_do_list_data').toggleClass('visible');
        $('body.o_web_client').toggleClass('backdrop');
    },

    showToDoSidebar: function () {
        var self = this;
        $.get('/show/user/todo/list', {}).then(function (data) {
            $(".navbar_to_do_list_data").empty()
            $(".navbar_to_do_list_data").append(data)

            self.biz_TodoList_events();
            var showListSelf = self;
            $(".add-new-list-btn").on('click', function (ev) {
                if ($('.add-list').hasClass('d-none')) {
                    $(ev.currentTarget).addClass('close');
                    $('.add-list').removeClass('d-none');
                    $('.users-to-do-list').addClass('backdrop');
                } else {
                    $(ev.currentTarget).removeClass('close');
                    $('.add-list').addClass('d-none');
                    $('.users-to-do-list').removeClass('backdrop');

                    // empty all details and note id input on closing new note popup
                    var edit_list = $('.to-do-sidebar-body .add-list');
                    var edit_list_outer = $('.to-do-sidebar-body .add-list .add-list-outer');
                    edit_list.find('input[name="note_id"]').attr('value', '');
                    edit_list.find('input[name="note_id"]').val('');
                    edit_list_outer.find('.note-title input').val('');
                    edit_list_outer.find('.note-description .note-description-input').html('');
                    edit_list_outer.find('.note-save-update #note-create').removeClass('d-none');
                    edit_list_outer.find('.note-save-update #note-update').addClass('d-none');
                    edit_list_outer.find('.note-colors-option label[color-pallet="pallet_1"]').click();

                }
            });

            // create to do list task on 'Add' btn click
            $(".note-save-update .note-add").on('click', function (ev) {
                var self = this
                var to_do_body = $(".navbar_to_do_list_data").find('.to-do-sidebar-body');
                var note_id = $(to_do_body).find('input[name="note_id"]').val();
                var user_id = $(to_do_body).find('input[name="user_id"]');
                var note_title = $(to_do_body).find('.note-title .note-title-input').val();
                var note_description_element = $(to_do_body).find('.note-description .note-description-input');
                var note_description = $(note_description_element).html();
                var note_color_pallet = $(to_do_body).find('.note-colors-option input[name="noteColorPallet"]:checked').val();
                var is_update = $(ev.currentTarget).data('update');

                if (!user_id) {
                    return
                }
                var user_id = $(user_id).val();

                if (note_title === '' || note_description === '') {
                    return
                }

                var jsonDict = {
                    'user_id': user_id,
                    'note_title': note_title,
                    'note_description': note_description,
                    'is_update': is_update ? true : false,
                    'note_pallet': note_color_pallet,
                }

                if (is_update) {
                    jsonDict['note_id'] = note_id
                }

                rpc('/create/todo', jsonDict).then(function (rec) {
                    if (is_update) {
                        var existing_note = $('.users-to-do-list .note_content[data-note-id="' + note_id + '"]');
                        existing_note.remove();
                    }
                    $('.users-to-do-list').prepend(rec);
                    showListSelf.biz_TodoList_events();

                    // close note edit dialog
                    $('.to-do-sidebar-body').find('.add-new-list-btn').click();
                    $('.users-to-do-list').animate({ scrollTop: 0 }, "slow");
                });
            });
        })
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

