/** @odoo-module **/

import { Component, onMounted, useExternalListener, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { HdaiChatDialog } from "./hdai_chat_dialog";

/**
 * Visual entry point: systray AI icon at the far left of the notification
 * area with an expanding quick input widget (Linkin AI design).
 */
export class HdaiSystrayMenu extends Component {
    static template = "hdai_base.SystrayMenu";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.actionService = useService("action");
        this.inputRef = useRef("input");
        this.state = useState({
            expanded: false,
            content: "",
            modelReady: true,
            modelStatus: {},
        });
        useExternalListener(window, "keydown", this.onGlobalKeydown);
        useExternalListener(
            window,
            "hdai:systray-refresh",
            () => this.refreshStatus()
        );
        onMounted(() => this.refreshStatus());
    }

    get hasContent() {
        return this.state.content.trim().length > 0;
    }

    get iconTitle() {
        return this.state.modelReady
            ? _t("AI Assistant")
            : this.state.modelStatus.message || _t("Model not ready");
    }

    async refreshStatus() {
        try {
            const defaults = await this.orm.call(
                "hdai.session",
                "action_get_defaults",
                []
            );
            this.state.modelReady = Boolean(defaults.model_ready);
            this.state.modelStatus = defaults.model_status || {};
        } catch (error) {
            console.error("hdai: failed to refresh the model status", error);
        }
    }

    expand() {
        if (!this.state.expanded) {
            this.state.expanded = true;
        }
    }

    collapse() {
        if (this.state.expanded) {
            this.state.expanded = false;
        }
    }

    onMouseEnter() {
        this.expand();
    }

    onMouseLeave() {
        if (!this.hasContent) {
            this.collapse();
        }
    }

    onGlobalKeydown(ev) {
        if (!this.state.expanded) {
            return;
        }
        const tag = ev.target && ev.target.tagName;
        if (tag && ["INPUT", "TEXTAREA", "SELECT"].includes(tag)) {
            return;
        }
        const isPrintable =
            ev.key && ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey && !ev.altKey;
        if (isPrintable || ev.keyCode === 229) {
            this.inputRef.el.focus();
        }
    }

    onKeyDown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.onSend();
        }
    }

    async onSend() {
        const content = this.state.content.trim();
        if (!(await this.openChat(content))) {
            return;
        }
        this.state.content = "";
    }

    async onClickIcon() {
        this.collapse();
        await this.openChat("");
    }

    async openChat(pendingMessage) {
        if (!this.state.modelReady) {
            this.showModelWarning();
            return false;
        }
        this.collapse();
        let sessionId = false;
        if (pendingMessage) {
            try {
                sessionId = await this.orm.call(
                    "hdai.session",
                    "action_create_from_input",
                    [pendingMessage]
                );
            } catch (error) {
                console.error("hdai: failed to create session", error);
                this.notification.add(
                    _t("Failed to start the conversation: %s", error.message || error),
                    { type: "danger" }
                );
            }
        }
        this.dialog.add(HdaiChatDialog, {
            sessionId: sessionId || undefined,
            pendingMessage: pendingMessage || undefined,
        });
        return true;
    }

    showModelWarning() {
        const status = this.state.modelStatus || {};
        const options = {
            type: "warning",
            title: status.title || _t("Model not ready"),
            sticky: true,
        };
        if (user.isAdmin) {
            options.buttons = [
                {
                    name: _t("Open AI Assistant Settings"),
                    onClick: () => this.openSettings(),
                },
            ];
        }
        this.notification.add(
            status.message || _t("No model is configured."),
            options
        );
    }

    openSettings() {
        this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "res.config.settings",
            name: _t("AI Assistant Settings"),
            view_mode: "form",
            views: [[false, "form"]],
            target: "inline",
            context: { module: "hdai" },
        });
    }
}

registry.category("systray").add("hdai_systray", {
    Component: HdaiSystrayMenu,
    sequence: 1000,
});

registry.category("actions").add("hdai_refresh_systray", () => {
    window.dispatchEvent(new CustomEvent("hdai:systray-refresh"));
    return { type: "ir.actions.client", tag: "soft_reload" };
});

// Open the AI Assistant tab of the settings page and refresh the systray icon.
registry.category("actions").add("hdai_open_settings", () => {
    window.dispatchEvent(new CustomEvent("hdai:systray-refresh"));
    return {
        type: "ir.actions.act_window",
        res_model: "res.config.settings",
        name: _t("AI Assistant Settings"),
        view_mode: "form",
        views: [[false, "form"]],
        target: "inline",
        context: { module: "hdai" },
    };
});

registry.category("actions").add("hdai_open_chat", (env) => {
    return (async () => {
        const defaults = await env.services.orm.call(
            "hdai.session",
            "action_get_defaults",
            []
        );
        if (!defaults.model_ready) {
            const status = defaults.model_status || {};
            const options = {
                type: "warning",
                title: status.title || _t("Model not ready"),
                sticky: true,
            };
            if (env.services.user.isAdmin) {
                options.buttons = [
                    {
                        name: _t("Open AI Assistant Settings"),
                        onClick: () =>
                            env.services.action.doAction({
                                type: "ir.actions.act_window",
                                res_model: "res.config.settings",
                                name: _t("AI Assistant Settings"),
                                view_mode: "form",
                                views: [[false, "form"]],
                                target: "inline",
                                context: { module: "hdai" },
                            }),
                    },
                ];
            }
            env.services.notification.add(
                status.message || _t("No model is configured."),
                options
            );
            return;
        }
        env.services.dialog.add(HdaiChatDialog, {
            sessionId: false,
            pendingMessage: false,
        });
    })();
});
