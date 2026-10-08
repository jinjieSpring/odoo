/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { Component, markup, onWillUnmount, useEffect, useRef, useState } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";

const NOTE_PALLETS = ["pallet_1", "pallet_2", "pallet_3", "pallet_4", "pallet_5", "pallet_6", "pallet_7"];

export class TodoSidebar extends Component {
    static template = "spiffy_theme_backend.TodoSidebar";
    static props = {
        // Shared reactive state owned by the NavBar: { visible: Boolean }
        state: Object,
    };

    setup() {
        this.state = useState({
            notes: [],
            loaded: false,
            showForm: false,
            editingId: null,
            formPallet: "pallet_1",
        });
        this.markup = markup;
        this.pallets = NOTE_PALLETS;
        this.userId = user.userId;
        this.listRef = useRef("noteList");
        this.titleRef = useRef("titleInput");
        this.descRef = useRef("descInput");

        useEffect(
            (visible) => {
                document.body.classList.toggle("backdrop", Boolean(visible));
                if (visible && !this.state.loaded) {
                    this.loadNotes();
                }
            },
            () => [this.props.state.visible]
        );
        onWillUnmount(() => document.body.classList.remove("backdrop"));
    }

    async loadNotes() {
        const data = await rpc("/show/user/todo/list/data", {});
        this.state.notes = data.notes;
        this.state.loaded = true;
    }

    close() {
        this.props.state.visible = false;
    }

    toggleForm() {
        if (this.state.showForm) {
            this.closeForm();
        } else {
            this.state.showForm = true;
        }
    }

    closeForm() {
        this.state.showForm = false;
        this.state.editingId = null;
        this.state.formPallet = "pallet_1";
        if (this.titleRef.el) {
            this.titleRef.el.value = "";
        }
        if (this.descRef.el) {
            this.descRef.el.innerHTML = "";
        }
    }

    editNote(note) {
        this.state.editingId = note.id;
        this.state.formPallet = note.note_color_pallet || "pallet_1";
        // The form stays mounted (hidden with d-none), so refs are available.
        if (this.titleRef.el) {
            this.titleRef.el.value = note.name;
        }
        if (this.descRef.el) {
            this.descRef.el.innerHTML = note.description;
        }
        this.state.showForm = true;
    }

    async saveNote() {
        const title = this.titleRef.el ? this.titleRef.el.value : "";
        const description = this.descRef.el ? this.descRef.el.innerHTML : "";
        if (title === "" || description === "") {
            return;
        }
        const isUpdate = Boolean(this.state.editingId);
        const payload = {
            user_id: this.userId,
            note_title: title,
            note_description: description,
            is_update: isUpdate,
            note_pallet: this.state.formPallet,
        };
        if (isUpdate) {
            payload.note_id = this.state.editingId;
        }
        const rec = await rpc("/create/todo", payload);
        if (!rec) {
            return;
        }
        if (isUpdate) {
            const index = this.state.notes.findIndex((n) => n.id === rec.id);
            if (index !== -1) {
                this.state.notes.splice(index, 1);
            }
        }
        this.state.notes.unshift(rec);
        this.closeForm();
        this.listRef.el?.scrollTo({ top: 0, behavior: "smooth" });
    }

    async deleteNote(note) {
        const res = await rpc("/delete/todo", { noteID: note.id });
        if (res) {
            const index = this.state.notes.findIndex((n) => n.id === note.id);
            if (index !== -1) {
                this.state.notes.splice(index, 1);
            }
        }
    }
}
