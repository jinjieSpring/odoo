/** @odoo-module **/

import { Component, useEffect, useRef, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { useService } from "@web/core/utils/hooks";
import {
    decodeContent,
    markdownToHtml,
    sanitizeHtml,
} from "./ai_markdown";

/**
 * Renders markdown content (headings, bold/italic, links, lists, tables,
 * code / mermaid / svg blocks) into sanitized HTML. Every fenced block gets a
 * copy and a download button that appear on hover.
 */
export class AiFormattedText extends Component {
    static template = "ai_base.FormattedText";
    static props = {
        content: { type: String, optional: true },
        className: { type: String, optional: true },
    };

    setup() {
        this.rootRef = useRef("root");
        this.state = useState({ html: "" });
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        useEffect(
            () => {
                this.state.html = sanitizeHtml(
                    markdownToHtml(this.props.content || "")
                );
            },
            () => [this.props.content]
        );
        useEffect(
            () => {
                const root = this.rootRef.el;
                if (!root) {
                    return;
                }
                root.innerHTML = this.state.html;
                this._processBlocks(root);
                this._processCitations(root);
            },
            () => [this.state.html]
        );
    }

    _processCitations(root) {
        for (const sup of root.querySelectorAll(".o_ai_citation")) {
            sup.addEventListener("click", (ev) => {
                ev.preventDefault();
                ev.stopPropagation();
                this._openSource(sup.dataset.chunkId);
            });
        }
    }

    async _openSource(chunkId) {
        // hdai_knowledge is optional: when it is not installed the citation
        // superscript is inert (no action available).
        try {
            const action = await this.orm.call(
                "ai.knowledge.chunk",
                "action_open_source",
                [chunkId]
            );
            if (action && action.type) {
                this.actionService.doAction(action);
            }
        } catch (error) {
            this.notification.add(
                _t("Could not open the source document: %s", error.message || error),
                { type: "warning" }
            );
        }
    }

    _processBlocks(root) {
        for (const blockEl of root.querySelectorAll(
            ".o_ai_block[data-type]"
        )) {
            const type = blockEl.dataset.type;
            const content = decodeContent(blockEl.dataset.content || "");
            const lang = blockEl.dataset.lang || "";
            const wrapper = document.createElement("div");
            wrapper.className = `o_ai_block o_ai_block_${type}`;
            const head = document.createElement("div");
            head.className = "o_ai_block_head";
            const label = document.createElement("span");
            label.className = "o_ai_block_label";
            label.textContent =
                type === "code" ? (lang || "code") : type;
            const actions = document.createElement("div");
            actions.className = "o_ai_block_actions";
            const extension =
                type === "svg" ? "svg" : type === "mermaid" ? "mmd" : "txt";
            actions.appendChild(
                this._actionButton("fa-copy", _t("Copy"), () =>
                    this._copy(content)
                )
            );
            actions.appendChild(
                this._actionButton("fa-download", _t("Download"), () =>
                    this._download(
                        content,
                        `hdai_${type}.${extension}`,
                        type === "svg" ? "image/svg+xml" : "text/plain"
                    )
                )
            );
            head.append(label, actions);
            const body = document.createElement("div");
            body.className = "o_ai_block_body";
            wrapper.append(head, body);
            blockEl.replaceWith(wrapper);
            if (type === "code") {
                this._renderCode(body, content, lang);
            } else if (type === "svg") {
                this._renderSvg(body, content);
            } else {
                this._renderMermaid(body, content);
            }
        }
    }

    _actionButton(icon, title, onClick) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "btn btn-link p-1 o_ai_block_action";
        button.title = title;
        const iconEl = document.createElement("i");
        iconEl.className = `fa ${icon}`;
        button.appendChild(iconEl);
        button.addEventListener("click", (ev) => {
            ev.preventDefault();
            ev.stopPropagation();
            onClick();
        });
        return button;
    }

    _renderCode(body, content, lang) {
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        if (lang) {
            code.className = `language-${lang}`;
        }
        code.textContent = content;
        pre.appendChild(code);
        body.appendChild(pre);
        if (window.Prism && lang && window.Prism.languages[lang]) {
            try {
                window.Prism.highlightElement(code);
            } catch (error) {
                console.error("ai_base: prism highlight failed", error);
            }
        }
    }

    _renderSvg(body, content) {
        let sanitized = content;
        if (window.DOMPurify) {
            sanitized = window.DOMPurify.sanitize(content, {
                USE_PROFILES: { svg: true, svgFilters: true },
            });
        }
        if (!sanitized.trim()) {
            this._renderCode(body, content, "svg");
            return;
        }
        const holder = document.createElement("div");
        holder.className = "o_ai_svg_holder";
        holder.innerHTML = sanitized;
        body.appendChild(holder);
    }

    async _renderMermaid(body, content) {
        const fallback = () => {
            this._renderCode(body, content, "mermaid");
        };
        // Mermaid is vendored locally (static/lib/mermaid) and loaded as a
        // web asset, so rendering never needs an external network.
        if (!window.mermaid) {
            fallback();
            return;
        }
        if (!window.mermaid._hdai_initialized) {
            window.mermaid.initialize({
                startOnLoad: false,
                securityLevel: "strict",
            });
            window.mermaid._hdai_initialized = true;
        }
        try {
            const id =
                "o_ai_mermaid_" +
                Math.random().toString(36).slice(2, 10);
            const { svg } = await window.mermaid.render(id, content);
            const holder = document.createElement("div");
            holder.className = "o_ai_mermaid_svg";
            holder.innerHTML = svg;
            body.appendChild(holder);
        } catch (error) {
            console.error("ai_base: mermaid render failed", error);
            fallback();
        }
    }

    async _copy(text) {
        try {
            await navigator.clipboard.writeText(text);
        } catch (error) {
            const textarea = document.createElement("textarea");
            textarea.value = text;
            textarea.style.position = "fixed";
            textarea.style.opacity = "0";
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand("copy");
            textarea.remove();
        }
    }

    _download(text, filename, mime) {
        const blob = new Blob([text], { type: mime });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(url);
    }
}
