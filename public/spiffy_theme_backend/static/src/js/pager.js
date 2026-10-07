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
        var size = $(window).width();
        const chatterPosition = await rpc('/update/chatter/position', {});
        if (chatterPosition === 'chatter_right') {
            $("body").find('.chatter_position_right').addClass('active');
            $("body").find('.chatter_position_bottom').removeClass('active');
        } else {
            $("body").find('.chatter_position_right').removeClass('active');
            $("body").find('.chatter_position_bottom').addClass('active');
        }

        const showFilter = await rpc('/update/filter/row', {});
        if (showFilter === true) {
            $("body").addClass("show_filter_row");
            $(".filter_row").removeClass("d-none");
            $(".show_filter_row").addClass("active");
        } else {
            $("body").removeClass("show_filter_row");
            $(".filter_row").addClass("d-none");
            $(".show_filter_row").removeClass("active");
        }
    },

    async updateChatterPosition(position) {
        await rpc('/update/chatter/position', {
            'chatter_position': position
        }).then(function (rec) {

        })
        this.chatter_position = position

        if (position === 'chatter_right') {
            $("body").removeClass('chatter_bottom');
            $("body").addClass(position);
            $("body").find('.chatter_position_right').addClass('active')
            $("body").find('.chatter_position_bottom').removeClass('active')
        }
        else {
            $("body").removeClass('chatter_right');
            $("body").addClass(position);
            $("body").find('.chatter_position_right').removeClass('active')
            $("body").find('.chatter_position_bottom').addClass('active')
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
        const isActive = $("body").hasClass("show_filter_row");

        if (isActive) {
            $("body").removeClass("show_filter_row");
            $(".show_filter_row").removeClass("active");
            $(".filter_row").addClass("d-none");
            rpc('/update/filter/row', {
                show_filter_row: false,
            });
        } else {
            $("body").addClass("show_filter_row");
            $(".show_filter_row").addClass("active");
            $(".filter_row").removeClass("d-none");
            rpc('/update/filter/row', {
                show_filter_row: true,
            });
        }
    },

})