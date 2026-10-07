/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { UserMenu } from "@web/webclient/user_menu/user_menu";
import { patch } from "@web/core/utils/patch";
import { user } from "@web/core/user";
import { session } from '@web/session';
import { router } from "@web/core/browser/router";

patch(UserMenu.prototype, {
    setup() {
        super.setup();
        //  greeting
        var current_time_hr = new Date().getHours().toLocaleString("en-US", { timeZone: user.tz  });
        if ((parseInt(current_time_hr) >= 6) && (parseInt(current_time_hr) < 12)){
            var greeting = "Good Morning"
        } else if ((parseInt(current_time_hr) >= 12) && parseInt(current_time_hr) <= 18) {
            var greeting = "Good Afternoon"
        } else {
            var greeting = "Good Evening"
        }
        this.greeting = greeting
    }
});
