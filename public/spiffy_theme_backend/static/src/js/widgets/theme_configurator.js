/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { Component, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";

const range = (n) => Array.from({ length: n }, (_, i) => i + 1);

export class ThemeConfigurator extends Component {
    static template = "spiffy_theme_backend.ThemeConfigurator";
    static props = {
        // Shared reactive state owned by the NavBar: { visible: Boolean }
        state: Object,
    };

    setup() {
        this.state = useState({
            loaded: false,
            configId: false,
            config: {},
            fonts: [],
            selectedFontId: null,
            existingLightBgImage: false,
            existingMenuBgImage: false,
            lightBgImageData: null,
            menuBgImageData: null,
            lightBgFileName: "",
            menuBgFileName: "",
            lightBgPreviewSrc: "",
            menuBgPreviewSrc: "",
            fontLimitReached: false,
            fontExists: false,
            previewFontName: null,
        });
        this.fontInputRef = useRef("fontInput");

        this.themeStyles = [
            { value: "biz_theme_rounded", id: "theme_style_rounded", img: "theme-style-rounded.png", alt: "Rounded Theme" },
            { value: "biz_theme_standard", id: "theme_style_standard", img: "theme-style-standard.png", alt: "Standard Theme" },
            { value: "biz_theme_square", id: "theme_style_square", img: "theme-style-square.png", alt: "Square Theme" },
        ];
        this.menuPositions = [
            { value: "top_menu_horizontal", id: "top_menu_style_horizontal", img: "theme-menu_horizontal.png", alt: "Menu horizontal" },
            { value: "top_menu_vertical", id: "top_menu_style_vertical", img: "theme-menu-vertical-center.png", alt: "Menu Vertical" },
            { value: "top_menu_vertical_mini", id: "top_menu_style_vertical_mini", img: "theme-menu-vertical_mini.png", alt: "Menu Vertical" },
        ];
        this.verticalBgs = [
            { value: "top_menu_vertical_bg1", id: "top_menu_vertical_bg1", img: "top-menu-v2-bg-one.png" },
            { value: "top_menu_vertical_bg2", id: "top_menu_vertical_bg2", img: "top-menu-v2-bg-two.png" },
            { value: "top_menu_vertical_bg3", id: "top_menu_vertical_bg3", img: "top-menu-v2-bg-three.png" },
        ];
        this.shapeStyles = [
            { value: "biz_shape_rounded", id: "shape_style_rounded", img: "shape-style-rounded.png", label: _t("Rounded") },
            { value: "biz_shape_circle", id: "shape_style_standard", img: "shape-style-standard.png", label: _t("Circle") },
            { value: "biz_shape_square", id: "shape_style_square", img: "shape-style-square.png", label: _t("Square") },
        ];
        this.listDensities = [
            { value: "list_comfortable", id: "list_comfortable", img: "list_comfortable.png", title: _t("Comfortable") },
            { value: "list_compact", id: "list_compact", img: "list_compact.png", title: _t("Compact") },
        ];
        this.inputStyles = [
            { value: "input_borderless", id: "input_borderless", img: "input-style-borderless.png", title: _t("Borderless") },
            { value: "input_bottom_border", id: "input_bottom_border", img: "input-style-bottom-border.png", title: _t("Border Bottom") },
            { value: "input_bordered", id: "input_bordered", img: "input-style-bordered.png", title: _t("Bordered") },
        ];
        this.fontSizes = [
            { value: "font_small", id: "font_size_1", cls: "font_small", label: _t("Small") },
            { value: "font_medium", id: "font_size_2", cls: "font_medium", label: _t("Medium") },
            { value: "font_large", id: "font_size_3", cls: "font_large", label: _t("Large") },
        ];
        this.colorPallets = range(17);
        this.drawerPallets = range(17);
        this.loaders = range(10);
        this.tabStyles = [
            { value: "tab_style_1", cls: "tab-style-one" },
            { value: "tab_style_2", cls: "tab-style-two" },
            { value: "tab_style_3", cls: "tab-style-three" },
            { value: "tab_style_4", cls: "tab-style-four" },
        ];
        this.checkboxStyles = range(4);
        this.radioStyles = range(4);
        this.popupStyles = [
            { value: "popup_style_1", label: _t("Fade") },
            { value: "popup_style_2", label: _t("Vertical Flip") },
            { value: "popup_style_3", label: _t("BounceIn") },
            { value: "popup_style_4", label: _t("Shrink") },
        ];
        this.separatorStyles = range(4);

        useEffect(
            (visible) => {
                document.body.classList.toggle("backdrop", Boolean(visible));
                if (visible && !this.state.loaded) {
                    this.loadData();
                }
            },
            () => [this.props.state.visible]
        );
        onWillUnmount(() => document.body.classList.remove("backdrop"));
    }

    async loadData() {
        const data = await rpc("/color/pallet/data/json/", {});
        this.state.configId = data.config_id;
        Object.assign(this.state.config, data.config);
        this.state.fonts = data.fonts;
        const selected = data.fonts.find((font) => font.is_selected);
        this.state.selectedFontId = selected ? selected.id : null;
        this.state.existingLightBgImage = data.light_bg_image;
        this.state.existingMenuBgImage = data.top_menu_custom_bg_vertical;
        if (data.config_id) {
            this.state.lightBgPreviewSrc = `/web/image/backend.config/${data.config_id}/light_bg_image`;
            this.state.menuBgPreviewSrc = `/web/image/backend.config/${data.config_id}/top_menu_custom_bg_vertical`;
        }
        this.state.loaded = true;
    }

    get previewFontStyle() {
        if (!this.state.previewFontName) {
            return "";
        }
        return `font-family: '${this.state.previewFontName}', -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;`;
    }

    // Generic binding: every config input carries data-field="<config key>".
    onConfigChange(ev) {
        const field = ev.target.dataset.field;
        if (!field) {
            return;
        }
        const value = ev.target.type === "checkbox" ? ev.target.checked : ev.target.value;
        this.state.config[field] = value;
        if (field === "vertical_background") {
            // Live preview on the page behind the panel, same as before.
            document.body.classList.toggle("vertical_background", Boolean(value));
        }
    }

    _readImageInput(input, assign) {
        const file = input.files && input.files[0];
        if (!file) {
            return;
        }
        const reader = new FileReader();
        reader.onload = (e) => assign(e.target.result, file);
        reader.readAsDataURL(file);
    }

    onLightBgFileChange(ev) {
        this.state.lightBgFileName = (ev.target.value || "").split("\\").pop();
        this._readImageInput(ev.target, (dataUrl, file) => {
            this.state.lightBgImageData = dataUrl;
            this.state.lightBgPreviewSrc = URL.createObjectURL(file);
        });
    }

    onMenuBgFileChange(ev) {
        this.state.menuBgFileName = (ev.target.value || "").split("\\").pop();
        this._readImageInput(ev.target, (dataUrl, file) => {
            this.state.menuBgImageData = dataUrl;
            this.state.menuBgPreviewSrc = URL.createObjectURL(file);
        });
    }

    selectFont(fontId) {
        this.state.selectedFontId = fontId;
        this.state.fonts.forEach((font) => {
            font.is_selected = font.id === fontId;
        });
        rpc("/update_single_font_selection", {
            font_id: fontId,
            backend_config_id: this.state.configId,
        });
    }

    _ensureFontLink(fontName) {
        const id = `font-link-${fontName}`;
        if (!document.getElementById(id)) {
            const link = document.createElement("link");
            link.href = `https://fonts.googleapis.com/css2?family=${fontName}&display=swap`;
            link.rel = "stylesheet";
            link.id = id;
            document.head.appendChild(link);
        }
    }

    async addGoogleFont() {
        const fontUrl = this.fontInputRef.el?.value?.trim();
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
            if (!fontName || fontName === "Unknown Font") {
                return;
            }
            this._ensureFontLink(fontName);
            this.state.previewFontName = fontName;

            const data = await rpc('/add/google/font', {
                'name': fontName,
                'url': fontUrl,
            });
            if (data.status == 'limit_reached') {
                this.state.fontLimitReached = true;
                return;
            }
            this.state.fonts.forEach((font) => {
                font.is_selected = false;
            });
            if (data.status == 'success') {
                this.state.fonts.push({
                    id: data.id,
                    name: data.name,
                    url: data.url,
                    is_selected: true,
                });
                this.state.fontExists = false;
            } else {
                // Duplicate: re-select the existing font.
                const existing = this.state.fonts.find((font) => font.id === data.id);
                if (existing) {
                    existing.is_selected = true;
                }
                this.state.fontExists = true;
            }
            this.state.selectedFontId = data.id;
        } catch (err) {
            alert(_t("Please enter a valid Google Fonts URL, e.g. https://fonts.google.com/specimen/Lato"));
        }
    }

    async deleteFont(font) {
        const response = await rpc('/delete/google/font', { 'id': font.id });
        if (response.status === "success") {
            const index = this.state.fonts.findIndex((f) => f.id === font.id);
            if (index !== -1) {
                this.state.fonts.splice(index, 1);
            }
            if (this.state.selectedFontId === font.id) {
                this.state.selectedFontId = null;
            }
            this.state.fontLimitReached = false;
        } else {
            console.log("Error: ", response.message);
        }
    }

    async save() {
        const c = this.state.config;
        await rpc('/color/pallet/', {
            'light_primary_bg_color': c.light_primary_bg_color,
            'light_primary_text_color': c.light_primary_text_color,

            'apply_light_bg_img': c.apply_light_bg_img,
            'app_light_bg_image': this.state.lightBgImageData
                || (this.state.existingLightBgImage ? 'data:image/png;base64,' + this.state.existingLightBgImage : false),
            'vertical_app_menu_bg_image': this.state.menuBgImageData
                || (this.state.existingMenuBgImage ? 'data:image/png;base64,' + this.state.existingMenuBgImage : false),

            'attachment_in_tree_view': c.attachment_in_tree_view,

            'selected_separator': c.separator,
            'selected_tab': c.tab,
            'selected_checkbox': c.checkbox,
            'selected_radio': c.radio,
            'selected_popup': c.popup,
            'custom_color_pallet': c.use_custom_colors,
            'selected_color_pallet': c.color_pallet,

            'custom_drawer_bg': c.appdrawer_custom_bg_color,
            'custom_drawer_text': c.appdrawer_custom_text_color,
            'menu_shape_bg': c.menu_shape_bg_color,
            'custom_drawer_color_pallet': c.use_custom_drawer_color,
            'selected_drawer_color_pallet': c.drawer_color_pallet,
            'google_font_links_ids': this.state.selectedFontId || undefined,

            'selected_loader': c.loader_style,
            'selected_fontsize': c.font_size,
            'selected_top_menu_position': c.top_menu_position,
            'selected_top_menu_bg_vertical': c.top_menu_bg_vertical,
            'selected_theme_style': c.theme_style,
            'apply_menu_shape_style': c.apply_menu_shape_style,
            'vertical_background': c.vertical_background,
            'selected_menu_shape': c.shape_style,
            'selected_list_view_density': c.list_view_density,
            'selected_list_view_sticky_header': c.list_view_sticky_header ? "on" : false,
            'selected_input_style': c.input_style,
            'menu_shape_bg_color_opacity': c.menu_shape_bg_color_opacity,
        });
        window.location.reload();
    }

    async reset() {
        const data = await rpc('/color/pallet/reset/', {});
        if (data.status === "success") {
            window.location.reload();
        }
    }

    close() {
        this.props.state.visible = false;
    }
}
