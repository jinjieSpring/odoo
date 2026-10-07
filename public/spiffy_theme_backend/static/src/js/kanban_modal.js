/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { KanbanRecord } from "@web/views/kanban/kanban_record";
import { KanbanController } from "@web/views/kanban/kanban_controller";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { renderToFragment } from "@web/core/utils/render";

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

        // Shift+Click opens modal
        if (ev.shiftKey) {
            ev.preventDefault();
            ev.stopPropagation();
            
            // Try action service first
            if (this.env?.services?.action) {
                const action = {
                    type: "ir.actions.act_window",
                    name: this.props.record.data.display_name || "Record Details",
                    res_model: this.props.record.resModel,
                    res_id: this.props.record.resId,
                    views: [[false, "form"]],
                    view_mode: "form",
                    target: "new",
                    context: {},
                };
                
                this.env.services.action.doAction(action, {
                    onClose: () => {
                        document.querySelector('.o_kanban_view')
                        ?.__owl__?.component?.model?.load();
                        if ($('.o_action_manager > .o_view_controller.o_kanban_view > .o_control_panel .reload_view').length) {
                            $('.o_action_manager > .o_view_controller.o_kanban_view > .o_control_panel .reload_view').click()
                        }
                    },
                });
            } else {
                // Fallback: use XML template
                this.createModalFromTemplate();
            }
            return;
        }

        // Normal click
        return super.onGlobalClick(ev);
    },

    createModalFromTemplate() {
        const { resId, resModel, data } = this.props.record;
        
        // Render modal from XML template
        const modalFragment = renderToFragment("kanban_modal_form.modal_template", {
            resModel: resModel,
            resId: resId,
            displayName: data.display_name || 'Record Details',
            formUrl: `/web#id=${resId}&model=${resModel}&view_type=form`
        });
        
        document.body.appendChild(modalFragment);
        
        const modal = document.querySelector('.kanban-modal-container');
        
        const close = () => {
            modal.remove();
            document.querySelector('.o_kanban_view')?.__owl__?.component?.model?.load();
        };
        
        modal.querySelector('.btn-close').onclick = close;
        modal.querySelector('.btn-secondary').onclick = close;
        modal.querySelector('.modal-backdrop').onclick = close;
        document.addEventListener('keydown', (e) => e.key === 'Escape' && close(), { once: true });
    },
});