/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { Pager } from "@web/core/pager/pager";
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { onWillDestroy, onMounted, useState } from "@odoo/owl";
import { setChatterPosition, setShowFilterRow, spiffyThemeState } from "@spiffy_theme_backend/js/menu";

patch(Pager.prototype, {
    setup() {
        super.setup();
        // Reactive state driving the spiffy buttons in the Pager template.
        // The matching body classes are global theme flags consumed by SCSS;
        // they are synced from this state, never queried back.
        this.spiffyPager = useState({
            dialogOpen: document.body.classList.contains("modal-open"),
        });
        // Chatter position and the filter row are filled by the navbar
        // bootstrap call. Reading the shared state avoids a request per pager.
        this.themeState = useState(spiffyThemeState);
        onWillDestroy(() => {
            this._modalObserver?.disconnect();
        });
        onMounted(() => {
            const observer = new MutationObserver(() => {
                this.spiffyPager.dialogOpen = document.body.classList.contains("modal-open");
            });
            observer.observe(document.body, {
                attributes: true,
                attributeFilter: ['class'],
            });
            this._modalObserver = observer;
        });
    },

    // Expand/collapse-all button for grouped list views. The button lives in
    // the Pager template; the list model root comes from the controller env.
    get spiffyListRoot() {
        return this.env.model?.root;
    },
    get isGroupedList() {
        return Boolean(this.spiffyListRoot?.isGrouped);
    },
    get anyGroupExpanded() {
        if (!this.isGroupedList) {
            return false;
        }
        return (this.spiffyListRoot.groups || []).some((group) => !group.isFolded);
    },
    groupsExpand(ev) {
        ev.stopPropagation();
        if (!this.isGroupedList) {
            return;
        }
        this.spiffyListRoot.groups.forEach((group) => group.toggle());
    },

    async updateChatterPosition(position) {
        setChatterPosition(position);
        await rpc('/update/chatter/position', {
            'chatter_position': position
        });
    },

    async toggleFilterClass() {
        setShowFilterRow(!this.themeState.showFilterRow);
        rpc('/update/filter/row', {
            show_filter_row: this.themeState.showFilterRow,
        });
    },

})
