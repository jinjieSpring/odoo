/** @odoo-module **/

import { Component, onMounted, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { AiChatDialog } from "./ai_chat";

export class AiSystrayMenu extends Component {
    static template = "ai_base.SystrayMenu";
    static props = {};

    setup() {
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({ modelReady: true, modelStatus: {} });
        onMounted(() => this.refreshStatus());
    }

    get iconTitle() {
        return this.state.modelReady
            ? _t("AI Assistant")
            : this.state.modelStatus.message || _t("Model not ready");
    }

    async refreshStatus() {
        try {
            const defaults = await rpc("/ai_base/defaults", {});
            this.state.modelReady = Boolean(defaults.model_ready);
            this.state.modelStatus = defaults.model_status || {};
        } catch (error) {
            console.error("ai_base: failed to refresh the model status", error);
        }
    }

    async onClick() {
        if (!this.state.modelReady) {
            this.notification.add(
                this.state.modelStatus.message || _t("No model is configured."),
                { type: "warning", title: _t("Model not ready") }
            );
            return;
        }
        this.dialog.add(AiChatDialog, {});
    }
}

registry.category("systray").add("ai_base_systray", {
    Component: AiSystrayMenu,
    sequence: 1001,
});
