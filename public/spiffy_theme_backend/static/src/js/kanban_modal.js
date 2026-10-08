/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { KanbanRecord } from "@web/views/kanban/kanban_record";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

// Add modal functionality to KanbanController
patch(KanbanController.prototype, {
    setup() {
        super.setup();
        this.action = useService("action");
    },

    async openRecordModal(record) {
        const action = {
            type: "ir.actions.act_window",
            name: record.data.display_name || "Record Details",
            res_model: this.props.resModel,
            res_id: record.resId,
            views: [[false, "form"]],
            view_mode: "form",
            target: "new",
            context: this.props.context,
        };

        return this.action.doAction(action, {
            onClose: () => this.model.load(),
        });
    },
});

// Add Shift+Click handling to KanbanRecord
patch(KanbanRecord.prototype, {
    onGlobalClick(ev) {
        // Skip interactive elements
        if (ev.target.closest('button, a[href], input, select, textarea, .dropdown-toggle')) {
            return super.onGlobalClick(ev);
        }

        // Shift+Click opens the record in a dialog and reloads the model on
        // close. The record's own model reference avoids reaching into DOM
        // internals (__owl__) to find the kanban model.
        if (ev.shiftKey) {
            ev.preventDefault();
            ev.stopPropagation();
            const model = this.props.record.model;
            this.env.services.action.doAction({
                type: "ir.actions.act_window",
                name: this.props.record.data.display_name || "Record Details",
                res_model: this.props.record.resModel,
                res_id: this.props.record.resId,
                views: [[false, "form"]],
                view_mode: "form",
                target: "new",
                context: {},
            }, {
                onClose: () => model.load(),
            });
            return;
        }

        // Normal click
        return super.onGlobalClick(ev);
    },
});
