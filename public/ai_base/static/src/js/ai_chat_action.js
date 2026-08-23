/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { AiChat } from "./ai_chat";

/**
 * Full-page chat action used as the "AI Assistant" app landing and menu
 * entry. The systray quick input keeps opening the overlay dialog; this
 * action is what the application menu opens, so clicking the app shows the
 * app menu (sidebar) with a normal page instead of a dialog popup.
 */
export class AiChatAction extends Component {
    static template = "ai_base.ChatAction";
    static components = { AiChat };
    static props = ["*"];
    static extractProps = (action) => {
        const sessionId = action.params?.session_id;
        return sessionId ? { sessionId } : {};
    };
}

registry.category("actions").add("ai_chat", AiChatAction);
