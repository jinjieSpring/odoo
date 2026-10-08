/** @odoo-module */
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { Component } from "@odoo/owl";

// Dropdown content for the list view column filters (relational and
// selection fields). Positioning and click-away closing are handled by the
// popover service; the items list is a reactive object owned by the caller,
// so live-search typing updates the open popover.
export class ColumnFilterPopover extends Component {
    static template = "spiffy_theme_backend.ColumnFilterPopover";
    static props = {
        state: Object, // { items: [{ id, label, value }], showSearchMore: Boolean }
        onSelect: Function,
        onSearchMore: { type: Function, optional: true },
        close: Function,
    };

    select(item) {
        this.props.onSelect(item);
        this.props.close();
    }

    searchMore() {
        this.props.onSearchMore?.();
        this.props.close();
    }
}
