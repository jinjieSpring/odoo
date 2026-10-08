/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { Pager } from "@web/core/pager/pager";
import { patch } from "@web/core/utils/patch";
import { rpc } from "@web/core/network/rpc";
import { onWillDestroy, onMounted } from "@odoo/owl";

patch(Pager.prototype, {
    setup() {
        super.setup();        
        this.isDialogOpen = document.body.classList.contains("modal-open");
        onWillDestroy(() => {
            this.isDialogOpen = false;
            this._modalObserver?.disconnect();
        });
        onMounted(() => {
            setTimeout(() => {
                this._toggleChatterButtons();
            }, 0);

            this._loadPreferences();
            const observer = new MutationObserver(() => {
                this.isDialogOpen = document.body.classList.contains("modal-open");
            });

            observer.observe(document.body, {
                attributes: true,
                attributeFilter: ['class'],
            });

            this._modalObserver = observer;
        });        
    },

    async _loadPreferences() {
        const chatterPosition = await rpc('/update/chatter/position', {});
        const rightActive = chatterPosition === "chatter_right";
        this._setMatchedClass(".chatter_position_right", "active", rightActive);
        this._setMatchedClass(".chatter_position_bottom", "active", !rightActive);

        const showFilter = await rpc('/update/filter/row', {});
        document.body.classList.toggle("show_filter_row", showFilter === true);
        this._setMatchedClass(".filter_row", "d-none", showFilter !== true);
        this._setMatchedClass(".show_filter_row", "active", showFilter === true);
    },

    _setMatchedClass(selector, className, enabled) {
        document.querySelectorAll(selector).forEach((el) => el.classList.toggle(className, enabled));
    },

    async updateChatterPosition(position) {
        await rpc('/update/chatter/position', {
            'chatter_position': position
        });
        this.chatter_position = position

        if (position === 'chatter_right') {
            document.body.classList.remove("chatter_bottom");
            document.body.classList.add(position);
            this._setMatchedClass(".chatter_position_right", "active", true);
            this._setMatchedClass(".chatter_position_bottom", "active", false);
        }
        else {
            document.body.classList.remove("chatter_right");
            document.body.classList.add(position);
            this._setMatchedClass(".chatter_position_right", "active", false);
            this._setMatchedClass(".chatter_position_bottom", "active", true);
        }
    },


    _toggleChatterButtons() {
        const viewType = this.env.config.viewType || this.env.viewType;
        const isFormView = viewType === 'form';
        const btnRight = document.querySelector('.chatter_position_right');
        const btnBottom = document.querySelector('.chatter_position_bottom');
        if (btnRight && btnBottom) {
            const shouldHide = !isFormView;
            [btnRight, btnBottom].forEach(btn =>
                btn.classList.toggle('d-none', shouldHide)
            );
        }
    },
    async toggleFilterClass() {
        const isActive = document.body.classList.contains("show_filter_row");

        if (isActive) {
            document.body.classList.remove("show_filter_row");
            this._setMatchedClass(".show_filter_row", "active", false);
            this._setMatchedClass(".filter_row", "d-none", true);
            rpc('/update/filter/row', {
                show_filter_row: false,
            });
        } else {
            document.body.classList.add("show_filter_row");
            this._setMatchedClass(".show_filter_row", "active", true);
            this._setMatchedClass(".filter_row", "d-none", false);
            rpc('/update/filter/row', {
                show_filter_row: true,
            });
        }
    },

})