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
        var self = this
        this.dialog = useService("dialog");
        // this.rpc = rpc;
        this.fileViewer = useFileViewer();
        this.action = useService("action");
        self.showattachment = false
        if ($('body').hasClass('show_attachment')) {
            self.showattachment = true
        }
        this.notificationService = useService("notification");
        this._bizAttachmentTimer = null;
        this._bizLastRecIdsKey = null;

        onMounted(async () => {
            if (self.showattachment) {
                this._bizAttachmentClickHandler = (ev) => { self._loadattachmentviewer(ev); };
                $(document).on('click', '.biz_attachment_section .attachment_box', this._bizAttachmentClickHandler);
                await this._bizRenderAttachments();
            }
        });

        onWillUnmount(() => {
            clearTimeout(this._bizAttachmentTimer);
            if (this._bizAttachmentClickHandler) {
                $(document).off('click', '.biz_attachment_section .attachment_box', this._bizAttachmentClickHandler);
            }
        });

        onPatched(async () => {
            await Promise.resolve();
            if (self.showattachment) {
                clearTimeout(this._bizAttachmentTimer);
                this._bizAttachmentTimer = setTimeout(() => {
                    this._bizRenderAttachments();
                }, 50);
            }
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

    async _bizRenderAttachments() {
        if (!this.showattachment) return;
        if (this._bizAttachmentLoading) return;
        this._bizAttachmentLoading = true;

        $('.attachment_div.new').remove();

        if (this.props.archInfo.editable != 'bottom') {
            const records = this.props.list.records;
            const model = this.props.list.resModel;
            const rec_ids = records.map(r => r.resId).filter(Boolean);
            const recIdsKey = rec_ids.slice().sort().join(',');

            // Only call server if visible records changed
            if (recIdsKey !== this._bizLastRecIdsKey || !this.biz_attachment_data) {
                this._bizLastRecIdsKey = recIdsKey;
                this.biz_attachment_data = await rpc("/get/attachment/data", { model, rec_ids });
            }

            if (this.biz_attachment_data) {
                const attachment_data = this.biz_attachment_data[0];
                $.each(attachment_data, (key, value) => {
                    const $tr = $('tr.o_data_row[resid="' + key + '"]');
                    const $attachment_section = $("<section>", {
                        class: "biz_attachment_section d-flex align-items-center position-absolute flex-nowrap overflow-auto",
                        id: $tr.attr('data-id'),
                    });

                    value.every((attachment, index, arr) => {
                        if (index < 5) {
                            $attachment_section.append(
                                $("<div>", {
                                    class: "attachment_box border d-flex align-items-center mx-2",
                                    "data-id": attachment.attachment_id,
                                    "data-name": attachment.attachment_name,
                                    "data-mimetype": attachment.attachment_mimetype,
                                    "data-rec_id": key,
                                }).append(
                                    $("<span>", { class: "o_image me-2", "data-mimetype": attachment.attachment_mimetype }),
                                    $("<div>", { class: "attachment-name text-nowrap" }).append($("<span>").html(attachment.attachment_name))
                                )
                            );
                            return true;
                        } else {
                            $attachment_section.append(
                                $("<div>", {
                                    class: "attachment_box border attachment_box_counter d-flex align-items-center px-2",
                                    "data-id": attachment.attachment_id,
                                    "data-name": attachment.attachment_name,
                                    "data-mimetype": attachment.attachment_mimetype,
                                    "data-rec_id": key,
                                }).append(
                                    $("<div>", { class: "attachment-name text-nowrap" }).append($("<span>").html("+" + (arr.length - 5)))
                                )
                            );
                            return false;
                        }
                    });

                    $tr.after($("<div>", { class: "attachment_div new" }).append($attachment_section));
                });
            }
        }

        this._bizAttachmentLoading = false;
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


    loadattachmentevents: function () {
        var self = this
        $('.biz_attachment_section .attachment_box').unbind().on('click', function(ev) {self._loadattachmentviewer(ev);})
    },

    close: function(){
        registry.category("main_components").remove('spiffy_document');
    },

    _loadattachmentviewer(ev) {
        var attachment_id = parseInt($(ev.currentTarget).data("id"));
        var rec_id = parseInt($(ev.currentTarget).data("rec_id"));
        var attachment_mimetype = $(ev.currentTarget).data("mimetype");
        var mimetype_match = attachment_mimetype.match("(image|application/pdf|text|video)");
        var attachment_data = this.biz_attachment_data[0];

        if (mimetype_match) {
            var biz_attachment_id = attachment_id;
            var biz_attachment_list = [];
            attachment_data[rec_id].forEach((attachment) => {
                if (attachment.attachment_mimetype.match("(image|application/pdf|text|video)")) {
                    biz_attachment_list.push({
                        id: attachment.attachment_id,
                        filename: attachment.attachment_name,
                        name: attachment.attachment_name,
                        url: "/web/content/" + attachment.attachment_id + "?download=true",
                        type: attachment.attachment_mimetype,
                        mimetype: attachment.attachment_mimetype,
                        is_main: false,
                    });
                }
            });
            
            registry.category("main_components").add('spiffy_document', {
                Component: spiffyDocumentViewer,
                props: { attachments: biz_attachment_list, activeAttachmentID: biz_attachment_id},
            });

            // await whenReady();
        } else {
            this.notificationService.add(_t("Preview for this file type can not be shown"), {
                title: _t("File Format Not Supported"),
                type: 'danger',
                sticky: false
            });
        }
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

