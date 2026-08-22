/** @odoo-module **/

import { Component, onWillStart, useRef, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

async function readSse(response, onEvent) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    while (true) {
        const { value, done } = await reader.read();
        if (done) {
            break;
        }
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n\n");
        buffer = parts.pop();
        for (const part of parts) {
            let event = "message";
            let data = "";
            for (const line of part.split("\n")) {
                if (line.startsWith("event:")) {
                    event = line.slice(6).trim();
                } else if (line.startsWith("data:")) {
                    data += line.slice(5).trim();
                }
            }
            if (data) {
                try {
                    onEvent(event, JSON.parse(data));
                } catch {
                    onEvent(event, { raw: data });
                }
            }
        }
    }
}

export class AiChat extends Component {
    static template = "ai_base.Chat";
    _t = _t;
    static props = {
        sessionId: { type: [Number, Boolean], optional: true },
        pendingMessage: { type: String, optional: true },
        resModel: { type: String, optional: true },
        resId: { type: [Number, Boolean], optional: true },
    };

    rpc(...args) {
        return rpc(...args);
    }

    setup() {
        this.notification = useService("notification");
        this.messagesRef = useRef("messages");
        this.state = useState({
            sessionId: this.props.sessionId || false,
            sessions: [],
            messages: [],
            content: "",
            streamingContent: "",
            toolHint: "",
            sending: false,
            error: "",
        });
        onWillStart(async () => {
            await this.refreshSessions();
            if (!this.state.sessionId) {
                const created = await this.rpc("/ai_base/session/create", {
                    res_model: this.props.resModel,
                    res_id: this.props.resId,
                });
                this.state.sessionId = created.id;
            }
            await this.loadSession(this.state.sessionId);
            if (this.props.pendingMessage) {
                this.state.content = this.props.pendingMessage;
                await this.onSend();
            }
        });
    }

    get canSend() {
        return Boolean(this.state.content.trim()) && !this.state.sending;
    }

    async refreshSessions() {
        this.state.sessions = await this.rpc("/ai_base/session/list", {});
    }

    async loadSession(sessionId) {
        const payload = await this.rpc("/ai_base/session/get", { session_id: sessionId });
        this.state.sessionId = sessionId;
        this.state.messages = payload.messages || [];
        this.state.error = "";
        this.state.streamingContent = "";
        this.state.toolHint = "";
    }

    async onNewSession() {
        const created = await this.rpc("/ai_base/session/create", {
            res_model: this.props.resModel,
            res_id: this.props.resId,
        });
        await this.refreshSessions();
        await this.loadSession(created.id);
    }

    async onSelectSession(sessionId) {
        await this.loadSession(sessionId);
    }

    onKeyDown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.onSend();
        }
    }

    async onSend() {
        const content = this.state.content.trim();
        if (!content || this.state.sending) {
            return;
        }
        this.state.sending = true;
        this.state.error = "";
        this.state.streamingContent = "";
        this.state.toolHint = "";
        this.state.content = "";
        this.state.messages.push({
            id: `tmp-${Date.now()}`,
            role: "user",
            content,
        });
        try {
            const response = await this._stream(content);
            if (!response.ok) {
                throw new Error(_t("Stream failed (%s)", response.status));
            }
            let reply = "";
            const toolCards = [];
            await readSse(response, (event, data) => {
                if (event === "delta") {
                    reply += data.delta || "";
                    this.state.streamingContent = reply;
                } else if (event === "tool_call") {
                    toolCards.push(data.card || { name: data.name, status: "done" });
                    this.state.toolHint = _t("Tool: %s", data.name || "");
                } else if (event === "error") {
                    this.state.error = data.error || _t("The model could not be reached.");
                }
            });
            if (reply) {
                this.state.messages.push({
                    id: `asst-${Date.now()}`,
                    role: "assistant",
                    content: reply,
                    tool_cards: toolCards,
                });
            }
            this.state.streamingContent = "";
            this.state.toolHint = "";
            await this.refreshSessions();
        } catch (error) {
            this.state.error = error.message || String(error);
        } finally {
            this.state.sending = false;
        }
    }

    _stream(content) {
        return fetch("/ai_base/chat/stream", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                session_id: this.state.sessionId,
                content,
            }),
        });
    }
}

export class AiChatDialog extends Component {
    static template = "ai_base.ChatDialog";
    static components = { Dialog, AiChat };
    static props = {
        sessionId: { type: [Number, Boolean], optional: true },
        pendingMessage: { type: String, optional: true },
        resModel: { type: String, optional: true },
        resId: { type: [Number, Boolean], optional: true },
        close: Function,
    };

    get title() {
        return _t("AI Assistant");
    }
}

export { readSse };
