/** @odoo-module **/

import { Component, onWillStart, useExternalListener, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { HdaiChat } from "./hdai_chat";

export class HdaiChatDialog extends Component {
    static template = "hdai_base.ChatDialog";
    static components = { Dialog, HdaiChat };
    static props = {
        sessionId: { type: Number, optional: true },
        pendingMessage: { type: String, optional: true },
        close: Function,
        title: { type: String, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.actionService = useService("action");
        this.chatRef = null;
        this.state = useState({
            badge: { kind: "gray", text: "", title: "" },
        });
        // Clicking anywhere in the current browser window outside this
        // dialog closes it. The Odoo modal backdrop is itself part of the
        // .modal container, so only clicks inside the dialog body
        // (.modal-dialog) are kept open; clicking outside the browser does
        // not fire a document event at all.
        useExternalListener(document, "mousedown", (ev) => {
            if (!ev.target.closest?.(".modal-dialog")) {
                this.props.close();
            }
        });
        onWillStart(async () => {
            try {
                const defaults = await this.orm.call(
                    "hdai.session",
                    "action_get_defaults",
                    []
                );
                const status = defaults.model_status || {};
                let kind = "gray";
                let text = _t("Model not configured");
                if (status.code === "ready") {
                    kind = "green";
                    text = _t("Model OK");
                } else if (status.code && status.code !== "no_model") {
                    kind = "red";
                    text = _t("Model config error");
                }
                this.state.badge = {
                    kind,
                    text,
                    title: status.message || text,
                };
            } catch (error) {
                console.error("hdai: badge load failed", error);
            }
        });
    }

    newSession() {
        this.chatRef?.newSession();
    }

    deleteSession() {
        const chat = this.chatRef;
        if (chat && chat.state.currentId) {
            chat.closeSession(chat.state.currentId, chat.state.currentName);
        }
    }

    openModelConfig() {
        if (this.env.user?.isAdmin) {
            this.actionService.doAction({
                type: "ir.actions.act_window",
                res_model: "res.config.settings",
                view_mode: "form",
                views: [[false, "form"]],
                target: "current",
                context: { module: "hdai_base" },
            });
        } else {
            this.notification.add(this.state.badge.title, {
                type: "warning",
            });
        }
    }
}
