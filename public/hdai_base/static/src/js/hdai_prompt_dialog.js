/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { Dialog } from "@web/core/dialog/dialog";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

/** Editor for a personal user prompt (title + content). */
export class HdaiPromptDialog extends Component {
    static template = "hdai_base.PromptDialog";
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
            content: this.props.prompt?.content || "",
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
                await this.orm.write("hdai.prompt", [promptId], {
                    name,
                    content,
                });
            } else {
                [promptId] = await this.orm.create("hdai.prompt", [
                    { name, content, scope: "user" },
                ]);
            }
            this.props.onSave?.(promptId);
            this.props.close();
        } catch (error) {
            console.error("hdai: saving prompt failed", error);
            this.notification.add(
                _t("Save failed: %s", error.message || error),
                { type: "danger" }
            );
        } finally {
            this.isSaving = false;
        }
    }
}
