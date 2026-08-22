/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { user } from "@web/core/user";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

/**
 * Visual card for an LLM tool call. Ready tools show an Execute button;
 * blocked tools show the reason, guidance and (for non-admins) a button to
 * notify the administrators.
 */
export class HdaiToolCard extends Component {
    static template = "hdai_base.ToolCard";
    static props = {
        tool: Object,
        onUpdate: { type: Function, optional: true },
        onTask: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.isAdmin = user.isAdmin;
        this.state = useState({ installing: false });
    }

    get executeLabel() {
        return _t("Execute");
    }

    get notifyLabel() {
        return _t("Notify Administrators");
    }

    get addWhitelistLabel() {
        return _t("Add to Whitelist");
    }

    get openWhitelistLabel() {
        return _t("Open Whitelist Settings");
    }

    get installModuleLabel() {
        return _t("Install Module");
    }

    get openAppsLabel() {
        return _t("Open Apps Install");
    }

    get installingLabel() {
        const module = this.props.tool.error?.action?.module || "";
        return _t(
            "Installing module %s... this can take a few minutes. Please wait.",
            module
        );
    }

    _confirm(title, body, onConfirm) {
        this.dialog.add(ConfirmationDialog, {
            title,
            body,
            confirm: onConfirm,
        });
    }

    async _refreshCard() {
        if (!this.props.onUpdate) {
            return;
        }
        const card = await this.orm.call(
            "hdai.session",
            "action_build_tool_card",
            [this.props.tool.payload]
        );
        this.props.onUpdate(card);
    }

    addToWhitelist() {
        const action = this.props.tool.error?.action || {};
        this._confirm(
            _t("Add to Whitelist"),
            _t('Add the model "%s" to the Open View Models whitelist?', action.model),
            async () => {
                const result = await this.orm.call(
                    "hdai.session",
                    "action_whitelist_add",
                    [action.model]
                );
                if (result && result.type) {
                    this.actionService.doAction(result);
                }
                await this._refreshCard();
            }
        );
    }

    openWhitelist() {
        const action = this.props.tool.error?.action || {};
        this.actionService.doAction(
            "hdai_base.hdai_action_nlview_model",
            {
                additionalContext: action.model_id
                    ? { default_model_id: action.model_id }
                    : {},
            }
        );
    }

    installModule() {
        const action = this.props.tool.error?.action || {};
        this._confirm(
            _t("Install Module"),
            _t('Install the module "%s"? The server will restart.', action.module),
            async () => {
                this.state.installing = true;
                try {
                    const result = await this.orm.call(
                        "hdai.session",
                        "action_install_module",
                        [action.module]
                    );
                    if (result && result.type) {
                        this.actionService.doAction(result);
                        if (result.tag !== "reload") {
                            this.state.installing = false;
                        }
                    }
                } catch (error) {
                    console.error("hdai: module install failed", error);
                    this.state.installing = false;
                    this.notification.add(
                        _t("Module install failed: %s", error.message || error),
                        { type: "danger" }
                    );
                }
            }
        );
    }

    openApps() {
        const action = this.props.tool.error?.action || {};
        // Use the system Apps action (base.open_module_tree) so the install
        // interface behaves exactly like the native one; only the search box
        // is prefilled with the module name.
        this.actionService.doAction("base.open_module_tree", {
            additionalContext: { search_default_name: action.module },
        });
    }

    async execute() {
        const tool = this.props.tool;
        const preview = tool.suggestion_preview;
        const confirmBody = preview
            ? _t(
                  "Apply suggestion for %s #%s?\n\n%s\n\nReason: %s",
                  preview.model || "?",
                  preview.record_id || "?",
                  Object.entries(preview.fields_to_update || {})
                      .map(([k, v]) => `${k}=${v}`)
                      .join(", ") || "-",
                  preview.reason || "-"
              )
            : _t(
                  "Run tool \"%s\"? Write operations open a standard Odoo form for you to confirm; the AI never writes directly.",
                  tool.name || tool.label || "tool"
              );
        this._confirm(_t("Confirm AI suggestion"), confirmBody, async () => {
            try {
                this.props.onTask?.(_t("Executing tool..."), true, false);
                const method =
                    tool.suggestive || preview
                        ? "action_confirm_suggestion"
                        : "action_execute_tool";
                const action = await this.orm.call("hdai.session", method, [
                    tool.payload,
                ]);
                if (action && action.type) {
                    this.actionService.doAction(action);
                }
                this.props.onTask?.(_t("Idle"), false, false);
            } catch (error) {
                console.error("hdai: tool execution failed", error);
                this.notification.add(
                    _t("Tool execution failed: %s", error.message || error),
                    { type: "danger" }
                );
                this.props.onTask?.(_t("Failed"), false, true);
            }
        });
    }

    async notifyAdmins() {
        try {
            const action = await this.orm.call(
                "hdai.session",
                "action_notify_admins",
                [this.props.tool.payload, this.props.tool.error]
            );
            if (action && action.type) {
                this.actionService.doAction(action);
            }
        } catch (error) {
            this.notification.add(
                _t("Failed to notify administrators: %s", error.message || error),
                { type: "danger" }
            );
        }
    }
}
