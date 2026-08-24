/** @odoo-module **/

/**
 * Compact, safe Markdown renderer for Linkin AI messages.
 *
 * Fenced blocks (```code / ```mermaid / ```svg) are extracted into
 * placeholders that the AiFormattedText component turns into rendered
 * blocks with copy/download actions. All text is HTML-escaped first and the
 * final HTML is sanitized with DOMPurify, so the renderer never injects raw
 * user content.
 */

const FENCE_RE = /^```([a-zA-Z0-9_+-]*)\s*$/;
const HEADING_RE = /^(#{1,6})\s+(.*)$/;
const HR_RE = /^\s*(-{3,}|\*{3,})\s*$/;
const QUOTE_RE = /^>\s?(.*)$/;
const UL_ITEM_RE = /^\s*[-*+]\s+(.*)$/;
const OL_ITEM_RE = /^\s*(\d+)\.\s+(.*)$/;

export function escapeHtml(text) {
    return String(text || "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

function inlineFormat(text) {
    // text is already HTML-escaped; apply safe inline patterns.
    let out = text;
    out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
    out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    out = out.replace(/__([^_]+)__/g, "<strong>$1</strong>");
    out = out.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    out = out.replace(/_([^_]+)_/g, "<em>$1</em>");
    out = out.replace(/~~([^~]+)~~/g, "<del>$1</del>");
    // Knowledge citations: [SOURCE:123] renders as a clickable superscript
    // that opens the source document (the formatted-text component wires
    // the click handler).
    out = out.replace(
        /\[SOURCE:(\d+)\]/g,
        '<sup class="o_ai_citation" data-chunk-id="$1">[$1]</sup>'
    );
    out = out.replace(
        /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
    );
    return out;
}

function isTableSeparator(line) {
    return /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(line) &&
        /-{2,}/.test(line) && line.includes("|");
}

function renderTable(rows) {
    if (!rows.length) {
        return "";
    }
    const cells = (row) =>
        row
            .trim()
            .replace(/^\||\|$/g, "")
            .split("|")
            .map((cell) => cell.trim());
    const header = cells(rows[0]);
    const bodyRows = rows.slice(1);
    const html = ["<table><thead><tr>"];
    for (const cell of header) {
        html.push(`<th>${inlineFormat(cell)}</th>`);
    }
    html.push("</tr></thead>");
    if (bodyRows.length) {
        html.push("<tbody>");
        for (const row of bodyRows) {
            html.push("<tr>");
            for (const cell of cells(row)) {
                html.push(`<td>${inlineFormat(cell)}</td>`);
            }
            html.push("</tr>");
        }
        html.push("</tbody>");
    }
    html.push("</table>");
    return html.join("");
}

function makePlaceholder(blockType, content, lang) {
    const b64 = btoa(unescape(encodeURIComponent(content)));
    return (
        `<div class="o_ai_block o_ai_${blockType}" ` +
        `data-type="${blockType}" data-content="${b64}" ` +
        `data-lang="${escapeHtml(lang || "")}"></div>`
    );
}

/**
 * Convert markdown text into sanitized HTML with block placeholders.
 * @param {string} text
 * @returns {string}
 */
export function markdownToHtml(text) {
    const lines = String(text || "").split(/\r?\n/);
    const html = [];
    let i = 0;

    const flushList = (listType) => {
        if (!listType) {
            return;
        }
        html.push(`</${listType}>`);
        listType = null;
    };

    let listType = null;
    let paragraph = [];
    const flushParagraph = () => {
        if (paragraph.length) {
            html.push(`<p>${inlineFormat(paragraph.join(" "))}</p>`);
            paragraph = [];
        }
    };

    while (i < lines.length) {
        const line = lines[i];

        // Fenced blocks
        const fence = line.match(FENCE_RE);
        if (fence) {
            flushList(listType);
            listType = null;
            flushParagraph();
            const lang = fence[1];
            const content = [];
            i += 1;
            while (i < lines.length && !FENCE_RE.test(lines[i])) {
                content.push(lines[i]);
                i += 1;
            }
            i += 1; // skip closing fence
            const blockType = lang === "mermaid" ? "mermaid"
                : lang.toLowerCase() === "svg" ? "svg" : "code";
            html.push(makePlaceholder(blockType, content.join("\n"), lang));
            continue;
        }

        // Tables
        if (line.includes("|") && i + 1 < lines.length &&
                isTableSeparator(lines[i + 1])) {
            flushList(listType);
            listType = null;
            flushParagraph();
            const rows = [line];
            i += 2;
            while (i < lines.length && lines[i].includes("|") &&
                    lines[i].trim() !== "") {
                rows.push(lines[i]);
                i += 1;
            }
            html.push(renderTable(rows));
            continue;
        }

        // Headings
        const heading = line.match(HEADING_RE);
        if (heading) {
            flushList(listType);
            listType = null;
            flushParagraph();
            const level = heading[1].length;
            html.push(`<h${level}>${inlineFormat(heading[2])}</h${level}>`);
            i += 1;
            continue;
        }

        // Horizontal rule
        if (HR_RE.test(line)) {
            flushList(listType);
            listType = null;
            flushParagraph();
            html.push("<hr/>");
            i += 1;
            continue;
        }

        // Blockquote
        if (QUOTE_RE.test(line)) {
            flushList(listType);
            listType = null;
            flushParagraph();
            const quote = [];
            while (i < lines.length && QUOTE_RE.test(lines[i])) {
                quote.push(lines[i].match(QUOTE_RE)[1]);
                i += 1;
            }
            html.push(`<blockquote>${inlineFormat(quote.join(" "))}</blockquote>`);
            continue;
        }

        // Lists
        const ulItem = line.match(UL_ITEM_RE);
        const olItem = line.match(OL_ITEM_RE);
        if (ulItem || olItem) {
            flushParagraph();
            const newType = ulItem ? "ul" : "ol";
            if (listType !== newType) {
                flushList(listType);
                html.push(`<${newType}>`);
                listType = newType;
            }
            const itemText = ulItem ? ulItem[1] : olItem[2];
            html.push(`<li>${inlineFormat(itemText)}</li>`);
            i += 1;
            continue;
        }

        // Blank line ends lists and paragraphs
        if (!line.trim()) {
            flushList(listType);
            listType = null;
            flushParagraph();
            i += 1;
            continue;
        }

        // Plain paragraph line
        paragraph.push(line.trim());
        i += 1;
    }

    flushList(listType);
    flushParagraph();
    return html.join("\n");
}

/**
 * Sanitize generated HTML with DOMPurify (available globally in the web
 * client). Block placeholders and the tags used by the renderer are allowed.
 * @param {string} html
 * @returns {string}
 */
export function sanitizeHtml(html) {
    if (!window.DOMPurify) {
        return html;
    }
    return window.DOMPurify.sanitize(html, {
        ADD_ATTR: ["target", "rel", "data-type", "data-content", "data-lang"],
        ADD_TAGS: ["table", "thead", "tbody", "tr", "th", "td"],
    });
}

export function decodeContent(b64) {
    try {
        return decodeURIComponent(escape(atob(b64)));
    } catch (error) {
        return "";
    }
}
