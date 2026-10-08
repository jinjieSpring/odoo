/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { Component, useState, useExternalListener, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { FormViewDialog } from "@web/views/view_dialogs/form_view_dialog";
import { createFileViewer } from "@web/core/file_viewer/file_viewer_hook";

let _showMenuCallback = null;
let _hideMenuCallback = null;

const rightClickMenuService = {
    start() {
        function show(options) {
            _showMenuCallback?.(options);
        }

        function hide() {
            _hideMenuCallback?.();
        }

        return { show, hide };
    },
};

registry.category("services").add("right_click_menu", rightClickMenuService);

export class RightClickMenu extends Component {
    static template = "spiffy_theme_backend.RightClickMenu";
    static props = {};

    setup() {
        this.state = useState({
            visible: false,
            x: 0,
            y: 0,
            openAbove: false,
            resModel: null,
            resId: null,
            menuData: null,
            loading: false,
            submenuOpen: false,
            submenuX: 0,
            submenuY: 0,
        });

        this.actionService = useService("action");
        this.notificationService = useService("notification");
        this.dialogService = useService("dialog");
        this.uiService = useService("ui");
        this.orm = useService("orm");
        this.splitViewPanel = useService("split_view_panel");
        this.fileViewer = createFileViewer();
        this._submenuHideTimer = null;

        _showMenuCallback = (opts) => this._show(opts);
        _hideMenuCallback = () => this._hide();

        onWillUnmount(() => {
            _showMenuCallback = null;
            _hideMenuCallback = null;
            clearTimeout(this._submenuHideTimer);
        });

        useExternalListener(document, "click", (ev) => {
            if (this.state.visible && !ev.target.closest(".spiffy-context-menu")) {
                this._hide();
            }
        });

        useExternalListener(
            document,
            "contextmenu",
            (ev) => {
                if (this.state.visible && !ev.target.closest(".spiffy-context-menu")) {
                    this._hide();
                }
            },
            true
        );

        useExternalListener(document, "keydown", (ev) => {
            if (ev.key === "Escape" && this.state.visible) {
                this._hide();
            }
        });

        useExternalListener(window, "scroll", () => this._hide(), true);
    }


    get menuStyle() {
        const { x, y, openAbove } = this.state;
        const H = window.innerHeight;
        const margin = 8;
        if (openAbove) {
            return `left:${x}px; bottom:${H - y}px; max-height:${y - margin}px;`;
        }
        return `left:${x}px; top:${y}px; max-height:${H - y - margin}px;`;
    }

    get submenuStyle() {
        return `left:${this.state.submenuX}px; top:${this.state.submenuY}px;`;
    }


    async _show({ x, y, resModel, resId, activeFieldValue, model }) {
        const W = window.innerWidth;
        const H = window.innerHeight;
        const openAbove = y + 300 > H;
        const adjX = x + 214 > W ? Math.max(4, W - 214) : x;

        // The list/kanban model of the view the record was right-clicked in.
        // Kept as a plain property (not reactive state) so the model class
        // instance is never wrapped in an OWL proxy.
        this._contextModel = model || null;

        Object.assign(this.state, {
            visible: true,
            loading: true,
            menuData: null,
            x: adjX,
            y,
            openAbove,
            resModel,
            resId,
            submenuOpen: false,
        });

        try {
            const data = await rpc("/spiffy/right_click_menu/data", {
                res_model: resModel,
                res_id: resId || 0,
                active_field_value: activeFieldValue !== undefined ? activeFieldValue : null,
            });

            if (
                this.state.visible &&
                this.state.resModel === resModel &&
                this.state.resId === resId
            ) {
                if (!data || !data.enabled) {
                    this.state.visible = false;
                } else {
                    const menuData = { ...data };
                    if (activeFieldValue !== undefined) {
                        menuData.is_active = activeFieldValue;
                    }
                    Object.assign(this.state, { menuData, loading: false });
                }
            }
        } catch (e) {
            console.error("[RightClickMenu] Failed to fetch menu data:", e);
            this.state.visible = false;
        }
    }

    _hide() {
        this.state.visible = false;
        this.state.submenuOpen = false;
        clearTimeout(this._submenuHideTimer);
    }

    async openRecord() {
        this._hide();
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: this.state.resModel,
            res_id: this.state.resId,
            views: [[false, "form"]],
            view_mode: "form",
        });
    }

    openInNewTab() {
        this._hide();
        const url = `/web#model=${this.state.resModel}&id=${this.state.resId}&view_type=form`;
        window.open(url, "_blank");
    }

    quickView() {
        const { resModel, resId } = this.state;
        this._hide();
        this.dialogService.add(FormViewDialog, {
            resModel,
            resId,
            title: _t("Quick View"),
            preventCreate: true,
            preventEdit: true,
            context: { form_view_initial_mode: "readonly" },
        });
    }

    async editRecord() {
        this._hide();
        await this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: this.state.resModel,
            res_id: this.state.resId,
            views: [[false, "form"]],
            view_mode: "form",
        });
    }

    async duplicateRecord() {
        const { resModel, resId } = this.state;
        this._hide();
        try {
            await this.orm.call(resModel, "copy", [resId], {});
            this.notificationService.add(_t("Record duplicated successfully"), {
                type: "success",
            });
            this._reloadCurrentView();
        } catch (e) {
            this.notificationService.add(_t("Failed to duplicate record"), {
                type: "danger",
            });
        }
    }

    async toggleArchive() {
        const { resModel, resId, menuData } = this.state;
        const isActive = menuData?.is_active;
        this._hide();
        try {
            await this.orm.write(resModel, [resId], { active: !isActive });
            this.notificationService.add(
                isActive ? _t("Record archived") : _t("Record unarchived"),
                { type: "success" }
            );
            this._reloadCurrentView();
        } catch (e) {
            this.notificationService.add(_t("Failed to archive/unarchive record"), {
                type: "danger",
            });
        }
    }

    async deleteRecord() {
        const { resModel, resId } = this.state;
        this._hide();
        this.dialogService.add(ConfirmationDialog, {
            title: _t("Delete Record"),
            body: _t(
                "Are you sure you want to delete this record? This action cannot be undone."
            ),
            confirm: async () => {
                try {
                    await this.orm.unlink(resModel, [resId]);
                    this.notificationService.add(_t("Record deleted"), {
                        type: "success",
                    });
                    this._reloadCurrentView();
                } catch (e) {
                    this.notificationService.add(_t("Failed to delete record"), {
                        type: "danger",
                    });
                }
            },
            cancel: () => {},
        });
    }

    async copyLink() {
        const { resModel, resId } = this.state;
        this._hide();
        const url = `${window.location.origin}/web#model=${resModel}&id=${resId}&view_type=form`;
        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(url);
            } else {
                const ta = document.createElement("textarea");
                ta.value = url;
                ta.style.cssText = "position:fixed;opacity:0;pointer-events:none";
                document.body.appendChild(ta);
                ta.focus();
                ta.select();
                document.execCommand("copy");
                document.body.removeChild(ta);
            }
            this.notificationService.add(_t("Link copied to clipboard"), {
                type: "success",
            });
        } catch (e) {
            this.notificationService.add(_t("Failed to copy link"), {
                type: "warning",
            });
        }
    }

    async openInSplitView() {
        const { resModel, resId } = this.state;
        this._hide();
        await this.splitViewPanel.openRecord({ resModel, resId });
    }

    onReportItemMouseEnter(ev) {
        clearTimeout(this._submenuHideTimer);
        const reports = this.state.menuData?.reports || [];
        if (reports.length <= 1) return;
        const rect = ev.currentTarget.getBoundingClientRect();
        const W = window.innerWidth;
        const submenuWidth = 240;
        const openLeft = rect.right + submenuWidth > W;
        this.state.submenuX = openLeft ? rect.left - submenuWidth : rect.right - 4;
        this.state.submenuY = rect.top - 5;
        this.state.submenuOpen = true;
    }

    onReportItemMouseLeave() {
        this._submenuHideTimer = setTimeout(() => {
            this.state.submenuOpen = false;
        }, 150);
    }

    onSubmenuMouseEnter() {
        clearTimeout(this._submenuHideTimer);
    }

    onSubmenuMouseLeave() {
        this.state.submenuOpen = false;
    }

    async previewReport(report) {
        const { resId, resModel } = this.state;
        this._hide();
        const context = encodeURIComponent(JSON.stringify({
            active_id: resId,
            active_ids: [resId],
            active_model: resModel,
            report_pdf_no_attachment: true,
        }));
        const pdfUrl = `/report/pdf/${report.report_name}/${resId}?context=${context}`;
        this.uiService.block();
        let blobUrl;
        try {
            const response = await fetch(pdfUrl, { credentials: "same-origin" });
            if (!response.ok) {
                this.notificationService.add(
                    _t("PDF preview is not available for this report."),
                    { type: "danger", title: _t("Preview Failed") }
                );
                return;
            }
            const blob = await response.blob();
            blobUrl = URL.createObjectURL(blob);
        } catch (e) {
            this.notificationService.add(
                _t("Failed to generate PDF preview."),
                { type: "danger", title: _t("Preview Failed") }
            );
            return;
        } finally {
            this.uiService.unblock();
        }
        const pdfViewerUrl = `/web/static/lib/pdfjs/web/viewer.html?file=${encodeURIComponent(blobUrl)}`;
        this.fileViewer.open({
            name: report.name || _t("Report"),
            isPdf: true,
            isViewable: true,
            downloadUrl: pdfUrl,
            defaultSource: pdfViewerUrl,
        });
    }

    _reloadCurrentView() {
        // Reload through the model captured when the menu was opened; no DOM
        // probing needed.
        if (this._contextModel) {
            this._contextModel.load();
            return;
        }
        const reloadBtn = document.querySelector(".o_control_panel .reload_view");
        if (reloadBtn) {
            reloadBtn.click();
        }
    }
}

registry.category("main_components").add("SpiffyRightClickMenu", {
    Component: RightClickMenu,
});
