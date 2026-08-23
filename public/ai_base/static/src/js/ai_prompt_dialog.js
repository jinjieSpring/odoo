/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/** Editor for a personal user prompt (title + content). */
export class AiPromptDialog extends Component {
    static template = "ai_base.PromptDialog";
    static components = { Dialog };
    static props = {
        close: Function,
        prompt: { type: Object, optional: true },
        onSave: { type: Function, optional: true },
    };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.state = useState({
            name: this.props.prompt?.name || "",
            content: this.props.prompt?.system_prompt
                || this.props.prompt?.content || "",
        });
    }

    async save() {
        const name = this.state.name.trim();
        const content = this.state.content.trim();
        if (!name || !content || this.isSaving) {
            return;
        }
        this.isSaving = true;
        try {
            let promptId = this.props.prompt?.id;
            if (promptId) {
                await this.orm.write("ai.prompt.template", [promptId], {
                    name,
                    system_prompt: content,
                });
            } else {
                [promptId] = await this.orm.create("ai.prompt.template", [
                    {
                        name,
                        code: `user.${Date.now()}`,
                        system_prompt: content,
                    },
                ]);
            }
            this.props.onSave?.(promptId);
            this.props.close();
        } catch (error) {
            console.error("ai_base: saving prompt failed", error);
            this.notification.add(
                _t("Save failed: %s", error.message || error),
                { type: "danger" }
            );
        } finally {
            this.isSaving = false;
        }
    }
}
