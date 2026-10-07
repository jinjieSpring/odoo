/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
const commandProviderRegistry = registry.category("command_provider");
const commandSetupRegistry = registry.category("command_setup");
commandSetupRegistry.add(":", {
    emptyMessage: _t("No record found"),
    name: _t("Global Search"),
    placeholder: _t("Search for a Record..."),
});
commandProviderRegistry.add("find_or_start_menu_record_search", {
    namespace: ":",
    async provide(env, options) {
        const result = [];
        const searchValue = options.searchValue?.trim();
        if (!searchValue) {
            return result;
        }
        const RecordList = await rpc("/spiffy/global/search", { search: searchValue });
        for (const record of RecordList) {
            result.push({
                name: `${record.model_name} - ${record.display_name}`,  
                text: record.display_name,
                category: "colon_search",

                // Open record
                action() {
                    const actionService = env.services.action;
                    actionService.doAction({
                        type: "ir.actions.act_window",
                        res_model: record.model,
                        res_id: record.id,
                        views: [[false, "form"]],
                    });
                },
                href: `/web#model=${record.model}&id=${record.id}&view_type=form`,
            });
        }
        return result;
    },
});