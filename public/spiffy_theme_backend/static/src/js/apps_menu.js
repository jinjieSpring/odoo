/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import {fuzzyLookup} from "@web/core/utils/search";
import { rpc } from "@web/core/network/rpc";
import { renderToFragment } from "@web/core/utils/render";
import { NavBar } from "@web/webclient/navbar/navbar";
import { patch } from "@web/core/utils/patch";
import { useRef, useState } from "@odoo/owl";
import { browser } from "@web/core/browser/browser";
import { renderToElement } from "@web/core/utils/render";
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

patch(NavBar.prototype, {
    setup() {
        super.setup();
        
        var self = this;
        $(document).on("keydown", "#app_menu_search", function(ev){self._AppsearchResultsNavigate(ev)});
        $(document).on("input", "#app_menu_search", function(ev){self._searchAppDrawerTimeout(ev)});
        $(document).on("click", "#search_result .search_list_content a", function(ev){self._ToggleDrawer(ev)});
        $(document).on("click", ".fav_app_select", function(ev){self._AddRemoveFavApps(ev)});
        $(document).on("click", ".appdrawer_section .app-box .o_app", function(ev){self._ToggleDrawer(ev)});
        
        var menuData = this.menuService.getApps()

        this._search_def = false;

        this._GetFavouriteApps()
        this._FavouriteAppsIsland()

        this.state = useState({
            ...this.state,
            results: [],
            offset: 0,
            hasResults: false,
        });

        this.searchBarInput = useRef("SearchBarInput");
        this._drawersearchableMenus = {};
        for (const menu of this.menuService.getApps()) {
            Object.assign(
                this._drawersearchableMenus,[this.menuService.getMenuAsTree(menu.id)].reduce(findNames,{}),
            );
        }
    },

    _ToggleDrawer: function (ev) {
        $('.o_main_navbar').toggleClass('appdrawer-toggle')
        $('.appdrawer_section').toggleClass('toggle')
        $('.o_app_drawer a').toggleClass('toggle')

        // reset app drawer search details on drawer close
        if (!$('.appdrawer_section').hasClass('toggle')) {
            $("input[id='app_menu_search']").val("")
            $(".appdrawer_section #search_result").empty()
            $('.appdrawer_section .apps-list .row').removeClass('d-none');
            $('#searched_main_apps').empty().addClass('d-none').removeClass('d-flex');
        }
    },

    _FavouriteAppsIsland: function (ev){
        var menu_data = this.menuService.getApps()
        let addedAppIds = new Set();
        if (this.favappsdata) {
            var rec = this.favappsdata
            if (rec.app_list.length) {
                $('.fav_app_island .fav_apps').empty();
                $.each(rec.app_list, function( index, value ) {
                    $.each(menu_data, function (key, data) {
                        if (addedAppIds.has(value['app_id'])) {
                            return;
                        }
                        if (data['id'] == value['app_id']){
                            if (value['web_icon'] != false){
                                var web_icon_ext = value['web_icon'].split('/icon.')[1]
                                var web_svg_src = value['web_icon'].replace(',', '/')
                            }
                            else {
                                var web_icon_ext = value['web_icon'].toString()
                                var web_svg_src = value['web_icon'].toString()
                            }
                            // TODO: qweb render
                            var app_actionPath = `/odoo/${data.actionPath || "action-" + data.actionID}`;
                            var favapps = $(renderToElement("FavoriteApps", {
                                app_name:value['name'],
                                app_id:value['app_id'],
                                app_xmlid:data['xmlid'],
                                app_actionid:data['actionID'],
                                use_icon:value['use_icon'],
                                icon_class_name:value['icon_class_name'],
                                icon_img:value['icon_img'],
                                web_icon: value['web_icon'],
                                web_icon_data:value['web_icon_data'],
                                web_icon_ext: web_icon_ext,
                                web_svg_src: web_svg_src,
                                app_actionModel:data['actionModel'],
                                app_actionPath: app_actionPath,
                            }))
                            $('.fav_app_island .fav_apps').append(favapps)
                            addedAppIds.add(value['app_id']);
                        }
                    })
                });
                $('.fav_app_island').removeClass('d-none')
            } else {
                $('.fav_app_island').addClass('d-none')
            }
        }
    },

    _GetFavouriteApps: function() {
        var apps = this.menuService.getApps()
        var self = this
        if (this.favappsdata) {
            var rec = this.favappsdata
            $.each(rec.app_list, function( index, value ) {
                $.each(apps, function( ind, val ) {
                    if (value['app_id'] == val.id) {
                        var target = ".o_app[data-menu-id="+val.id+"]";
                        var $target = $(target);
                        $target.parent().find('.fav_app_select .ri').addClass('active');
                    }
                });
            });
        } else {
            rpc('/get-favorite-apps', {}).then(function(rec) {
                if (rec) {
                    self.favappsdata = rec
                    $.each(rec.app_list, function( index, value ) {
                        $.each(apps, function( ind, val ) {
                            if (value['app_id'] == val.id) {
                                var target = ".o_app[data-menu-id="+val.id+"]";
                                var $target = $(target);
                                $target.parent().find('.fav_app_select .ri').addClass('active');
                            }
                        });
                    });
                    self._FavouriteAppsIsland()
                }
            });
        }
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

    _AddRemoveFavApps: function (ev) {
        var self = this 
        var app_id = $(ev.target).parent().find('.o_app').attr('data-menu-id')
        var app_name = $(ev.target).parent().find('.app-name').text()
        if ($(ev.target).find('.ri.active').length) {
            rpc('/remove-user-fav-apps', {
                'app_id':app_id,
            }).then(function(rec) {
                $(ev.target).find('.ri').removeClass('active');
                self._FavouriteAppsIsland()
            });
        } else {
            rpc('/update-user-fav-apps', {
                'app_name':app_name,
                'app_id':app_id,
            }).then(function(rec) {
                $(ev.target).find('.ri').addClass('active');
                self._FavouriteAppsIsland()
            });
        }
    },
    _searchApps: function(searchvals, containerSelector){
        var apps = this.menuService.getApps();
        var $searchContainer = $(containerSelector);

        // Hide container if search is empty
        if (!searchvals || searchvals.trim() === "") {
            $searchContainer.empty().addClass('d-none').removeClass('d-flex');
            return;
        }

        $searchContainer.empty().addClass('d-flex').removeClass('d-none');

        $.each(apps, function(index, app){
            if (app.name.toLowerCase().includes(searchvals.toLowerCase())) {
                var $appItem = $(renderToElement("SearchedApps", {
                    app_name: app.name,
                    app_id: app.menuID,
                    app_xmlid: app.xmlID,
                    app_actionid: app.actionID,
                }));

                $appItem.find('.o_app').attr("href", "#menu_id=" + app.id);

                // Icon logic
                var $iconContainer = $appItem.find('.app-image');
                var iconHtml = "";

                if (app.use_icon) {
                    if (app.icon_class_name) {
                        iconHtml = "<span class='ri " + app.icon_class_name + "'/>";
                    } else if (app.icon_img) {
                        iconHtml = "<img class='img img-fluid' src='/web/image/ir.ui.menu/" + app.id + "/icon_img' />";
                    } else if (!app.webIconData || app.webIconData.toString() === 'false' || app.webIconData === '/web_enterprise/static/img/default_icon_app.png') {
                        iconHtml = "<img class='img img-fluid' src='/spiffy_theme_backend_ent/static/description/bizople-icon.png' />";
                    } else {
                        iconHtml = "<img class='img img-fluid use_icon' src='/web/image/ir.ui.menu/" + app.id + "/web_icon_data' />";
                    }
                } else {
                    if (app.icon_img) {
                        iconHtml = "<img class='img img-fluid' src='/web/image/ir.ui.menu/" + app.id + "/icon_img' />";
                    } else if (!app.webIconData || app.webIconData.toString() === 'false' || app.webIconData === '/web_enterprise/static/img/default_icon_app.png') {
                        iconHtml = "<img class='img img-fluid' src='/spiffy_theme_backend_ent/static/description/bizople-icon.png' />";
                    } else {
                        iconHtml = "<img class='img img-fluid else' src='/web/image/ir.ui.menu/" + app.id + "/web_icon_data' />";
                    }
                }

                $iconContainer.append($(iconHtml));
                $searchContainer.append($appItem);
            }
        });

        this._GetFavouriteApps(); // refresh favourite logic if needed
    },

    _AppsearchResultsNavigate: function(ev) {
        // Find current results and active element (1st by default)
        const all = $(".appdrawer_section #search_result").find(".search_list_content"),
            pre_focused = all.filter(".navigate_active") || $(all[0]);
        let offset = all.index(pre_focused),
            key = ev.key;
        // Keyboard navigation only supports search results
        if (!all.length) {
            return;
        }
        // Transform tab presses in arrow presses
        if (key === "Tab") {
            ev.preventDefault();
            key = ev.shiftKey ? "ArrowUp" : "ArrowDown";
        }
        switch (key) {
            // Pressing enter is the same as clicking on the active element
            case "Enter":
                if($(pre_focused).length){
                    $(pre_focused).find('.autoComplete_highlighted')[0].click();
                    // $('.o_app_drawer .close_fav_app_btn')[0].click();
                }
                break;
            // Navigate up or down
            case "ArrowUp":
                offset--;
                break;
            case "ArrowDown":
                offset++;
                break;
            default:
                // Other keys are useless in this event
                return;
        }
        // Allow looping on results
        if (offset < 0) {
            offset = all.length + offset;
        } else if (offset >= all.length) {
            offset -= all.length;
        }
        // Switch active element
        var new_focused = $(all[offset]);
        pre_focused.removeClass("navigate_active");
        new_focused.addClass("navigate_active");
        var $targetElement = $(".appdrawer_section #search_result");
        var newScrollTop = new_focused + $targetElement.scrollTop() - $(".appdrawer_section #search_result").height() * 0.5;
        $targetElement.scrollTop(newScrollTop);
    },

    _menuInfo(key) {
        return this._drawersearchableMenus[key];
    },

    _searchAppDrawerTimeout: function (ev) {
        this._search_def = new Promise((resolve) => {
            setTimeout(resolve, 100);
        });
        this._search_def.then(this._searchMenuItems(ev));
    },

    _searchMenuItems: function(ev){
        var searchvals = $("input[id='app_menu_search']").val()
        this._searchApps(searchvals, '#searched_main_apps');       // Main apps
        this._searchApps(searchvals, '.favourite_apps #searched_main_apps'); // Favourite apps

        $(".appdrawer_section .apps-list .row").toggleClass('d-none',Boolean(searchvals.length));
        if (searchvals === "") {
            $(".appdrawer_section #search_result").empty();
            $(".appdrawer_section #searched_main_apps").empty().removeClass('d-flex').addClass('d-none');
            return;
        }
        const query = searchvals;
        this.state.hasResults = query !== "";
        var results = this.state.hasResults
            ? fuzzyLookup(searchvals, Object.keys(this._drawersearchableMenus), (k) => k)
            : [];
        // TODO: qweb render
        $(".appdrawer_section #search_result").empty().append(renderToFragment("spiffy_theme_backend.MenuSearchResults", {
                results: results,
                widget: this,
            })
        );
        this._AppdrawerIcons()
    },

    _applyAppdrawerIcons: function(rec) {
        var apps = this.menuService.getApps()
        $.each(apps, function( key, value ) {
            var target_tag = '.appdrawer_section a.o_app[data-menu-id='+value.id+']'
                var $tagtarget = $(target_tag)
                $tagtarget.find('.app-image').empty()

                var current_record = rec[value.id] && rec[value.id][0]
                if (!current_record) {
                    return
                }
                var spiffy_app_group = rec["spiffy_app_group"]
                value.id = current_record.id
                value.use_icon = current_record.use_icon
                value.icon_class_name = current_record.icon_class_name
                value.icon_img = current_record.icon_img
                value.spiffy_app_group_id = current_record.spiffy_app_group_id
                value.spiffy_app_group = spiffy_app_group
                if (current_record.use_icon) {
                    if (current_record.icon_class_name) {
                        var icon_image = "<span class='ri "+current_record.icon_class_name+"'/>"
                    } else if (current_record.icon_img) {
                        var icon_image = "<img class='img img-fluid' src='/web/image/ir.ui.menu/"+current_record.id+"/icon_img' />"
                    } else if (current_record.web_icon != false) {
                        var icon_data = current_record.web_icon.split('/icon.')
                        if (icon_data[1] == 'svg'){
                            var web_svg_icon = current_record.web_icon.replace(',', '/')
                            var icon_image = "<img class='img img-fluid' src='"+web_svg_icon+"' />"
                        } else {
                            var icon_image = "<img class='img img-fluid' src='data:image/"+icon_data[1]+";base64,"+current_record.web_icon_data+"' />"
                        }
                    } else{
                        var icon_image = "<img class='img img-fluid' src='/spiffy_theme_backend/static/description/bizople-icon.png' />"
                        }
                    $tagtarget.find('.app-image').append($(icon_image))
                } else {
                    if (current_record.icon_img) {
                        var icon_image = "<img class='img img-fluid' src='/web/image/ir.ui.menu/"+current_record.id+"/icon_img' />"
                    } else if (current_record.web_icon != false){
                        var icon_data = current_record.web_icon.split('/icon.')
                        if (icon_data[1] == 'svg'){
                            var web_svg_icon = current_record.web_icon.replace(',', '/')
                            var icon_image = "<img class='img img-fluid' src='"+web_svg_icon+"' />"
                        } else {
                            var icon_image = "<img class='img img-fluid' src='data:image/"+icon_data[1]+";base64,"+current_record.web_icon_data+"' />"
                        }
                    } else{
                        var icon_image = "<img class='img img-fluid' src='/spiffy_theme_backend/static/description/bizople-icon.png' />"
                    }
                    $tagtarget.find('.app-image').append($(icon_image))
                }
        })
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