/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { onMounted, onWillUnmount } from "@odoo/owl";
import { session } from "@web/session";

import { ListRenderer } from "@web/views/list/list_renderer";
import { KanbanRecord } from "@web/views/kanban/kanban_record";
import { Many2OneField } from "@web/views/fields/many2one/many2one_field";

function isNativeContextTarget(ev) {
    return !!ev.target.closest('input, textarea, [contenteditable="true"], select');
}

patch(ListRenderer.prototype, {
    setup() {
        super.setup();
        this._rcmService = useService("right_click_menu");
    },

    onRowContextMenu(ev) {
        if (!session.enable_right_click_menu) return;
        if (isNativeContextTarget(ev)) return;

        ev.preventDefault();
        ev.stopPropagation();

        const row = ev.target.closest("tr.o_data_row");
        if (!row) return;

        this._triggerListMenu(row, ev.clientX, ev.clientY);
    },

    _triggerListMenu(row, x, y) {
        const resId = parseInt(row.getAttribute("resid") || row.getAttribute("data-resid") || "0");
        if (!resId) return;

        const record = this.props.list.records.find((r) => r.resId === resId);
        if (!record) return;

        const activeFieldValue =
            record.data.active !== undefined ? record.data.active : undefined;

        this._rcmService.show({
            x,
            y,
            resModel: record.resModel,
            resId: record.resId,
            activeFieldValue,
        });
    },
});

patch(KanbanRecord.prototype, {
    setup() {
        super.setup();
        this._rcmService = useService("right_click_menu");
    },

    onKanbanContextMenu(ev) {
        if (!session.enable_right_click_menu) return;
        if (isNativeContextTarget(ev)) return;

        ev.preventDefault();
        ev.stopPropagation();
        const record = this.props.record;
        if (!record?.resId) return;
        const payload = {
            resId: record.resId,
            resModel: record.resModel,
            name:
                record.data?.display_name ||
                record.data?.name ||
                `${record.resModel},${record.resId}`,
            record,
            data: record.data || {},
            x: ev.clientX,
            y: ev.clientY,
        };

        this.el?.dispatchEvent(
            new CustomEvent("spiffy-kanban-record-contextmenu", {
                bubbles: true,
                detail: payload,
            })
        );
        this.env?.bus?.trigger("spiffy_kanban_record_contextmenu", payload);

        this._rcmService?.show({
            x: ev.clientX,
            y: ev.clientY,
            resModel: record.resModel,
            resId: record.resId,
            activeFieldValue:
                record.data.active !== undefined ? record.data.active : undefined,
        });
    },
});


patch(Many2OneField.prototype, {
    setup() {
        super.setup();

        if (!session.enable_right_click_menu) return;

        this._rcmService = useService("right_click_menu");
        this._onM2OContextMenuBound = (ev) => this._onM2OContextMenu(ev);

        onMounted(() => {
            this.el?.addEventListener("contextmenu", this._onM2OContextMenuBound);
        });

        onWillUnmount(() => {
            this.el?.removeEventListener("contextmenu", this._onM2OContextMenuBound);
        });
    },

    _onM2OContextMenu(ev) {
        // Allow native context menu on inputs (for search/typing)
        if (ev.target.closest("input, textarea")) return;

        const value = this.props.value;
        if (!value) return;

        // Handle both object {id, displayName} and legacy [id, name] formats
        const resId = Array.isArray(value) ? value[0] : value.id;
        if (!resId) return;

        const resModel = this.props.relation;
        if (!resModel) return;

        ev.preventDefault();
        ev.stopPropagation();

        this._rcmService.show({
            x: ev.clientX,
            y: ev.clientY,
            resModel,
            resId,
            // active field unknown for m2o without extra data
            activeFieldValue: undefined,
        });
    },
});
