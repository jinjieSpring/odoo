/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { ActionMenus } from "@web/search/action_menus/action_menus";
import { patch } from "@web/core/utils/patch";
import { createFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { _t } from "@web/core/l10n/translation";

patch(ActionMenus.prototype, {
    /**
     * @param {Object} item  - print item from state.printItems
     */
    async onPreviewReport(item) {
        const action = item.action;
        if (!action || !action.report_name) {
            return;
        }

        const activeIds = this.props.getActiveIds ? this.props.getActiveIds() : [];
        if (!activeIds || activeIds.length === 0) {
            return;
        }

        const previewContext = Object.assign(
            {},
            action.context,
            {
                active_id: activeIds[0],
                active_ids: activeIds,
                active_model: this.props.resModel,
                report_pdf_no_attachment: true,
            }
        );

        let pdfUrl;
        if (action.data && JSON.stringify(action.data) !== "{}") {
            const options = encodeURIComponent(JSON.stringify(action.data));
            const context = encodeURIComponent(JSON.stringify(previewContext));
            pdfUrl = `/report/pdf/${action.report_name}?options=${options}&context=${context}`;
        } else {
            const context = encodeURIComponent(JSON.stringify(previewContext));
            pdfUrl = `/report/pdf/${action.report_name}/${activeIds.join(",")}`
                   + `?context=${context}`;
        }

        this.env.services.ui.block();

        let blobUrl;
        try {
            const response = await fetch(pdfUrl, { credentials: "same-origin" });
            if (!response.ok) {
                this.env.services.notification.add(
                    _t("PDF preview is not available for this report. The report may not produce a valid PDF."),
                    { type: "danger", title: _t("Preview Failed") }
                );
                return;
            }
            const blob = await response.blob();
            blobUrl = URL.createObjectURL(blob);
        } catch (err) {
            this.env.services.notification.add(
                _t("An unexpected error occurred while generating the PDF preview."),
                { type: "danger", title: _t("Preview Failed") }
            );
            return;
        } finally {
            this.env.services.ui.unblock();
        }

        const pdfViewerUrl =
            `/web/static/lib/pdfjs/web/viewer.html?file=${encodeURIComponent(blobUrl)}`;

        const fileViewer = createFileViewer();
        fileViewer.open({
            name: action.name || "Report",
            isPdf: true,
            isViewable: true,
            downloadUrl: pdfUrl,
            defaultSource: pdfViewerUrl,
        });
    },
});
