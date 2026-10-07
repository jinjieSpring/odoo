/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { Widget } from "@web/views/widgets/widget";

const COLOR_PALLETS = {
    pallet_1: ["#6B3F69", "#ffffff", "#1b1b1b", "#6B3f69b3"],
    pallet_2: ["#84994F", "#ffffff", "#1b1b1b", "#84994Fb3"],
    pallet_3: ["#097c67", "#ffffff", "#1b1b1b", "#76C893b3"],
    pallet_4: ["#985ffd", "#ffffff", "#1b1b1b", "#DADDFF"],
    pallet_5: ["#3396D3", "#ffffff", "#1b1b1b", "#3396D3b3"],
    pallet_6: ["#1A2A80", "#ffffff", "#1b1b1b", "#ABB7F5"],
    pallet_7: ["#433878", "#ffffff", "#1b1b1b", "#C6BCF6"],
    pallet_8: ["#615fff", "#ffffff", "#1b1b1b", "#DADDFF"],
    pallet_9: ["#B9375D", "#ffffff", "#1b1b1b", "#B9375Db3"],
    pallet_10: ["#8a0020", "#ffffff", "#1b1b1b", "#E3C8CE"],
    pallet_11: ["#465C88", "#ffffff", "#1b1b1b", "#465C88b3"],
    pallet_12: ["#1e2b52", "#ffffff", "#1b1b1b", "#64729d"],
    pallet_13: ["#0D5EA6", "#ffffff", "#1b1b1b", "#C7E9FF"],
    pallet_14: ["#FFB823", "#ffffff", "#1b1b1b", "#FBEAC4"],
    pallet_15: ["#F08B51", "#ffffff", "#1b1b1b", "#F08B51b3"],
    pallet_16: ["#eb5858", "#ffffff", "#1b1b1b", "#eb5858b3"],
    pallet_17: ["#0097a7", "#ffffff", "#1b1b1b", "#61ccd7"],
};

function applyRootColors(primary, text, textRgba, primaryRgba) {
    $(":root").css({
        "--light-theme-primary-color": primary,
        "--light-theme-primary-text-color": text,
        "--primary-text-rgba": textRgba,
        "--primary-rgba": primaryRgba,
    });
}

class ColorPallet extends Widget {
    constructor(parent) {
        super(parent);
        for (const [name, colors] of Object.entries(COLOR_PALLETS)) {
            this[name] = () => applyRootColors(...colors);
        }
    }
    custom_color_pallet(record_dict) {
        $(":root").css({
            "--light-theme-primary-color": record_dict.light_primary_bg_color,
            "--light-theme-primary-text-color": record_dict.light_primary_text_color,
            "--primary-rgba": record_dict.light_primary_bg_color + "b3",
        });
    }
    menu_shape_color_pallet(record_dict) {
        let hex = Math.round(record_dict.menu_shape_bg_color_opacity * 255).toString(16);
        if (hex.length === 1) {
            hex = "0" + hex;
        }
        $(":root").css({
            "--menu-shape-bg-color": record_dict.menu_shape_bg_color + hex,
        });
    }
    custom_app_drawer_color_pallet(record_dict) {
        $(":root").css({
            "--app-drawer-custom-bg-color": record_dict.appdrawer_custom_bg_color,
            "--app-drawer-custom-text-color": record_dict.appdrawer_custom_text_color,
        });
    }
}

export { ColorPallet };
