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
import { onMounted, useState, useChildSubEnv, onPatched, onWillUnmount } from "@odoo/owl";
import { CalendarDialog } from "./calendar_dialog";
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
        this.showattachment = document.body.classList.contains("show_attachment");
        this.notificationService = useService("notification");
        this.attachmentState = useState({ byResId: {} });
        this._bizAttachmentTimer = null;
        this._bizLastRecIdsKey = null;
        this._bizAlive = true;

        onMounted(() => {
            this._scheduleAttachmentLoad();
        });

        onWillUnmount(() => {
            this._bizAlive = false;
            clearTimeout(this._bizAttachmentTimer);
        });

        onPatched(() => {
            this._scheduleAttachmentLoad();
            // Funcationality to manage the expand and collapse group on click
            const expandGroup = $('.expand_groups_records');
            if (!this.props.list?.isGrouped) {
                expandGroup.addClass('d-none');
            } else {
                expandGroup.removeClass('d-none');
                const groups = this.props.list.groups || [];
                const anyExpanded = groups.some(group => !group.isFolded);
                if (anyExpanded) {
                    expandGroup.addClass('active');
                } else {
                    expandGroup.removeClass('active');
                }
                if (!expandGroup.hasClass('bound')) {
                    expandGroup.addClass('bound');
                    expandGroup.on('click', (ev) => {
                        this.groupsExpand(ev);
                    });
                }
            }
        });
    },

    _attachmentRecordKey() {
        const records = this.props.list.records || [];
        return records.map((record) => record.resId).filter(Boolean).slice().sort().join(",");
    },

    _scheduleAttachmentLoad() {
        if (!this.showattachment || this.props.archInfo.editable == "bottom" || this._bizAttachmentLoading) {
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
        if (!this._bizAlive || !this.showattachment || this.props.archInfo.editable == "bottom") {
            return;
        }
        const recIds = (this.props.list.records || []).map((record) => record.resId).filter(Boolean);
        const recIdsKey = recIds.slice().sort().join(",");
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
        if (!this.showattachment || !record?.resId || this.props.archInfo.editable == "bottom") {
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

    groupsExpand(ev){
        ev.stopPropagation();
        const groups = this.props.list.groups;
        groups.forEach((group) => {
            group.toggle();
        })
        const expandGroup = $('.expand_groups_records');
        const anyExpanded = this.props.list.groups.some(g => !g.isFolded);
        if (anyExpanded) {  
            expandGroup.addClass('active');
        } else {
            expandGroup.removeClass('active');
        }
    },

    async onColumnFilter(ev) {
        const model = this.props.list.model.config.resModel;
        const columnName = ev.currentTarget.dataset.column;
        const ColumnString = ev.currentTarget.dataset.fieldname;
        const fieldType = ev.currentTarget.dataset.fieldType;
        const input = ev.currentTarget;
        const table = $('div.o_list_renderer table.o_list_table')
        const el = table
        if (!el) {
            console.warn("Table element not found");
            return;
        }

        if (!input.dataset.enterListenerAdded) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    const filterValue = input.value.trim();
                    let domain;

                    if (!filterValue) {
                        // If input is empty, clear domain filter and clear input
                        domain = [];
                        input.value = '';  // clear input field
                        const domainString = JSON.stringify(domain);
                        this.env.searchModel.splitAndAddDomain(domainString);
                        input.value = ''; 
                        return;
                    }

                    if (fieldType === 'char' || fieldType === 'text') {
                        domain = [[columnName, 'ilike', filterValue]];
                        input.value = ''; 
                    } else if (fieldType === 'integer' || fieldType === 'float') {
                        const number = parseFloat(filterValue);
                        if (!isNaN(number)) {
                            domain = [[columnName, '>=', number]];
                            input.value = ''; 
                        } else {
                            alert("Invalid number input");
                            return;
                        }
                    } else if (fieldType === 'monetary') {
                        const number = parseFloat(filterValue);
                        if (!isNaN(number)) {
                            domain = [[columnName, '>=', number]];
                            input.value = ''; 
                        } else {
                            alert("Invalid monetary input");
                            return;
                        }
                    } else if (fieldType === 'boolean') {
                        const boolValue = filterValue.toLowerCase();
                        if (boolValue === 'true' || boolValue === 'false') {
                            domain = [[columnName, '=', boolValue === 'true']];
                            input.value = ''; 
                        } else {
                            alert("Enter true or false");
                            return;
                        }
                    } else if (fieldType === 'many2one' || fieldType === 'one2many' || fieldType === 'many2many') {
                        domain = [[columnName, 'ilike', filterValue]];
                        input.value = ''; 
                    } else if (fieldType === 'datetime' || fieldType === 'date') {
                        // Try to parse date, and if invalid alert user
                        const dateObj = new Date(filterValue);
                        if (isNaN(dateObj.getTime())) {
                            alert("Invalid date format. Please enter a valid date.");
                            return;
                        }
                        // Format date as ISO string for domain
                        const pad = (num) => num.toString().padStart(2, '0');
                        const isoDate = `${dateObj.getFullYear()}-${pad(dateObj.getMonth() + 1)}-${pad(dateObj.getDate())}`;
                        domain = [[columnName, '=', isoDate]];
                        input.value = ''; 
                    } else {
                        domain = [[columnName, '=', filterValue]];
                        input.value = ''; 
                    }

                    const domainString = JSON.stringify(domain);
                    this.env.searchModel.splitAndAddDomain(domainString);
                    input.value = ''; 
                }
            });

            input.dataset.enterListenerAdded = "true";
        }

        // Only run dropdown logic for relational fields
        if (['many2one', 'one2many', 'many2many'].includes(fieldType)) {
            // Remove any existing dropdown first
            const existingDropdown = document.querySelector('.filter-dropdown');
            if (existingDropdown) {
                existingDropdown.remove();
            }

            await rpc('/filter/relational/field/list', {
                resModel: model,
                resField: columnName,
                searchTerm: input.value || '',
            }).then(data => {
                if (data.error) {
                    console.error('Filter list error:', data.error);
                    return;
                }

                // Create dropdown
                const dropdown = document.createElement('div');
                dropdown.classList.add('filter-dropdown');

                // Set position near the input field
                const rect = input.getBoundingClientRect();
                dropdown.style.left = `${rect.left + window.pageXOffset}px`;
                dropdown.style.top = `${rect.bottom + window.pageYOffset}px`;

                const maxVisible = 6;
                const recordsToShow = data.records.slice(0, maxVisible);

                // Add records to dropdown
                recordsToShow.forEach(rec => {
                    const item = document.createElement('div');
                    item.classList.add('relational_filter_data');
                    item.textContent = rec.name || `Record ${rec.id}`;

                    item.addEventListener('click', () => {
                        input.value = rec.name;
                        dropdown.remove();
                        const domainString = `[["${columnName}", "=", ${rec.id}]]`;
                        this.env.searchModel.splitAndAddDomain(domainString);
                        input.value = ''; 
                    });

                    dropdown.appendChild(item);
                });

                // Add "Search More" button if needed
                if (data.records.length > maxVisible) {
                    const searchMore = document.createElement('div');
                    searchMore.classList.add('search_more');
                    searchMore.textContent = 'Search more...';

                    const self = this;  // capture component context

                    searchMore.addEventListener('click', () => {
                        dropdown.remove();

                        self.env.services.dialog.add(SelectCreateDialog, {
                            resModel: data.related_model,
                            title: `Select ${ColumnString}`,
                            multiSelect: true,
                            noCreate: true,
                            onSelected: async (selectedRecords) => {
                                if (selectedRecords && selectedRecords.length > 0) {
                                    const RecordList = await rpc('/filter/relational/field/data', {
                                        resModel: data.related_model,
                                        resField: selectedRecords,
                                    });
                                    const recordIds = RecordList.map(r => r.id);
                                    const domain = [[columnName, "in", recordIds]];

                                    // Add the domain to the search model
                                    self.env.searchModel.splitAndAddDomain(domain);
                                } else {
                                    alert("Please select at least one record.");
                                }
                            },
                        });
                    });


                    dropdown.appendChild(searchMore);
                }

                document.body.appendChild(dropdown);

                // Remove dropdown when clicking outside
                const onClickOutside = (event) => {
                    if (!dropdown.contains(event.target) && event.target !== input) {
                        dropdown.remove();
                        document.removeEventListener('click', onClickOutside);
                    }
                };
                document.addEventListener('click', onClickOutside);
            });
        }

        if (fieldType === 'selection') {
            const input = ev.currentTarget;

            const data = await rpc('/selection/filter/list', {
                resModel: model,
                resField: columnName,
            });

            const existingDropdown = input.parentElement.querySelector('.filter-dropdown');
            if (existingDropdown) existingDropdown.remove();

            const dropdown = document.createElement('div');
            dropdown.classList.add('filter-dropdown');

            const rect = input.getBoundingClientRect();
            dropdown.style.left = (rect.left + window.pageXOffset) + 'px';
            dropdown.style.top = (rect.bottom + window.pageYOffset) + 'px';

            data.records.forEach(item => {
                const option = document.createElement('div');
                option.textContent = item.display_name || item.label || item.name || item;
                option.classList.add('selection-filter-dropdown');

                option.addEventListener('click', () => {
                    input.value = item.value || item;
                    dropdown.remove();

                    const domain = [[columnName, '=', item.value || item]];
                    const domainString = JSON.stringify(domain);
                    this.env.searchModel.splitAndAddDomain(domainString);
                    input.value = ''; 
                });

                dropdown.appendChild(option);
            });

            document.body.appendChild(dropdown);

            const onClickOutside = (event) => {
                if (!dropdown.contains(event.target) && event.target !== input) {
                    dropdown.remove();
                    document.removeEventListener('click', onClickOutside);
                }
            };
            document.addEventListener('click', onClickOutside);
        }

        if (['datetime', 'date'].includes(fieldType)) {
            const inputEl = ev.currentTarget.closest(".input-group").querySelector("input");
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
            const fieldType = ev.currentTarget.getAttribute("data-field-type");

            this.dialog.add(CalendarDialog, {
                close: () => this.dialog.closeAll(),
                pickerProps: {
                    type: fieldType,
                    value: parsedValue,
                    range: false,
                    onSelect: (value) => {
                        // Format value (Luxon → string)
                        let formattedValue;
                        formattedValue = value.toFormat("yyyy-MM-dd HH:mm:ss");

                        if (inputEl) {
                            inputEl.value = formattedValue;
                            inputEl.dispatchEvent(new Event("input", { bubbles: true }));
                        }
                        const dateStr = inputEl?.value;
                        const columnName = ev.target.getAttribute("data-column");
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
        }
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

