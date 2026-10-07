/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { patch } from "@web/core/utils/patch";
import { Widget } from "@web/views/widgets/widget";
class ColorPallet extends Widget {
    constructor(parent) {
        super(parent);
    }
    pallet_1() {
        $(':root').css({
            "--light-theme-primary-color": "#6B3F69",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#6B3f69b3',
        });
    }
    pallet_2() {
        $(':root').css({
            "--light-theme-primary-color": "#84994F",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#84994Fb3',
        });
    }
    pallet_3() {
        $(':root').css({
            "--light-theme-primary-color": "#097c67",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#76C893b3',
        });
    }
    pallet_4() {
        $(':root').css({
            "--light-theme-primary-color": "#985ffd",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#DADDFF',
        });
    }
    pallet_5() {
        $(':root').css({
            "--light-theme-primary-color": "#3396D3",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#3396D3b3',
        });
    }
    pallet_6() {
        $(':root').css({
            "--light-theme-primary-color": "#1A2A80",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#ABB7F5',
        });
    }
    pallet_7() {
        $(':root').css({
            "--light-theme-primary-color": "#433878",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#C6BCF6',
        });
    }
    pallet_8() {
        $(':root').css({
            "--light-theme-primary-color": "#615fff",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#DADDFF',
        });
    }
    pallet_9() {
        $(':root').css({
            "--light-theme-primary-color": "#B9375D",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#B9375Db3',
        });
    }
    pallet_10() {
        $(':root').css({
            "--light-theme-primary-color": "#8a0020",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#E3C8CE',
        });
    }

    pallet_11() {
        $(':root').css({
            "--light-theme-primary-color": "#465C88",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#465C88b3',
        });
    }
    pallet_12() {
        $(':root').css({
            "--light-theme-primary-color": "#1e2b52",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#64729d',
        });
    }
    pallet_13() {
        $(':root').css({
            "--light-theme-primary-color": "#0D5EA6",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#C7E9FF',
        });
    }
    pallet_14() {
        $(':root').css({
            "--light-theme-primary-color": "#FFB823",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#FBEAC4',
        });
    }
    pallet_15() {
        $(':root').css({
            "--light-theme-primary-color": "#F08B51",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#F08B51b3',
        });
    }
    pallet_16() {
        $(':root').css({
            "--light-theme-primary-color": "#eb5858",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#eb5858b3',
        });
    }
    pallet_17() {
        $(':root').css({
            "--light-theme-primary-color": "#0097a7",
            "--light-theme-primary-text-color": "#ffffff",
            "--primary-text-rgba": '#1b1b1b',
            "--primary-rgba": '#61ccd7',
        });
    }
    custom_color_pallet(record_dict) {
        $(':root').css({
            "--light-theme-primary-color": record_dict.light_primary_bg_color,
            "--light-theme-primary-text-color": record_dict.light_primary_text_color,
            "--primary-rgba": record_dict.light_primary_bg_color + 'b3',
        });
    }
    menu_shape_color_pallet(record_dict) {
        var converthex = Math.round(record_dict.menu_shape_bg_color_opacity * 255).toString(16);
        if (converthex.length === 1) {
            var hex = "0" + converthex;
        }
        else {
            var hex = converthex
        }
        $(':root').css({
            "--menu-shape-bg-color": record_dict.menu_shape_bg_color + hex,
        });
    }
    custom_app_drawer_color_pallet(record_dict) {
        $(':root').css({
            "--app-drawer-custom-bg-color": record_dict.appdrawer_custom_bg_color,
            "--app-drawer-custom-text-color": record_dict.appdrawer_custom_text_color,
        });
    }

};
export { ColorPallet }; 