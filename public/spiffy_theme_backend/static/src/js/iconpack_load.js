/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { listView } from "@web/views/list/list_view";
import { registry } from "@web/core/registry";

export const SpiffyIconListView = {
   ...listView,
   buttonTemplate: "show_icon_pack",
};

registry.category("views").add("button_in_tree", SpiffyIconListView);