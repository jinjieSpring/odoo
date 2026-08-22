/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { rpc } from "@web/core/network/rpc";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { CharField, charField } from "@web/views/fields/char/char_field";

export class AiEnhanceField extends CharField {
    static template = "ai_base.AiEnhanceField";

    setup() {
        super.setup();
        this.notification = useService("notification");
    }

    async enhance(action) {
        const current = this.props.record.data[this.props.name] || "";
        try {
            const result = await rpc("/ai_base/field/enhance", {
                action,
                text: current,
                lang: this.props.record.context?.lang,
            });
            if (result.text) {
                await this.props.record.update({ [this.props.name]: result.text });
            }
        } catch (error) {
            this.notification.add(error.message || String(error), {
                type: "danger",
                title: _t("AI enhance failed"),
            });
        }
    }
}

export const aiEnhanceField = {
    ...charField,
    component: AiEnhanceField,
    displayName: _t("AI Enhance"),
    supportedTypes: ["char", "text", "html"],
};

registry.category("fields").add("ai_enhance", aiEnhanceField);
