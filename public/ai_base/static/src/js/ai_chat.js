/** @odoo-module **/

import {
    Component,
    onMounted,
    onWillStart,
    onWillUnmount,
    useEffect,
    useRef,
    useState,
} from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { formatDateTime } from "@web/core/l10n/dates";
import { user } from "@web/core/user";
import { router } from "@web/core/browser/router";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { AiFormattedText } from "./ai_formatted_text";
import { AiToolCard } from "./ai_tool_card";
import { AiPromptDialog } from "./ai_prompt_dialog";
import { AiUserSettingsDialog } from "./ai_user_settings_dialog";
import { viewContext } from "./ai_view_context";

const EMPTY_SESSION_STATS = {
    input_tokens: 0,
    output_tokens: 0,
    context_usage: 0,
};

const NO_CAPABILITIES = {
    reasoning: false,
    web_search: false,
    streaming: false,
};

export class AiChat extends Component {
    static template = "ai_base.ChatMain";
    static components = { AiFormattedText, AiToolCard };
    static props = {
        sessionId: { type: Number, optional: true },
        pendingMessage: { type: String, optional: true },
        onReady: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.actionService = useService("action");
        this.bus = useService("bus_service");
        this.tabsRef = useRef("tabs");
        this.messagesRef = useRef("messages");
        this.chatInputRef = useRef("chatInput");
        this.gridsRef = useRef("grids");
        this.sidebarRef = useRef("sidebar");
        this.COMMANDS = [
            { name: "help", help: "Show available commands" },
            { name: "settings", help: "Open user settings" },
            { name: "compact", help: "Compact the current conversation context" },
            { name: "export", help: "Export the current conversation" },
            { name: "share", help: "Share the current conversation" },
        ];
        this.props.onReady?.(this);
        this.state = useState({
            sessions: [],
            currentId: false,
            messages: [],
            sessionStats: { ...EMPTY_SESSION_STATS },
            draft: "",
            historyIndex: -1,
            historyMode: false,
            sending: false,
            canScrollLeft: false,
            canScrollRight: false,
            editingId: false,
            editName: "",
            editingMessageId: false,
            editMessageContent: "",
            modelReady: false,
            modelStatus: {},
            modelInfo: {},
            capabilities: {
                reasoning: true,
                web_search: true,
                streaming: true,
            },
            reasoningStrength: "none",
            webSearchEnabled: false,
            streaming: true,
            attachContext: true,
            promptId: 0,
            prompts: [],
            agents: [],
            defaultAgentId: false,
            contextAttached: false,
            contextDisplayName: "",
            contextAvailable: false,
            reasoningCollapsed: {},
            sidebarCollapsed: false,
            grids: { sessions: false, knowledge: false },
            gridHeights: { sessions: 0, knowledge: 0 },
            sidebarWidth: 260,
            knowledgeEnabled: false,
            knowledgeTopK: 5,
            knowledgeDocuments: [],
            knowledgeSelection: [],
            sessionSearch: "",
            currentName: "",
            modelBadge: { kind: "gray", text: "", title: "" },
            taskText: _t("Idle"),
            taskBusy: false,
            taskError: false,
            commandOpen: false,
        });
        onWillStart(() => this.init());
        onMounted(() => {
            this.scrollToBottom();
            // Re-detect the record context after the DOM/router are ready
            // so the context strip auto-loads on dialog open.
            this.attachAutoContext();
            this.busSubscription = this.bus.subscribe(
                "ai_base/nlview",
                (payload) => this.onNlviewBus(payload)
            );
        });
        onWillUnmount(() => {
            this.busSubscription?.unsubscribe?.();
        });
        useEffect(
            () => this.scrollToBottom(),
            () => [this.state.messages, this.state.sending]
        );
    }

    get canSend() {
        return (
            this.state.draft.trim().length > 0 &&
            !this.state.sending &&
            this.state.modelReady
        );
    }

    get filteredSessions() {
        const q = this.state.sessionSearch.trim().toLowerCase();
        if (!q) {
            return this.state.sessions;
        }
        return this.state.sessions.filter((s) =>
            (s.name || "").toLowerCase().includes(q)
        );
    }

    sessionMeta(session) {
        const parts = [];
        const count = Number(session.message_count) || 0;
        parts.push(
            _t("%s messages", count)
        );
        const time = this._relativeTime(session.write_date);
        if (time) {
            parts.push(time);
        }
        return parts.join(" \u00b7 ");
    }

    sessionTooltip(session) {
        const count = Number(session.message_count) || 0;
        const input = this._formatTokens(session.input_tokens);
        const output = this._formatTokens(session.output_tokens);
        const updated = this._absoluteTime(session.write_date);
        return _t(
            "%s messages \u00b7 Input %s \u00b7 Output %s \u00b7 Updated %s",
            count,
            input,
            output,
            updated
        );
    }

    _absoluteTime(writeDate) {
        if (!writeDate) {
            return "";
        }
        const luxon = window.luxon;
        if (!luxon) {
            return writeDate;
        }
        const dt = luxon.DateTime.fromISO(
            String(writeDate).replace(" ", "T") + "Z"
        );
        if (!dt.isValid) {
            return writeDate;
        }
        return formatDateTime(dt.setZone("default"));
    }

    _relativeTime(writeDate) {
        if (!writeDate) {
            return "";
        }
        const luxon = window.luxon;
        if (!luxon) {
            return "";
        }
        const dt = luxon.DateTime.fromISO(
            String(writeDate).replace(" ", "T") + "Z"
        );
        if (!dt.isValid) {
            return "";
        }
        const minutes = Math.round(dt.diffNow().as("minutes"));
        if (minutes > -1) {
            return _t("Just now");
        }
        if (minutes > -60) {
            return _t("%s min ago", -minutes);
        }
        const hours = Math.round(-minutes / 60);
        if (hours < 24) {
            return _t("%s h ago", hours);
        }
        const days = Math.round(hours / 24);
        if (days < 7) {
            return _t("%s d ago", days);
        }
        return formatDateTime(dt.setZone("default"));
    }

    _formatTokens(value) {
        const n = Number(value) || 0;
        if (n < 1000) {
            return String(n);
        }
        const scaled = n / 1000;
        const text = scaled >= 100 ? scaled.toFixed(0) : scaled.toFixed(1);
        return text.replace(/\.0$/, "") + "k";
    }

    get tokenSummary() {
        const input = this._formatTokens(this.state.sessionStats.input_tokens);
        const output = this._formatTokens(this.state.sessionStats.output_tokens);
        const pct = Math.round(this.state.sessionStats.context_usage || 0) + "%";
        return _t(
            "Input %s \u00b7 Output %s \u00b7 Context %s",
            input,
            output,
            pct
        );
    }

    get capabilityReasons() {
        return {
            reasoning: this.state.capabilities.reasoning
                ? ""
                : _t("Thinking strength is not available for the current model."),
            web_search: this.state.capabilities.web_search
                ? ""
                : _t("Web search is not available for the current model."),
            streaming: this.state.capabilities.streaming
                ? ""
                : _t("Streaming is not available for the current model."),
        };
    }

    get webSearchTitle() {
        return this.state.capabilities.web_search
            ? _t("Web Search")
            : this.capabilityReasons.web_search;
    }

    get streamingTitle() {
        return this.state.capabilities.streaming
            ? _t("Streaming")
            : this.capabilityReasons.streaming;
    }

    get filteredCommands() {
        const q = this.state.draft.trim().replace(/^\//, "").toLowerCase();
        if (!q) {
            return this.COMMANDS;
        }
        return this.COMMANDS.filter((c) => c.name.startsWith(q));
    }

    updateModelBadge() {
        const status = this.state.modelStatus || {};
        let kind = "gray";
        let text = "Model not configured";
        if (status.code === "ready") {
            kind = "green";
            text = "Model OK";
        } else if (status.code && status.code !== "no_model") {
            kind = "red";
            text = "Model config error";
        }
        this.state.modelBadge = {
            kind,
            text,
            title: status.message || text,
        };
    }

    setTask(text, busy = false, error = false) {
        this.state.taskText = text;
        this.state.taskBusy = busy;
        this.state.taskError = error;
    }

    toggleSidebar() {
        this.state.sidebarCollapsed = !this.state.sidebarCollapsed;
        this.saveLayout();
    }

    toggleGrid(name) {
        this.state.grids[name] = !this.state.grids[name];
        this.saveLayout();
    }

    async saveLayout() {
        try {
            await this.orm.call(
                "ai.chat.session",
                "action_set_options",
                [[this.state.currentId], {
                    sidebar_collapsed: this.state.sidebarCollapsed,
                    grid_sessions_collapsed: this.state.grids.sessions,
                    grid_knowledge_collapsed: this.state.grids.knowledge,
                    grid_sessions_height: this.state.gridHeights.sessions,
                    grid_knowledge_height: this.state.gridHeights.knowledge,
                    sidebar_width: this.state.sidebarWidth,
                }]
            );
        } catch (error) {
            console.error("ai_base: save layout failed", error);
            this.notification.add(
                _t("Failed to save the layout: %s", error.message || error),
                { type: "danger" }
            );
        }
    }

    startGridResize(ev, name) {
        ev.preventDefault();
        const grid = this._findGridElement(name);
        if (!grid) {
            return;
        }
        const startY = ev.clientY;
        const startHeight = grid.getBoundingClientRect().height;
        const maxHeight = Math.max(120, grid.parentElement.clientHeight - 80);
        const onMove = (e) => {
            const delta = e.clientY - startY;
            const height = Math.max(60, Math.min(maxHeight, startHeight + delta));
            grid.style.flex = "0 0 " + height + "px";
        };
        const onUp = () => {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            document.body.style.cursor = "";
            const height = Math.round(
                parseFloat(grid.style.flex.split(" ")[2]) || startHeight
            );
            this.state.gridHeights[name] = height;
            this.saveLayout();
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
        document.body.style.cursor = "row-resize";
    }

    startSidebarResize(ev) {
        ev.preventDefault();
        const sidebar = this._findSidebarElement();
        if (!sidebar) {
            return;
        }
        const startX = ev.clientX;
        const startWidth = sidebar.getBoundingClientRect().width;
        const onMove = (e) => {
            const width = Math.max(180, Math.min(800, startWidth + e.clientX - startX));
            sidebar.style.width = width + "px";
        };
        const onUp = () => {
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            document.body.style.cursor = "";
            const width = Math.round(
                parseFloat(sidebar.style.width) || startWidth
            );
            this.state.sidebarWidth = width;
            this.saveLayout();
        };
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
        document.body.style.cursor = "col-resize";
    }

    _findGridElement(name) {
        const sidebar = this.gridsRef?.el ?? document.querySelector(
            ".o_ai_chat_sidebar_grids"
        );
        return sidebar?.querySelector(
            '.o_ai_sidebar_grid[data-grid-name="' + name + '"]'
        );
    }

    _findSidebarElement() {
        return this.sidebarRef?.el ?? document.querySelector(
            ".o_ai_chat_sidebar"
        );
    }

    openModelConfig() {
        if (this.env.user?.isAdmin) {
            this.actionService.doAction({
                type: "ir.actions.act_window",
                res_model: "res.config.settings",
                view_mode: "form",
                views: [[false, "form"]],
                target: "current",
                context: { module: "ai_base" },
            });
        } else {
            this.notification.add(this.state.modelBadge.title, {
                type: "warning",
            });
        }
    }

    runCommand(name) {
        this.state.commandOpen = false;
        this.state.draft = "";
        if (name === "settings") {
            this.openUserSettings();
            return;
        }
        if (name === "help") {
            this.notification.add(this.commandHelpText(), {
                type: "info",
                title: _t("Available commands"),
                sticky: true,
            });
            return;
        }
        if (name === "export") {
            this.notification.add(
                _t("Choose the export format for the current conversation."),
                {
                    type: "info",
                    title: _t("Export conversation"),
                    buttons: [
                        {
                            name: "JSON",
                            onClick: () => this.exportSession("json"),
                        },
                        {
                            name: "Markdown",
                            onClick: () => this.exportSession("markdown"),
                        },
                    ],
                }
            );
            return;
        }
        this.notification.add(
            `Command /${name} is available in a future release.`,
            { type: "info" }
        );
    }

    commandHelpText() {
        return _t(
            "/help - Show available commands\n" +
                "/settings - Open user settings\n" +
                "/export - Export the conversation (JSON or Markdown)\n" +
                "/compact - Compact the conversation context (planned)\n" +
                "/share - Share the conversation (planned)"
        );
    }

    exportSession(format) {
        const safeName = (this.state.currentName || "session").replace(
            /[\\/:*?"<>|]/g,
            "_"
        );
        const messages = this.state.messages || [];
        let content;
        let mime;
        let filename;
        if (format === "json") {
            content = JSON.stringify(
                {
                    session: { id: this.state.currentId, name: safeName },
                    exported_at: new Date().toISOString(),
                    messages: messages.map((msg) => ({
                        role: msg.role,
                        content: msg.content || "",
                        reasoning_content: msg.reasoning_content || "",
                        create_date: msg.create_date || "",
                    })),
                },
                null,
                2
            );
            mime = "application/json";
            filename = safeName + ".json";
        } else {
            const lines = ["# " + safeName];
            for (const msg of messages) {
                const label =
                    msg.role === "user" ? "User" : "Assistant";
                const date = msg.create_date
                    ? " (" + msg.create_date + ")"
                    : "";
                lines.push("\n## " + label + date + "\n");
                if (msg.reasoning_content) {
                    lines.push("> " + msg.reasoning_content + "\n");
                }
                lines.push(msg.content || "");
            }
            content = lines.join("\n");
            mime = "text/markdown";
            filename = safeName + ".md";
        }
        const blob = new Blob([content], { type: mime });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    }

    async init() {
        const defaults = await this.orm.call(
            "ai.chat.session",
            "action_get_defaults",
            []
        );
        Object.assign(this.state, {
            modelReady: Boolean(defaults.model_ready),
            modelStatus: defaults.model_status || {},
            modelInfo: defaults.model_info || {},
            capabilities:
                (defaults.model_info && defaults.model_info.capabilities) ||
                NO_CAPABILITIES,
            reasoningStrength: defaults.reasoning_strength || "none",
            webSearchEnabled: Boolean(defaults.web_search_enabled),
            streaming: Boolean(defaults.streaming),
            attachContext: Boolean(defaults.attach_context),
            sidebarCollapsed: Boolean(defaults.sidebar_collapsed),
            grids: {
                sessions: Boolean(defaults.grid_sessions_collapsed),
                knowledge: Boolean(defaults.grid_knowledge_collapsed),
            },
            gridHeights: {
                sessions: Number(defaults.grid_sessions_height) || 0,
                knowledge: Number(defaults.grid_knowledge_height) || 0,
            },
            sidebarWidth: Number(defaults.sidebar_width) || 260,
            knowledgeDocuments: defaults.knowledge_documents || [],
            promptId: defaults.default_prompt_id || 0,
            prompts: defaults.prompts || [],
            agents: defaults.agents || [],
            defaultAgentId: defaults.default_agent_id || false,
        });
        this.updateModelBadge();
        await this.loadSessions();
        if (this.props.sessionId) {
            this.state.currentId = this.props.sessionId;
            if (this.props.pendingMessage) {
                this.state.draft = this.props.pendingMessage;
            }
            await this.selectSession(
                this.props.sessionId,
                Boolean(this.props.pendingMessage)
            );
        } else if (this.props.pendingMessage) {
            // Fallback used only when no session was pre-created by the
            // entry point (systray pre-creates and passes its id, so this
            // branch never duplicates it).
            const sessionId = await this.orm.call(
                "ai.chat.session",
                "action_create_from_input",
                [this.props.pendingMessage]
            );
            if (sessionId) {
                this.state.currentId = sessionId;
                this.state.draft = this.props.pendingMessage;
                await this.selectSession(sessionId, true);
            }
        } else if (this.state.sessions.length) {
            await this.selectSession(this.state.sessions[0].id);
        } else {
            await this.attachAutoContext();
        }
        // Always re-detect the record context on dialog open: an existing
        // session may carry a stale/wrong context (e.g. attached earlier
        // from another page), and the user expects the current form record
        // to be sensed. attachAutoContext keeps the previous context when
        // no record is detected and respects the user preference toggle.
        await this.attachAutoContext();
    }

    async loadSessions() {
        const sessions = await this.orm.searchRead(
            "ai.chat.session",
            [["user_id", "=", user.userId]],
            ["id", "name", "message_count", "write_date",
             "input_tokens", "output_tokens"],
            { order: "write_date desc, id desc", limit: 50 }
        );
        this.state.sessions = sessions;
        if (
            this.state.currentId &&
            !sessions.some((s) => s.id === this.state.currentId)
        ) {
            this.state.currentId = false;
            this.state.messages = [];
            this.state.sessionStats = { ...EMPTY_SESSION_STATS };
        }
    }

    async selectSession(sessionId, autoSend = false) {
        this.state.currentId = sessionId;
        const session = this.state.sessions.find(
            (s) => s.id === sessionId
        );
        this.state.currentName = session ? session.name : "";
        const data = await this.orm.call(
            "ai.chat.session",
            "action_get_session",
            [[sessionId]]
        );
        this.state.messages = data.messages || [];
        this.state.sessionStats = {
            ...EMPTY_SESSION_STATS,
            ...(data.session || {}),
        };
        this.state.capabilities =
            (data.session && data.session.capabilities) || {
                ...NO_CAPABILITIES,
            };
        this.updateModelBadge();
        this.state.reasoningStrength =
            data.session.reasoning_strength || "none";
        this.state.webSearchEnabled = Boolean(
            data.session.web_search_enabled
        );
        this.state.streaming = Boolean(data.session.streaming);
        this.state.knowledgeEnabled = Boolean(
            data.session.knowledge_enabled
        );
        this.state.knowledgeTopK =
            Number(data.session.knowledge_top_k) || 5;
        this.state.knowledgeSelection =
            data.session.knowledge_document_ids || [];
        this.state.promptId = data.session.prompt_id || 0;
        // attach_context is a user preference persisted in the user
        // settings; switching sessions must not overwrite it.
        this.state.contextAttached = Boolean(data.session.context_attached);
        this.state.contextDisplayName =
            data.session.context_display_name || "";
        this.state.historyIndex = -1;
        this.state.historyMode = false;
        if (autoSend && this.state.draft.trim()) {
            const content = this.state.draft;
            this.state.draft = "";
            // Fire the send without blocking the first render: the dialog
            // must appear immediately with the user message and an empty
            // reply box; streamed content fills it as it arrives.
            this.sendMessage(content);
        }
        this.scrollToBottom();
    }

    async newSession() {
        if (!this.state.modelReady) {
            this.notification.add(
                _t("Configure a model provider first (Settings > AI Assistant)."),
                { type: "warning" }
            );
            return;
        }
        // Reuse an empty "New Session" instead of creating a duplicate:
        // the previous new session is still empty, so just activate it.
        const emptyNew = this.state.sessions.find(
            (s) => s.name === "New Session" && !s.message_count
        );
        if (emptyNew) {
            await this.selectSession(emptyNew.id);
            return;
        }
        const id = await this.orm.call(
            "ai.chat.session",
            "create",
            [{}]
        );
        this.state.currentId = id;
        this.state.messages = [];
        this.state.sessionStats = { ...EMPTY_SESSION_STATS };
        this.state.capabilities =
            (this.state.modelInfo && this.state.modelInfo.capabilities) || {
                ...NO_CAPABILITIES,
            };
        this.state.contextAttached = false;
        this.state.contextDisplayName = "";
        this.state.currentName = "New Session";
        this.state.sessionSearch = "";
        await this.loadSessions();
        this.scrollToBottom();
    }

    async closeSession(sessionId, name) {
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete session"),
            body: _t("Delete the session \"%s\" and all its messages?", name),
            confirm: async () => {
                await this.orm.unlink("ai.chat.session", [sessionId]);
                if (this.state.currentId === sessionId) {
                    this.state.currentId = false;
                    this.state.messages = [];
                    this.state.sessionStats = { ...EMPTY_SESSION_STATS };
                }
                await this.loadSessions();
                if (!this.state.currentId && this.state.sessions.length) {
                    await this.selectSession(this.state.sessions[0].id);
                }
            },
        });
    }

    startEdit(sessionId, name) {
        this.state.editingId = sessionId;
        this.state.editName = name;
    }

    async saveEdit() {
        if (!this.state.editingId || !this.state.editName.trim()) {
            this.state.editingId = false;
            return;
        }
        await this.orm.write("ai.chat.session", [this.state.editingId], {
            name: this.state.editName.trim(),
        });
        this.state.editingId = false;
        await this.loadSessions();
    }

    cancelEdit() {
        this.state.editingId = false;
    }

    onEditKeyDown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.saveEdit();
        } else if (ev.key === "Escape") {
            this.cancelEdit();
        }
    }

    onEditBlur() {
        if (this.state.editingId) {
            this.saveEdit();
        }
    }

    updateTabScrollState() {
        const el = this.tabsRef.el;
        if (!el) {
            return;
        }
        this.state.canScrollLeft = el.scrollLeft > 0;
        this.state.canScrollRight =
            el.scrollLeft + el.clientWidth < el.scrollWidth - 1;
    }

    scrollTabsLeft() {
        this.tabsRef.el.scrollBy({ left: -200, behavior: "smooth" });
    }

    scrollTabsRight() {
        this.tabsRef.el.scrollBy({ left: 200, behavior: "smooth" });
    }

    scrollToBottom() {
        setTimeout(() => {
            const el = this.messagesRef.el;
            if (el) {
                el.scrollTop = el.scrollHeight;
            }
        }, 0);
    }

    onInputKeyDown(ev) {
        if (ev.key === "Escape") {
            this.state.commandOpen = false;
        } else if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            if (this.state.commandOpen) {
                const commands = this.filteredCommands;
                if (commands.length === 1) {
                    this.runCommand(commands[0].name);
                }
            } else if (this.canSend) {
                this.sendCurrent();
            }
        } else if (ev.key === "ArrowUp") {
            if (this.state.historyMode) {
                ev.preventDefault();
                this.navigateHistory(-1);
            } else if (!this.state.draft) {
                ev.preventDefault();
                this.enterHistory();
            }
        } else if (ev.key === "ArrowDown") {
            if (this.state.historyMode) {
                ev.preventDefault();
                this.navigateHistory(1);
            }
        } else if (ev.key === "Tab" && this.state.commandOpen) {
            ev.preventDefault();
            const commands = this.filteredCommands;
            if (commands.length === 1) {
                this.state.draft = "/" + commands[0].name + " ";
                this.state.commandOpen = false;
            }
        }
    }

    onChatInput(ev) {
        const value = ev.target.value;
        // Toggle the slash-command palette when the draft starts with "/".
        this.state.commandOpen =
            value.trim().startsWith("/") && !value.includes(" ");
        if (this.state.historyMode) {
            const current =
                this.getHistory()[this.state.historyIndex] || "";
            if (value !== current) {
                // Any edit (typing or deleting) leaves the history mode.
                this.state.historyMode = false;
                this.state.historyIndex = -1;
            }
        }
        if (!value) {
            this.state.historyMode = false;
            this.state.historyIndex = -1;
        }
        this.state.draft = value;
    }

    getHistory() {
        return this.state.messages
            .filter((msg) => msg.role === "user" && msg.content)
            .map((msg) => msg.content);
    }

    enterHistory() {
        const history = this.getHistory();
        if (!history.length) {
            return;
        }
        this.state.historyMode = true;
        this.state.historyIndex = history.length - 1;
        this.state.draft = history[this.state.historyIndex];
        this.moveCursorToEnd();
    }

    navigateHistory(direction) {
        const history = this.getHistory();
        if (!history.length || !this.state.historyMode) {
            return;
        }
        if (direction === -1) {
            if (this.state.historyIndex > 0) {
                this.state.historyIndex -= 1;
            } else {
                return;
            }
        } else {
            if (this.state.historyIndex < history.length - 1) {
                this.state.historyIndex += 1;
            } else {
                // Past the newest entry: back to a blank input.
                this.state.historyMode = false;
                this.state.historyIndex = -1;
                this.state.draft = "";
                this.moveCursorToEnd();
                return;
            }
        }
        this.state.draft = history[this.state.historyIndex];
        this.moveCursorToEnd();
    }

    moveCursorToEnd() {
        const el = this.chatInputRef.el;
        if (!el) {
            return;
        }
        el.focus();
        const length = el.value.length;
        el.setSelectionRange(length, length);
    }

    async sendCurrent() {
        const content = this.state.draft.trim();
        if (!content || this.state.sending) {
            return;
        }
        if (!this.state.currentId) {
            // No session selected (e.g. the dialog was opened directly
            // while the user has no conversations yet): create one on the
            // first send so typing + Enter just works instead of being
            // silently ignored by canSend.
            this.state.draft = content;
            await this.newSession();
            if (!this.state.currentId) {
                return;
            }
            // The new session has no context yet: attach the current
            // record/list context before sending so the very first message
            // already carries it (attachAutoContext bails out when there
            // is no session).
            await this.attachAutoContext();
        }
        this.state.draft = "";
        this.sendMessage(content);
    }

    optimisticUserMessage(content) {
        const localId = "local-" + Date.now();
        this.state.messages.push({
            localId,
            id: false,
            role: "user",
            content,
            pending: false,
        });
        return localId;
    }

    async sendMessage(content) {
        if (this.state.sending) {
            return;
        }
        this.optimisticUserMessage(content);
        this.scrollToBottom();
        if (this.state.streaming && this.state.capabilities.streaming) {
            await this.sendStreaming(content);
        } else {
            await this.sendSync(content);
        }
        this.scrollToBottom();
    }

    async sendSync(content) {
        this.state.sending = true;
        this.setTask(_t("Generating..."), true);
        try {
            const result = await this.orm.call(
                "ai.chat.session",
                "action_send_message",
                [[this.state.currentId], content, {}]
            );
            this.applyResult(result);
            await this.loadSessions();
            if (result.action) {
                this.actionService.doAction(result.action);
            }
        } catch (error) {
            console.error("ai_base: send failed", error);
            this.notification.add(
                _t("Failed to send the message: %s", error.message || error),
                { type: "danger" }
            );
            this.setTask(_t("Failed"), false, true);
        } finally {
            this.state.sending = false;
            this.setTask(_t("Idle"));
        }
    }

    async sendStreaming(content) {
        this.state.sending = true;
        this.setTask(_t("Generating..."), true);
        const pending = {
            id: false,
            localId: "stream-" + Date.now(),
            role: "assistant",
            content: "",
            reasoning_content: "",
            toolCards: [],
            pending: true,
        };
        this.state.messages.push(pending);
        this.scrollToBottom();
        const controller = new AbortController();
        this._abortController = controller;
        this._stopRequested = false;
        try {
            const resp = await fetch("/ai_base/chat/stream", {
                method: "POST",
                signal: controller.signal,
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    session_id: this.state.currentId,
                    content,
                    options: {
                        reasoning_strength: this.state.reasoningStrength,
                        web_search: this.state.webSearchEnabled,
                    },
                }),
            });
            if (!resp.ok) {
                throw new Error(_t("Stream request failed (%s)", resp.status));
            }
            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            for (;;) {
                const { done, value } = await reader.read();
                if (done) {
                    break;
                }
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop();
                for (const line of lines) {
                    if (!line.trim()) {
                        continue;
                    }
                    let data;
                    try {
                        data = JSON.parse(line);
                    } catch (parseError) {
                        continue;
                    }
                    if (data.error) {
                        this.notification.add(data.error, { type: "danger" });
                        pending.pending = false;
                        continue;
                    }
                    if (data.delta || data.reasoning_delta) {
                        this.state.messages = this.state.messages.map((msg) =>
                            msg.localId === pending.localId
                                ? {
                                      ...msg,
                                      content:
                                          msg.content + (data.delta || ""),
                                      reasoning_content:
                                          msg.reasoning_content +
                                          (data.reasoning_delta || ""),
                                  }
                                : msg
                        );
                    }
                    if (data.tool_call || data.tool_card) {
                        const card = data.tool_call
                            ? data.tool_call.card
                            : data.tool_card;
                        if (card) {
                            pending.toolCards = [
                                ...pending.toolCards,
                                card,
                            ];
                            this.state.messages = this.state.messages.map(
                                (msg) =>
                                    msg.localId === pending.localId
                                        ? { ...msg, toolCards: pending.toolCards }
                                        : msg
                            );
                        }
                    }
                    if (data.action && data.action.type) {
                        // NL open-view closed loop: the server-side tool
                        // loop executed open_view and returned the action;
                        // apply it to the main web client.
                        this.actionService.doAction(data.action);
                    }
                    if (data.limit) {
                        this.notification.add(data.limit, {
                            type: "warning",
                        });
                    }
                }
                this.scrollToBottom();
            }
            pending.pending = false;
            if (
                !pending.content &&
                !pending.reasoning_content &&
                !pending.toolCards.length
            ) {
                this.state.messages = this.state.messages.filter(
                    (m) => m.localId !== pending.localId
                );
            }
            const data = await this.orm.call(
                "ai.chat.session",
                "action_get_session",
                [[this.state.currentId]]
            );
            this.state.messages = data.messages || [];
            this.state.sessionStats = {
                ...EMPTY_SESSION_STATS,
                ...(data.session || {}),
            };
            await this.loadSessions();
        } catch (error) {
            if (error.name === "AbortError") {
                // User stopped the generation: drop the partial bubble and
                // reload the persisted messages (the stream controller only
                // saves the completed reply).
                const data = await this.orm.call(
                    "ai.chat.session",
                    "action_get_session",
                    [[this.state.currentId]]
                );
                this.state.messages = data.messages || [];
                this.state.sessionStats = {
                    ...EMPTY_SESSION_STATS,
                    ...(data.session || {}),
                };
                await this.loadSessions();
                return;
            }
            console.error("ai_base: streaming failed", error);
            pending.pending = false;
            this.notification.add(
                _t("Streaming failed: %s", error.message || error),
                { type: "danger" }
            );
            this.setTask(_t("Failed"), false, true);
        } finally {
            this.state.sending = false;
            this._abortController = null;
            this._stopRequested = false;
            this.setTask(_t("Idle"));
        }
    }

    stopGeneration() {
        if (!this._abortController) {
            return;
        }
        this._stopRequested = true;
        this._abortController.abort();
        this.setTask(_t("Stopped"), false, false);
    }

    applyResult(result) {
        if (!result) {
            return;
        }
        if (result.error) {
            this.notification.add(result.error.message || result.error.title, {
                type: "warning",
            });
        }
        if (result.messages) {
            this.state.messages = result.messages;
        }
        if (result.session) {
            this.state.sessionStats = {
                ...EMPTY_SESSION_STATS,
                ...result.session,
            };
        }
    }

    async saveOptions() {
        const options = {
            reasoning_strength: this.state.reasoningStrength,
            web_search_enabled: this.state.webSearchEnabled,
            streaming: this.state.streaming,
            attach_context: this.state.attachContext,
            prompt_id: this.state.promptId || false,
            knowledge_enabled: this.state.knowledgeEnabled,
            knowledge_document_ids: this.state.knowledgeSelection.join(","),
        };
        try {
            await this.orm.call(
                "ai.chat.session",
                "action_set_options",
                [[this.state.currentId], options]
            );
        } catch (error) {
            console.error("ai_base: save options failed", error);
            this.notification.add(
                _t("Failed to save the options: %s", error.message || error),
                { type: "danger" }
            );
        }
    }

    toggleKnowledgeEnabled(ev) {
        this.state.knowledgeEnabled = ev.target.checked;
        this.saveOptions();
    }

    toggleKnowledgeDocument(ev) {
        const id = parseInt(ev.target.value, 10);
        if (!Number.isInteger(id)) {
            return;
        }
        const selection = this.state.knowledgeSelection.slice();
        const index = selection.indexOf(id);
        if (ev.target.checked && index === -1) {
            selection.push(id);
        } else if (!ev.target.checked && index !== -1) {
            selection.splice(index, 1);
        }
        this.state.knowledgeSelection = selection;
        this.saveOptions();
    }

    toggleWebSearch() {
        if (!this.state.capabilities.web_search) {
            return;
        }
        this.state.webSearchEnabled = !this.state.webSearchEnabled;
        this.saveOptions();
    }

    toggleStreaming() {
        if (!this.state.capabilities.streaming) {
            return;
        }
        this.state.streaming = !this.state.streaming;
        this.saveOptions();
    }

    isReasoningCollapsed(messageId) {
        return Boolean(this.state.reasoningCollapsed[messageId]);
    }

    toggleReasoningCollapse(messageId) {
        this.state.reasoningCollapsed[messageId] =
            !this.state.reasoningCollapsed[messageId];
    }

    async copyMessage(msg) {
        try {
            await navigator.clipboard.writeText(msg.content || "");
            this.notification.add(_t("Copied to clipboard."), {
                type: "success",
            });
        } catch (error) {
            console.error("ai_base: copy failed", error);
        }
    }

    startEditMessage(msg) {
        this.state.editingMessageId = msg.id;
        this.state.editMessageContent = msg.content;
    }

    cancelEditMessage() {
        this.state.editingMessageId = false;
        this.state.editMessageContent = "";
    }

    onEditMessageKeyDown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.saveEditMessage();
        } else if (ev.key === "Escape") {
            this.cancelEditMessage();
        }
    }

    async saveEditMessage() {
        const messageId = this.state.editingMessageId;
        const content = this.state.editMessageContent.trim();
        if (!messageId || !content || this.state.sending) {
            return;
        }
        this.cancelEditMessage();
        await this.runModelAction("action_edit_and_resend", [messageId, content]);
    }

    resendMessage(msg) {
        if (this.state.sending) {
            return;
        }
        this.runModelAction("action_edit_and_resend", [msg.id, msg.content]);
    }

    regenerateAnswer(msg) {
        if (this.state.sending) {
            return;
        }
        this.runModelAction("action_regenerate", [msg.id]);
    }

    async runModelAction(method, args) {
        this.state.sending = true;
        try {
            const result = await this.orm.call(
                "ai.chat.session",
                method,
                [[this.state.currentId], ...args]
            );
            this.applyResult(result);
            await this.loadSessions();
            if (result && result.action) {
                this.actionService.doAction(result.action);
            }
        } catch (error) {
            console.error(`ai_base: ${method} failed`, error);
            this.notification.add(
                _t("Action failed: %s", error.message || error),
                { type: "danger" }
            );
        } finally {
            this.state.sending = false;
        }
    }

    async sendAsMessage(msg) {
        const action = await this.orm.call(
            "ai.chat.session",
            "action_send_as_message",
            [[this.state.currentId], msg.id]
        );
        if (action && action.type) {
            this.actionService.doAction(action);
        }
    }

    async logAsNote(msg) {
        const action = await this.orm.call(
            "ai.chat.session",
            "action_log_as_note",
            [[this.state.currentId], msg.id]
        );
        if (action && action.type) {
            this.actionService.doAction(action);
        }
    }

    async sendFeedback(msg, rating) {
        if (!msg || !msg.id) {
            return;
        }
        try {
            await this.orm.call(
                "ai.governance.feedback",
                "action_submit",
                [msg.id, rating, ""]
            );
            this.notification.add(
                _t("Feedback recorded. Thank you!"),
                { type: "success" }
            );
        } catch (error) {
            // Governance module is optional: silence the call when the
            // service is not installed.
            if (
                error &&
                !String(error.message || error).includes(
                    "Object doesn't exist"
                )
            ) {
                console.error("ai_base: feedback failed", error);
            }
        }
    }

    updateToolCard(msg, card) {
        this.state.messages = this.state.messages.map((item) =>
            item === msg ? { ...item, tool: card } : item
        );
    }

    messageCards(msg) {
        if (msg.tool_cards && msg.tool_cards.length) {
            return msg.tool_cards;
        }
        return msg.toolCards || [];
    }

    onNlviewBus(payload) {
        // Session-tagged bus notification: never apply a view requested by
        // another chat session (multi-session anti-crosstalk).
        if (payload.session_id && payload.session_id !== this.state.currentId) {
            return;
        }
        if (payload.action && payload.action.type) {
            this.actionService.doAction(payload.action);
        }
    }

    async openInDiscuss() {
        try {
            const action = await this.orm.call(
                "ai.chat.session",
                "action_open_in_discuss",
                [[this.state.currentId]]
            );
            if (action && action.type) {
                this.actionService.doAction(action);
            }
        } catch (error) {
            console.error("ai_base: open in discuss failed", error);
            this.notification.add(
                _t("Failed to open in Discuss: %s", error.message || error),
                { type: "danger" }
            );
        }
    }

    _routerRecordContext() {
        // Prefer the router state: it carries the exact record of the view
        // currently displayed (model + resId) during SPA navigation.
        const candidates = [];
        const current = router.current || {};
        if (current.model && current.resId && current.resId !== "new") {
            candidates.push({
                source: "router",
                modelName: current.model,
                resId: current.resId,
            });
        }
        // Fallback: the current controller (same pattern as Odoo's
        // switch_company_menu), useful after page reloads where the URL
        // cannot carry the model for custom-path actions like Contacts.
        const controller = this.actionService?.currentController;
        if (controller?.props?.resModel) {
            const controllerResId =
                controller.props?.resId ?? controller.model?.root?.resId;
            // The authoritative record id of a form view is on the form
            // model root (props.resId can be stale after navigation/reload).
            if (controllerResId && controllerResId !== "new") {
                candidates.push({
                    source: "controller",
                    modelName: controller.props.resModel,
                    resId: controllerResId,
                });
            }
        }
        for (const candidate of candidates) {
            const parsed = parseInt(candidate.resId, 10);
            if (
                candidate.modelName &&
                !candidate.modelName.startsWith("ai.") &&
                candidate.modelName !== "discuss.channel" &&
                Number.isInteger(parsed) &&
                parsed > 0
            ) {
                return {
                    modelName: candidate.modelName,
                    resId: parsed,
                };
            }
        }
        // List / kanban views: the action service's currentController is
        // only a metadata object (no live view model), so the record set is
        // captured by the mounted view controllers and published through
        // viewContext (total record count + id list, no selection).
        // Guard against stale data: only trust the store when the current
        // action is a multi-record view of the same model.
        const currentViewType = controller?.props?.type;
        const onForm =
            currentViewType === "form" ||
            Boolean(current.resId && current.resId !== "new");
        const isListLike =
            currentViewType === "list" || currentViewType === "kanban";
        const isModelFallback =
            !currentViewType &&
            !onForm &&
            Boolean(controller?.props?.resModel || current.model);
        if (
            (isListLike || isModelFallback) &&
            viewContext.resModel &&
            viewContext.resModel === (controller?.props?.resModel || current.model) &&
            !viewContext.resModel.startsWith("ai.") &&
            viewContext.resModel !== "discuss.channel"
        ) {
            return {
                modelName: viewContext.resModel,
                resIds: viewContext.resIds,
                count: viewContext.count,
                viewType: viewContext.viewType || "list",
            };
        }
        // Other view types (pivot, graph, calendar, ...) do not support
        // record context sensing: tell the user instead of showing a
        // generic "no record" message.
        if (
            currentViewType &&
            !onForm &&
            !isListLike &&
            !isModelFallback
        ) {
            return {
                viewType: "unsupported",
                viewName: currentViewType,
            };
        }
        return null;
    }

    async attachAutoContext() {
        const context = this._routerRecordContext();
        if (!context) {
            // No record is being viewed: drop any stale context so the
            // dialog does not keep answering with an old record.
            this.state.contextAvailable = false;
            this.state.contextDisplayName = "";
            if (this.state.contextAttached) {
                await this.clearContext();
            }
            return;
        }
        try {
            if (context.viewType === "unsupported") {
                this.state.contextAvailable = false;
                this.state.contextDisplayName = _t(
                    "Current %s view does not support context awareness",
                    context.viewName
                );
                if (this.state.contextAttached) {
                    await this.clearContext();
                }
                return;
            }
            // Detect and display the record even before a session exists:
            // the strip must not say "No record detected" while the user is
            // actually viewing a record (the session is auto-created on the
            // first send and the context is attached then).
            if (context.viewType === "list" || context.viewType === "kanban") {
                // List/kanban record set: read-only info for the strip, and
                // attach only when the user preference is enabled. Empty
                // views have no context: the toggle is disabled.
                const info = await this.orm.call(
                    "ai.chat.session",
                    "action_get_list_context",
                    [context.modelName, context.resIds || [], context.count || 0]
                );
                if (info && info.model) {
                    const label = info.display_name || info.model;
                    this.state.contextDisplayName = _t(
                        "Total %s %s records",
                        info.count,
                        label
                    );
                }
                this.state.contextAvailable = info.count > 0;
                if (info.count <= 0) {
                    if (this.state.contextAttached) {
                        await this.clearContext();
                    }
                    return;
                }
                if (!this.state.currentId) {
                    this.state.contextAttached = false;
                    return;
                }
                if (!this.state.attachContext) {
                    this.state.contextAttached = false;
                    return;
                }
                const result = await this.orm.call(
                    "ai.chat.session",
                    "action_attach_list_context",
                    [[this.state.currentId], context.modelName,
                     context.resIds || [], context.count || 0]
                );
                this.state.contextAttached = Boolean(
                    result && result.attached
                );
                return;
            }
            // Read-only detection: always show the current record info.
            const info = await this.orm.call(
                "ai.chat.session",
                "action_get_record_context",
                [context.modelName, context.resId]
            );
            if (info && info.display_name) {
                this.state.contextDisplayName = info.display_name;
                this.state.contextAvailable = true;
            } else {
                // Missing/deleted record: no attachable context.
                this.state.contextDisplayName = "";
                this.state.contextAvailable = false;
                if (this.state.contextAttached) {
                    await this.clearContext();
                }
                return;
            }
            if (!this.state.currentId) {
                // Defer attaching until the session exists; sendCurrent
                // calls attachAutoContext again after auto-creating it.
                this.state.contextAttached = false;
                return;
            }
            if (!this.state.attachContext) {
                this.state.contextAttached = false;
                return;
            }
            const result = await this.orm.call(
                "ai.chat.session",
                "action_attach_context",
                [[this.state.currentId], context.modelName, context.resId]
            );
            if (result && result.attached) {
                this.state.contextAttached = true;
            } else {
                this.state.contextAttached = false;
            }
        } catch (error) {
            console.error("ai_base: attach context failed", error);
        }
    }

    async onToggleAttachContext(ev) {
        const checked = ev.target.checked;
        this.state.attachContext = checked;
        if (!checked) {
            await this.clearContext();
        } else {
            await this.attachAutoContext();
        }
        await this.saveOptions();
    }

    async clearContext() {
        this.state.contextAttached = false;
        this.state.contextDisplayName = "";
        try {
            await this.orm.call(
                "ai.chat.session",
                "action_clear_context",
                [[this.state.currentId]]
            );
        } catch (error) {
            console.error("ai_base: clear context failed", error);
        }
    }

    async openPromptDialog() {
        this.dialog.add(AiPromptDialog, {
            onSaved: async () => {
                const defaults = await this.orm.call(
                    "ai.chat.session",
                    "action_get_defaults",
                    []
                );
                this.state.prompts = defaults.prompts || [];
            },
        });
    }

    async openUserSettings() {
        this.dialog.add(AiUserSettingsDialog, {
            onSaved: async () => {
                const defaults = await this.orm.call(
                    "ai.chat.session",
                    "action_get_defaults",
                    []
                );
                Object.assign(this.state, {
                    reasoningStrength: defaults.reasoning_strength || "none",
                    webSearchEnabled: Boolean(defaults.web_search_enabled),
                    streaming: Boolean(defaults.streaming),
                    attachContext: Boolean(defaults.attach_context),
                    promptId: defaults.default_prompt_id || 0,
                    prompts: defaults.prompts || [],
                });
                await this.saveOptions();
            },
        });
    }
}
