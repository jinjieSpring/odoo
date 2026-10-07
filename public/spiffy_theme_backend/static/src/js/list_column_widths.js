/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { ListRenderer } from "@web/views/list/list_renderer";
import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { onMounted, onPatched, useExternalListener } from "@odoo/owl";

patch(ListRenderer.prototype, {
    setup() {
        super.setup();

        useExternalListener(window, "pointerup", () => {
            if (this.columnWidths?.resizing) {
                this._bizSaveColumnWidths();
            }
        });

        onMounted(() => {
            this._bizRestoreColumnWidths();
            setTimeout(() => {
                this._bizRestoreColumnWidths();
            }, 210);
        });

        onPatched(() => {
            if (!this.columnWidths?.resizing) {
                this._bizRestoreColumnWidths();
            }
        });
    },

    _bizColWidthKey() {
        const uid = session.uid;
        const resModel = this.props.list.resModel;

        if (this.isX2Many) {
            const colSig = this.columns
                .filter((c) => c.type === "field")
                .map((c) => c.name)
                .sort()
                .join(",");
            return `spiffy_col_widths_${uid}_${resModel}_x2m_${colSig}`;
        }

        const viewId =
            this.env.config?.views?.find((v) => v[1] === "list")?.[0] || 0;
        return `spiffy_col_widths_${uid}_${resModel}_${viewId}`;
    },

    _bizSaveColumnWidths() {
        const table = this.tableRef?.el;
        if (!table) return;

        const headers = table.querySelectorAll("thead th[data-name]");
        if (!headers.length) return;

        const widths = {};
        headers.forEach((th) => {
            const name = th.dataset.name;
            if (name && th.style.width) {
                widths[name] = th.style.width;
            }
        });

        if (!Object.keys(widths).length) return;

        try {
            localStorage.setItem(this._bizColWidthKey(), JSON.stringify(widths));
        } catch (_e) {
            // Quota exceeded or private browsing – silently ignore.
        }
    },

    _bizRestoreColumnWidths() {
        let stored;
        try {
            stored = localStorage.getItem(this._bizColWidthKey());
        } catch (_e) {
            return;
        }
        if (!stored) return;

        let widths;
        try {
            widths = JSON.parse(stored);
        } catch (_e) {
            return;
        }

        const table = this.tableRef?.el;
        if (!table) return;

        const headers = table.querySelectorAll("thead th[data-name]");
        if (!headers.length) return;

        headers.forEach((th) => {
            const saved = widths[th.dataset.name];
            if (saved) {
                th.style.width = saved;
            }
        });
    },
});
