/** @odoo-module **/
// Part of Bizople Solutions Pvt. Ltd.
// Licensed under the Bizople Proprietary License v1.0.
// Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import { Component, reactive, useState, useChildSubEnv, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { registry } from "@web/core/registry";
import { View } from "@web/views/view";
import { _t } from "@web/core/l10n/translation";

const PANEL_WIDTH_KEY  = "spiffy_split_panel_width";
const MAX_TABS_KEY     = "spiffy_split_max_tabs";
const TABS_KEY         = "spiffy_split_tabs";
const ACTIVE_TAB_KEY   = "spiffy_split_active_tab";
const DEFAULT_PANEL_WIDTH = 520;
const DEFAULT_MAX_TABS    = 5;
const ABS_MAX_TABS        = 10;

// Minimum panel width (px) — below this the form becomes unusable
const RESIZE_MIN = 280;
// Maximum panel width — leave at least 300 px for the list/kanban on the left
function getResizeMax() {
    return window.innerWidth - 300;
}

let _tabIdCounter = 0;
function nextTabId() {
    return ++_tabIdCounter;
}

// ── Service ───────────────────────────────────────────────────────────────────
registry.category("services").add("split_view_panel", {
    dependencies: ["orm", "notification"],
    start(env, { orm, notification }) {
        const service = reactive({
            isOpen:      false,
            tabs:        [],
            activeTabId: null,
            panelWidth: parseInt(
                localStorage.getItem(PANEL_WIDTH_KEY) || String(DEFAULT_PANEL_WIDTH), 10
            ),
            maxTabs: Math.min(
                ABS_MAX_TABS,
                parseInt(localStorage.getItem(MAX_TABS_KEY) || String(DEFAULT_MAX_TABS), 10)
            ),
        });

        function _syncBodyClass() {
            document.body.classList.toggle("spiffy-split-panel-open", service.isOpen);
            document.body.style.setProperty("--spiffy-split-width", service.panelWidth + "px");
        }

        function _saveTabs() {
            const data = service.tabs.map((t) => ({
                resId: t.resId, resModel: t.resModel, label: t.label,
            }));
            localStorage.setItem(TABS_KEY, JSON.stringify(data));
            const active = service.tabs.find((t) => t.id === service.activeTabId);
            if (active) {
                localStorage.setItem(ACTIVE_TAB_KEY, JSON.stringify({
                    resId: active.resId, resModel: active.resModel,
                }));
            } else {
                localStorage.removeItem(ACTIVE_TAB_KEY);
            }
        }

        function _loadPersistedTabs() {
            try {
                const raw = localStorage.getItem(TABS_KEY);
                if (!raw) return;
                const saved = JSON.parse(raw);
                if (!Array.isArray(saved) || saved.length === 0) return;
                const restored = saved.slice(0, service.maxTabs).map((t) => ({
                    id: nextTabId(),
                    resId: t.resId,
                    resModel: t.resModel,
                    label: t.label || `#${t.resId}`,
                }));
                service.tabs = restored;
                const activeRaw = localStorage.getItem(ACTIVE_TAB_KEY);
                if (activeRaw) {
                    const { resId, resModel } = JSON.parse(activeRaw);
                    const found = restored.find((t) => t.resId === resId && t.resModel === resModel);
                    service.activeTabId = found ? found.id : restored[restored.length - 1].id;
                } else {
                    service.activeTabId = restored[restored.length - 1].id;
                }
                service.isOpen = true;
                _syncBodyClass();
            } catch (_) {}
        }

        async function openRecord({ resId, resModel }) {
            const existing = service.tabs.find(
                (t) => t.resId === resId && t.resModel === resModel
            );
            if (existing) {
                service.activeTabId = existing.id;
                service.isOpen = true;
                _syncBodyClass();
                return;
            }

            if (service.tabs.length >= service.maxTabs) {
                const removed = service.tabs[0];
                service.tabs.shift();
                notification.add(
                    _t(`Tab limit (${service.maxTabs}) reached. "${removed.label}" was replaced.`),
                    { type: "warning", title: _t("Split View") }
                );
            }

            let label = `#${resId}`;
            try {
                const result = await orm.read(resModel, [resId], ["display_name"]);
                if (result?.[0]?.display_name) {
                    const name = result[0].display_name;
                    label = name.length > 25 ? name.slice(0, 25) + "\u2026" : name;
                }
            } catch (_) {}

            const tab = { id: nextTabId(), resId, resModel, label };
            service.tabs.push(tab);
            service.activeTabId = tab.id;
            service.isOpen = true;
            _syncBodyClass();
            _saveTabs();
        }

        function closeTab(tabId) {
            const idx = service.tabs.findIndex((t) => t.id === tabId);
            if (idx === -1) return;
            service.tabs.splice(idx, 1);
            if (service.tabs.length === 0) {
                service.isOpen = false;
                service.activeTabId = null;
            } else if (service.activeTabId === tabId) {
                service.activeTabId = service.tabs[Math.max(0, idx - 1)].id;
            }
            _syncBodyClass();
            _saveTabs();
        }

        function activateTab(tabId) {
            service.activeTabId = tabId;
            _saveTabs();
        }

        function closeAll() {
            service.tabs      = [];
            service.activeTabId = null;
            service.isOpen    = false;
            _syncBodyClass();
            localStorage.removeItem(TABS_KEY);
            localStorage.removeItem(ACTIVE_TAB_KEY);
        }

        function setPanelWidth(width) {
            service.panelWidth = width;
            localStorage.setItem(PANEL_WIDTH_KEY, String(width));
            document.body.style.setProperty("--spiffy-split-width", width + "px");
        }

        function setMaxTabs(n) {
            const clamped = Math.max(1, Math.min(ABS_MAX_TABS, n));
            service.maxTabs = clamped;
            localStorage.setItem(MAX_TABS_KEY, String(clamped));
            while (service.tabs.length > clamped) {
                service.tabs.shift();
            }
            if (
                service.tabs.length > 0 &&
                !service.tabs.find((t) => t.id === service.activeTabId)
            ) {
                service.activeTabId = service.tabs[service.tabs.length - 1].id;
            }
        }

        _syncBodyClass();
        _loadPersistedTabs();

        return Object.assign(service, {
            openRecord,
            closeTab,
            activateTab,
            closeAll,
            setPanelWidth,
            setMaxTabs,
        });
    },
});

// ── SplitViewTab ──────────────────────────────────────────────────────────────
export class SplitViewTab extends Component {
    setup() {
        useChildSubEnv({
            config: {
                ...this.env.config,
                noBreadcrumbs: true,
                viewSwitcherEntries: [],
                views: [[false, "form"]],
            },
        });
    }
}
SplitViewTab.template = "spiffy_theme_backend.SplitViewTab";
SplitViewTab.props = {
    resId:    { type: Number },
    resModel: { type: String },
};
SplitViewTab.components = { View };

// ── SplitViewPanel ────────────────────────────────────────────────────────────
export class SplitViewPanel extends Component {
    setup() {
        this.service      = useService("split_view_panel");
        this.ui           = useState({ settingsOpen: false });
        this._resizing    = false;
        this._startX      = 0;
        this._startWidth  = 0;
        this._onMouseMove = this._onMouseMove.bind(this);
        this._onMouseUp   = this._onMouseUp.bind(this);
        onWillUnmount(() => {
            document.removeEventListener("mousemove", this._onMouseMove);
            document.removeEventListener("mouseup", this._onMouseUp);
        });
    }

    get tabLimitOptions() { return [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]; }

    toggleSettings() {
        this.ui.settingsOpen = !this.ui.settingsOpen;
    }

    onResizerMouseDown(ev) {
        ev.preventDefault();
        this._resizing   = true;
        this._startX     = ev.clientX;
        this._startWidth = this.service.panelWidth;
        document.addEventListener("mousemove", this._onMouseMove);
        document.addEventListener("mouseup", this._onMouseUp);
        document.body.classList.add("spiffy-split-resizing");
    }

    _onMouseMove(ev) {
        if (!this._resizing) return;
        const delta    = this._startX - ev.clientX;
        const newWidth = Math.max(RESIZE_MIN, Math.min(getResizeMax(), this._startWidth + delta));
        this.service.setPanelWidth(newWidth);
    }

    _onMouseUp() {
        this._resizing = false;
        document.removeEventListener("mousemove", this._onMouseMove);
        document.removeEventListener("mouseup", this._onMouseUp);
        document.body.classList.remove("spiffy-split-resizing");
    }

    get panelStyle() {
        return `width: ${this.service.panelWidth}px`;
    }
}
SplitViewPanel.template = "spiffy_theme_backend.SplitViewPanel";
SplitViewPanel.props    = {};
SplitViewPanel.components = { SplitViewTab };

registry.category("main_components").add("SpiffySplitViewPanel", {
    Component: SplitViewPanel,
    props: {},
});
