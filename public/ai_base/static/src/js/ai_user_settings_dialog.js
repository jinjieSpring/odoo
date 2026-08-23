/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { AiPromptDialog } from "./ai_prompt_dialog";

/** User-level AI assistant settings dialog. */
export class AiUserSettingsDialog extends Component {
    static template = "ai_base.UserSettingsDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        onSaved: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            capabilities: { reasoning: false, streaming: false },
            languageMode: "auto",
            language: "",
            languages: [],
            reasoningStrength: "none",
            streaming: true,
            attachContext: true,
            sidebarCollapsed: false,
            gridSessionsCollapsed: false,
            gridKnowledgeCollapsed: false,
            hasKnowledge: false,
            defaultPromptId: false,
            prompts: [],
        });
        this.load();
    }

    async load() {
        try {
            const settings = await this.orm.call(
                "ai.chat.session",
                "action_get_user_settings",
                []
            );
            Object.assign(this.state, {
                loading: false,
                capabilities: settings.capabilities || {
                    reasoning: false,
                    streaming: false,
                },
                languageMode: settings.language_mode || "auto",
                language: settings.language || "",
                languages: settings.languages || [],
                reasoningStrength: settings.reasoning_strength || "none",
                streaming: Boolean(settings.streaming),
                attachContext: Boolean(settings.attach_context),
                sidebarCollapsed: Boolean(settings.sidebar_collapsed),
                gridSessionsCollapsed: Boolean(
                    settings.grid_sessions_collapsed),
                gridKnowledgeCollapsed: Boolean(
                    settings.grid_knowledge_collapsed),
                hasKnowledge: Boolean(settings.has_knowledge),
                defaultPromptId: settings.default_prompt_id || false,
                prompts: settings.prompts || [],
            });
        } catch (error) {
            console.error("ai_base: loading user settings failed", error);
            this.state.loading = false;
            this.notification.add(
                _t("Failed to load user settings: %s", error.message || error),
                { type: "danger" }
            );
        }
    }

    setLanguageMode(mode) {
        this.state.languageMode = mode;
    }

    changeReasoningStrength(ev) {
        this.state.reasoningStrength = ev.target.value;
    }

    toggleStreaming(ev) {
        this.state.streaming = ev.target.checked;
    }

    toggleAttachContext(ev) {
        this.state.attachContext = ev.target.checked;
    }

    toggleSidebarCollapsed(ev) {
        this.state.sidebarCollapsed = ev.target.checked;
    }

    toggleGridSessionsCollapsed(ev) {
        this.state.gridSessionsCollapsed = ev.target.checked;
    }

    toggleGridKnowledgeCollapsed(ev) {
        this.state.gridKnowledgeCollapsed = ev.target.checked;
    }

    async reloadPrompts() {
        this.state.prompts = await this.orm.searchRead(
            "ai.prompt.template",
            [["is_active", "=", true]],
            ["id", "name"],
            { order: "name" }
        );
        if (
            this.state.defaultPromptId &&
            !this.state.prompts.some((p) => p.id === this.state.defaultPromptId)
        ) {
            this.state.defaultPromptId = false;
        }
    }

    editPrompt(promptId) {
        const prompt = this.state.prompts.find((p) => p.id === promptId);
        this.dialog.add(AiPromptDialog, {
            prompt,
            onSave: (savedId) => {
                if (!promptId) {
                    this.state.defaultPromptId = savedId;
                }
                this.reloadPrompts();
            },
        });
    }

    deletePrompt(promptId) {
        const prompt = this.state.prompts.find((p) => p.id === promptId);
        if (!prompt) {
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t("Delete Prompt"),
            body: _t('Are you sure you want to delete the prompt "%s"?', prompt.name),
            confirmLabel: _t("Delete"),
            confirmClass: "btn-danger",
            confirm: async () => {
                try {
                    await this.orm.unlink("ai.prompt.template", [promptId]);
                    await this.reloadPrompts();
                } catch (error) {
                    this.notification.add(_t("Delete failed: %s", error.message), {
                        type: "danger",
                    });
                }
            },
        });
    }

    setDefaultPrompt(ev) {
        this.state.defaultPromptId = parseInt(ev.target.value, 10) || false;
    }

    async save() {
        if (this.isSaving || this.state.loading) {
            return;
        }
        if (this.state.languageMode === "specific" && !this.state.language) {
            this.notification.add(_t("Please select a language."), {
                type: "warning",
            });
            return;
        }
        this.isSaving = true;
        try {
            await this.orm.call("ai.chat.session", "action_save_user_settings", [
                {
                    language_mode: this.state.languageMode,
                    language: this.state.language,
                    reasoning_strength: this.state.reasoningStrength,
                    streaming: this.state.streaming,
                    attach_context: this.state.attachContext,
                    sidebar_collapsed: this.state.sidebarCollapsed,
                    grid_sessions_collapsed: this.state.gridSessionsCollapsed,
                    grid_knowledge_collapsed:
                        this.state.gridKnowledgeCollapsed,
                    default_prompt_id: this.state.defaultPromptId,
                },
            ]);
            this.props.onSaved?.();
            this.props.close();
        } catch (error) {
            console.error("ai_base: saving user settings failed", error);
            this.notification.add(
                _t("Save failed: %s", error.message || error),
                { type: "danger" }
            );
        } finally {
            this.isSaving = false;
        }
    }
}
