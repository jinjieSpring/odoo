/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

/*Developed by Bizople Solutions Pvt. Ltd.
See LICENSE file for full copyright and licensing details*/

import { DateTimeInput } from "@web/core/datetime/datetime_input";
import { DateTimePicker } from "@web/core/datetime/datetime_picker";
import { DateTimePickerPopover } from "@web/core/datetime/datetime_picker_popover";
import { useDateTimePicker } from "@web/core/datetime/datetime_picker_hook";
import { datetimePickerService } from "@web/core/datetime/datetimepicker_service";
import { Component } from "@odoo/owl";
import { onMounted, onWillUnmount, useRef } from "@odoo/owl";

/**
 * @typedef {import("./datetime_picker").DateTimePickerProps} DateTimePickerProps
 *
 * @typedef DateTimePickerPopoverProps
 * @property {() => void} close
 * @property {DateTimePickerProps} pickerProps
 */
export class CalendarDialog extends Component {
    static template = "biz.CalendarDialog";
    static props = {
        close: Function, // Given by the Popover service
        pickerProps: { type: Object, shape: DateTimePicker.props },
        position: { type: Object },
    };
    setup() {
        this.props.onSelect = (ev) => {
            this.props.value = ev.detail.value;
        };
        this.dialogRef = useRef("calendarDialog");
        this.onGlobalClick = this.onGlobalClick.bind(this);
        onMounted(() => {
            document.addEventListener("click", this.onGlobalClick, true);
        });
        onWillUnmount(() => {
            document.removeEventListener("click", this.onGlobalClick, true);
        });
    }
    onGlobalClick(ev) {
        const dialogEl = this.dialogRef?.el;
        // If the dialog exists and the clicked target is not inside it, close
        if (dialogEl && !dialogEl.contains(ev.target)) {
            this.props.close?.();
        }
    }
}
CalendarDialog.components = { DateTimeInput, useDateTimePicker, DateTimePicker, DateTimePickerPopover, datetimePickerService };