/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { spiffyDocumentViewer } from "@spiffy_theme_backend/js/widgets/spiffyDocumentViewer";
import { ListRenderer } from "@web/views/list/list_renderer";
import { useService } from "@web/core/utils/hooks";
import { useFileViewer } from "@web/core/file_viewer/file_viewer_hook";
import { registry } from "@web/core/registry";
import { divertColorItem, divertColorItemRefresh } from "./apps_menu";
import { session } from '@web/session';
import { FileViewer } from "@web/core/file_viewer/file_viewer";
import { AttachmentList } from "@mail/core/common/attachment_list";
import { DomainSelectorDialog } from "@web/core/domain_selector_dialog/domain_selector_dialog";
import { SelectCreateDialog } from "@web/views/view_dialogs/select_create_dialog";

const serviceRegistry = registry.category("services");
const userMenuRegistry = registry.category("user_menuitems");

import { rpc } from "@web/core/network/rpc";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";
import { AttachmentUploadService } from "@mail/core/common/attachment_upload_service";
import { useState, useChildSubEnv, onPatched, onWillUnmount, useEffect } from "@odoo/owl";
import { spiffyThemeState } from "@spiffy_theme_backend/js/menu";
import { usePopover } from "@web/core/popover/popover_hook";
import { CalendarDialog } from "./calendar_dialog";
import { ColumnFilterPopover } from "./widgets/column_filter_popover";
const { DateTime } = luxon;

// TODO add list view document here , old way will not work
/**
 * @property {import("models").Attachment[]} attachments
 * @extends {ListRenderer<Props, Env>}
 */
patch(ListRenderer.prototype, {

    setup() {
        super.setup();
        this.dialog = useService("dialog");
        // this.rpc = rpc;
        this.fileViewer = useFileViewer();
        this.action = useService("action");
        this.notificationService = useService("notification");
        this.attachmentState = useState({ byResId: {} });
        this._bizAttachmentTimer = null;
        this._bizLastRecIdsKey = null;
        this._bizAlive = true;

        useEffect(
            () => {
                this._scheduleAttachmentLoad();
            },
            () => [spiffyThemeState.showAttachment]
        );

        onWillUnmount(() => {
            this._bizAlive = false;
            clearTimeout(this._bizAttachmentTimer);
        });

        onPatched(() => {
            this._scheduleAttachmentLoad();
        });
        // The expand/collapse-all button lives in the Pager template and is
        // driven by the Pager patch in pager.js.
        this.columnFilterState = useState({ items: [], showSearchMore: false });
        this.columnFilterPopover = usePopover(ColumnFilterPopover, {
            position: "bottom-start",
            onClose: () => {
                this._columnFilterTarget = null;
            },
        });
    },

    _attachmentsEnabled() {
        return spiffyThemeState.showAttachment && this.props.archInfo?.editable != "bottom";
    },

    _visibleRecords(list = this.props.list) {
        if (!list) {
            return [];
        }
        if (!list.isGrouped) {
            return list.records || [];
        }
        const records = [];
        for (const group of list.groups || []) {
            if (!group.isFolded) {
                records.push(...this._visibleRecords(group.list));
            }
        }
        return records;
    },

    _attachmentRecordKey() {
        return this._visibleRecords()
            .map((record) => record.resId)
            .filter((resId) => Number.isInteger(resId))
            .slice()
            .sort((a, b) => a - b)
            .join(",");
    },

    _scheduleAttachmentLoad() {
        if (!this._attachmentsEnabled() || this._bizAttachmentLoading) {
            return;
        }
        if (this._attachmentRecordKey() === this._bizLastRecIdsKey) {
            return;
        }
        clearTimeout(this._bizAttachmentTimer);
        this._bizAttachmentTimer = setTimeout(() => {
            this._loadAttachments();
        }, 50);
    },

    async _loadAttachments() {
        if (!this._bizAlive || !this._attachmentsEnabled()) {
            return;
        }
        const recIds = this._visibleRecords()
            .map((record) => record.resId)
            .filter((resId) => Number.isInteger(resId));
        const recIdsKey = recIds.slice().sort((a, b) => a - b).join(",");
        if (recIdsKey === this._bizLastRecIdsKey || this._bizAttachmentLoading) {
            return;
        }
        this._bizAttachmentLoading = true;
        try {
            const data = recIds.length
                ? await rpc("/get/attachment/data", { model: this.props.list.resModel, rec_ids: recIds })
                : [{}];
            if (!this._bizAlive || recIdsKey !== this._attachmentRecordKey()) {
                return;
            }
            const raw = (data && data[0]) || {};
            const byResId = {};
            for (const [key, value] of Object.entries(raw)) {
                if (Array.isArray(value)) {
                    byResId[String(key)] = value;
                }
            }
            this._bizLastRecIdsKey = recIdsKey;
            this.biz_attachment_data = [byResId];
            this.attachmentState.byResId = byResId;
        } finally {
            this._bizAttachmentLoading = false;
            if (this._bizAlive && recIdsKey !== this._attachmentRecordKey()) {
                this._scheduleAttachmentLoad();
            }
        }
    },

    rowAttachments(record) {
        if (!this._attachmentsEnabled() || !Number.isInteger(record?.resId)) {
            return [];
        }
        const list = this.attachmentState.byResId[String(record.resId)] || [];
        const items = [];
        list.forEach((attachment, index, arr) => {
            if (index < 5) {
                items.push({ ...attachment, counter: false, key: attachment.attachment_id });
            } else if (index === 5) {
                items.push({
                    ...attachment,
                    counter: true,
                    label: "+" + (arr.length - 5),
                    key: "more-" + attachment.attachment_id,
                });
            }
        });
        return items;
    },

    onAttachmentBoxClick(attachment, resId) {
        const mimetype = attachment.attachment_mimetype || "";
        if (!mimetype.match("(image|application/pdf|text|video)")) {
            this.notificationService.add(_t("Preview for this file type can not be shown"), {
                title: _t("File Format Not Supported"),
                type: "danger",
                sticky: false,
            });
            return;
        }
        const all = this.attachmentState.byResId[String(resId)] || [];
        const attachments = [];
        for (const item of all) {
            if ((item.attachment_mimetype || "").match("(image|application/pdf|text|video)")) {
                attachments.push({
                    id: item.attachment_id,
                    filename: item.attachment_name,
                    name: item.attachment_name,
                    url: "/web/content/" + item.attachment_id + "?download=true",
                    type: item.attachment_mimetype,
                    mimetype: item.attachment_mimetype,
                    is_main: false,
                });
            }
        }
        const mainComponents = registry.category("main_components");
        if (mainComponents.contains("spiffy_document")) {
            mainComponents.remove("spiffy_document");
        }
        mainComponents.add("spiffy_document", {
            Component: spiffyDocumentViewer,
            props: { attachments, activeAttachmentID: attachment.attachment_id },
        });
    },

    async onColumnFilter(ev) {
        const input = ev.currentTarget;
        const columnName = input.dataset.column;
        const fieldType = input.dataset.fieldType;
        const model = this.props.list.model.config.resModel;
        const isRelational = ['many2one', 'one2many', 'many2many'].includes(fieldType);

        if (ev.type === "keydown") {
            // Enter applies the typed value as a domain; other keys only
            // live-search relational fields.
            if (ev.key === "Enter") {
                this.columnFilterPopover.close();
                this._applyColumnFilterDomain(input, columnName, fieldType);
            } else if (isRelational) {
                await this._openRelationalFilter(input, model, columnName);
            }
            return;
        }

        if (isRelational) {
            await this._openRelationalFilter(input, model, columnName);
        } else if (fieldType === 'selection') {
            await this._openSelectionFilter(input, model, columnName);
        } else if (['datetime', 'date'].includes(fieldType)) {
            this._openDateFilter(ev, input, columnName, fieldType);
        }
    },

    _applyColumnFilterDomain(input, columnName, fieldType) {
        const filterValue = input.value.trim();
        let domain;

        if (!filterValue) {
            input.value = '';
            this.env.searchModel.splitAndAddDomain(JSON.stringify([]));
            return;
        }

        if (fieldType === 'char' || fieldType === 'text') {
            domain = [[columnName, 'ilike', filterValue]];
        } else if (fieldType === 'integer' || fieldType === 'float') {
            const number = parseFloat(filterValue);
            if (isNaN(number)) {
                alert("Invalid number input");
                return;
            }
            domain = [[columnName, '>=', number]];
        } else if (fieldType === 'monetary') {
            const number = parseFloat(filterValue);
            if (isNaN(number)) {
                alert("Invalid monetary input");
                return;
            }
            domain = [[columnName, '>=', number]];
        } else if (fieldType === 'boolean') {
            const boolValue = filterValue.toLowerCase();
            if (boolValue !== 'true' && boolValue !== 'false') {
                alert("Enter true or false");
                return;
            }
            domain = [[columnName, '=', boolValue === 'true']];
        } else if (['many2one', 'one2many', 'many2many'].includes(fieldType)) {
            domain = [[columnName, 'ilike', filterValue]];
        } else if (fieldType === 'datetime' || fieldType === 'date') {
            const dateObj = new Date(filterValue);
            if (isNaN(dateObj.getTime())) {
                alert("Invalid date format. Please enter a valid date.");
                return;
            }
            const pad = (num) => num.toString().padStart(2, '0');
            const isoDate = `${dateObj.getFullYear()}-${pad(dateObj.getMonth() + 1)}-${pad(dateObj.getDate())}`;
            domain = [[columnName, '=', isoDate]];
        } else {
            domain = [[columnName, '=', filterValue]];
        }

        this.env.searchModel.splitAndAddDomain(JSON.stringify(domain));
        input.value = '';
    },

    async _openRelationalFilter(input, model, columnName) {
        const data = await rpc('/filter/relational/field/list', {
            resModel: model,
            resField: columnName,
            searchTerm: input.value || '',
        });
        if (data.error) {
            console.error('Filter list error:', data.error);
            return;
        }
        const maxVisible = 6;
        this.columnFilterState.items = data.records.slice(0, maxVisible).map((rec) => ({
            id: rec.id,
            label: rec.name || `Record ${rec.id}`,
            value: rec.id,
        }));
        this.columnFilterState.showSearchMore = data.records.length > maxVisible;
        if (this._columnFilterTarget !== input || !this.columnFilterPopover.isOpen) {
            this._columnFilterTarget = input;
            this.columnFilterPopover.open(input, {
                state: this.columnFilterState,
                onSelect: (item) => {
                    input.value = '';
                    this.env.searchModel.splitAndAddDomain(JSON.stringify([[columnName, "=", item.value]]));
                },
                onSearchMore: () => this._openRelationalSearchMore(data, columnName, input.dataset.fieldname),
            });
        }
    },

    _openRelationalSearchMore(data, columnName, columnString) {
        this.dialog.add(SelectCreateDialog, {
            resModel: data.related_model,
            title: `Select ${columnString}`,
            multiSelect: true,
            noCreate: true,
            onSelected: async (selectedRecords) => {
                if (selectedRecords && selectedRecords.length > 0) {
                    const RecordList = await rpc('/filter/relational/field/data', {
                        resModel: data.related_model,
                        resField: selectedRecords,
                    });
                    const recordIds = RecordList.map(r => r.id);
                    this.env.searchModel.splitAndAddDomain([[columnName, "in", recordIds]]);
                } else {
                    alert("Please select at least one record.");
                }
            },
        });
    },

    async _openSelectionFilter(input, model, columnName) {
        const data = await rpc('/selection/filter/list', {
            resModel: model,
            resField: columnName,
        });
        this.columnFilterState.items = data.records.map((item, index) => ({
            id: `selection-${index}`,
            label: item.display_name || item.label || item.name || item,
            value: item.value || item,
        }));
        this.columnFilterState.showSearchMore = false;
        if (this._columnFilterTarget !== input || !this.columnFilterPopover.isOpen) {
            this._columnFilterTarget = input;
            this.columnFilterPopover.open(input, {
                state: this.columnFilterState,
                onSelect: (item) => {
                    input.value = '';
                    this.env.searchModel.splitAndAddDomain(JSON.stringify([[columnName, "=", item.value]]));
                },
            });
        }
    },

    _openDateFilter(ev, inputEl, columnName, fieldType) {
        let parsedValue = DateTime.now();
        if (inputEl?.value) {
            const dt = DateTime.fromFormat(inputEl.value, "yyyy-MM-dd");
            if (dt.isValid) {
                parsedValue = dt;
            }
        }
        const rect = inputEl.getBoundingClientRect();
        let leftValue = rect.left
        if (leftValue > "1440"){
            leftValue = 1440;
        }

        this.dialog.add(CalendarDialog, {
            close: () => this.dialog.closeAll(),
            pickerProps: {
                type: fieldType,
                value: parsedValue,
                range: false,
                onSelect: (value) => {
                    let formattedValue;
                    formattedValue = value.toFormat("yyyy-MM-dd HH:mm:ss");

                    if (inputEl) {
                        inputEl.value = formattedValue;
                        inputEl.dispatchEvent(new Event("input", { bubbles: true }));
                    }
                    const dateStr = inputEl?.value;
                    inputEl.value = ""
                    const domain = [[columnName, '>=', dateStr]];
                    const domainString = JSON.stringify(domain);
                    this.env.searchModel.splitAndAddDomain(domainString);
                    this.dialog.closeAll();
                },
            },
            position: {
                top: rect.bottom + window.scrollY + 4,
                left: leftValue + window.scrollX,
            }
        });
    },


    async onDomainFilterClick(ev) {
        const columnName = ev.currentTarget.dataset.column;
        const fieldType = ev.currentTarget.dataset.fieldType;

        let domainArray;

        if (fieldType === "datetime") {
            const now = new Date();
            const pad = (n) => (n < 10 ? '0' + n : n);
            const currentTime = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;

            domainArray = [[columnName, '=', currentTime]];
        } else {
            domainArray = [[columnName, '=', false]];
        }

        const domainString = JSON.stringify(domainArray);

        this.env.services.dialog.add(DomainSelectorDialog, {
            title: "Modify Condition",
            domain: domainString,
            resModel: this.props.list.model.config.resModel,
            context: this.env.searchModel.domainEvalContext,
            onConfirm: (selectedDomain) => this.env.searchModel.splitAndAddDomain(selectedDomain),
        });
    },


    close() {
        registry.category("main_components").remove("spiffy_document");
    },

});

const getAttachmentNextTemporaryId = (function () {
    let tmpId = 0;
    return () => {
        tmpId -= 1;
        return tmpId;
    };
})();

patch(AttachmentUploadService.prototype, {
    get uploadURL() {
        if (session.bg_color){
            return "/app/attachment/upload";
        }
        else{
            return "/mail/attachment/upload";
        }
    },
});

patch(AttachmentList.prototype, {
    /**
     * @param {import("models").Attachment} attachment
     */
    onClickDownload(attachment) {
        if (session.bg_color) {
            var attach_id = attachment.id
            rpc("/attach/get_data", {
                id: attach_id
            }).then(function (data) {
                if (data) {
                    window.flutter_inappwebview.callHandler('blobToBase64Handler', data['pdf_data'], data['attach_type'], data['attach_name']);
                }
            });
        } else {
            super.onClickDownload(attachment);
        }
    }
});

patch(FileViewer.prototype, {
    setup() {
        super.setup();
        this.bg_color = session.bg_color;
    },

    onClickDownload() {
        if (this.bg_color) {
            this._spiffyattachmentdownload();
        } else {
            super.onClickDownload();
        }
    },

    _spiffyattachmentdownload(){
        // var attach_id = this.id
        var localId = this.props.files[this.props.startIndex].localId;
        var match = localId.match(/\d+/);
        var numericPart = match ? match[0] : null;
        rpc("/attach/get_data", {
            id: numericPart
        }).then(function (data) {
            if (data) {
                window.flutter_inappwebview.callHandler('blobToBase64Handler', data['pdf_data'], data['attach_type'], data['attach_name']);
            }
        });
    }
});

const bg_colorService = {
    start() {
        var is_body_color = session.bg_color
        if (is_body_color) {
            userMenuRegistry.remove('log_out');
            userMenuRegistry.remove('odoo_account');
            userMenuRegistry.remove('documentation');
            userMenuRegistry.remove('support');

            userMenuRegistry.add("divert.account", divertColorItem);
            userMenuRegistry.add("divert.account.refresh", divertColorItemRefresh);
        }
    },
};
serviceRegistry.add("bg_color", bg_colorService);

