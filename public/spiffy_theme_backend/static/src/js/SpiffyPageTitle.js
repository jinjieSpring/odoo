/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { rpc } from "@web/core/network/rpc";
import { WebClient } from "@web/webclient/webclient";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";

patch(WebClient.prototype, {
    setup() {
        super.setup();
        var self = this
        this.currentCompany = user.activeCompany;
        rpc('/get/tab/title/',{}).then(function(rec) {
            var new_title = rec
            self.title.setParts({ zopenerp: new_title })
        })
    },
});