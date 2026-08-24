# -*- coding: utf-8 -*-
"""Convert Markdown into a safe HTML fragment for mail / chatter bodies.

Chat UI still renders Markdown in OWL. This helper is for ``message_post``
and the mail composer, where the body is HTML. Text is escaped first; only
http(s) links become anchors; SVG fences become data-URL images; mermaid
stays a code block (no JS in chatter).
"""
import base64
import html
import re

_FENCE_RE = re.compile(r'^```([a-zA-Z0-9_+-]*)\s*$')
_HEADING_RE = re.compile(r'^(#{1,6})\s+(.*)$')
_HR_RE = re.compile(r'^\s*(-{3,}|\*{3,})\s*$')
_QUOTE_RE = re.compile(r'^>\s?(.*)$')
_UL_ITEM_RE = re.compile(r'^\s*[-*+]\s+(.*)$')
_OL_ITEM_RE = re.compile(r'^\s*(\d+)\.\s+(.*)$')
_TABLE_SEP_RE = re.compile(r'^\s*\|?[\s:|-]+\|[\s:|-]*$')


def _inline(text):
    text = html.escape(text, quote=True)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__([^_]+)__', r'<strong>\1</strong>', text)
    text = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', text)
    text = re.sub(r'_([^_]+)_', r'<em>\1</em>', text)
    text = re.sub(r'~~([^~]+)~~', r'<del>\1</del>', text)
    text = re.sub(
        r'\[SOURCE:(\d+)\]',
        r'<sup>[\1]</sup>',
        text,
    )
    text = re.sub(
        r'\[([^\]]+)\]\((https?://[^\s)]+)\)',
        r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
        text,
    )
    return text


def _is_table_separator(line):
    return bool(
        _TABLE_SEP_RE.match(line)
        and re.search(r'-{2,}', line)
        and '|' in line
    )


def _table_cells(row):
    return [
        cell.strip()
        for cell in re.sub(r'^\||\|$', '', row.strip()).split('|')
    ]


def _render_table(rows):
    if not rows:
        return ''
    header = _table_cells(rows[0])
    parts = ['<table><thead><tr>']
    parts.extend('<th>%s</th>' % _inline(cell) for cell in header)
    parts.append('</tr></thead>')
    body_rows = rows[1:]
    if body_rows:
        parts.append('<tbody>')
        for row in body_rows:
            parts.append('<tr>')
            parts.extend(
                '<td>%s</td>' % _inline(cell) for cell in _table_cells(row))
            parts.append('</tr>')
        parts.append('</tbody>')
    parts.append('</table>')
    return ''.join(parts)


def markdown_to_html(text):
    """Convert Markdown text into a safe HTML fragment."""
    if not text:
        return ''
    lines = text.splitlines()
    out = []
    i = 0
    list_type = None
    paragraph = []

    def flush_list():
        nonlocal list_type
        if list_type:
            out.append('</%s>' % list_type)
            list_type = None

    def flush_paragraph():
        if paragraph:
            out.append('<p>%s</p>' % _inline(' '.join(paragraph)))
            paragraph.clear()

    while i < len(lines):
        line = lines[i]
        fence = _FENCE_RE.match(line)
        if fence:
            flush_list()
            flush_paragraph()
            lang = fence.group(1)
            buf = []
            i += 1
            while i < len(lines) and not _FENCE_RE.match(lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1
            code_text = '\n'.join(buf)
            if lang.lower() == 'svg':
                encoded = base64.b64encode(code_text.encode()).decode()
                out.append(
                    '<p><img src="data:image/svg+xml;base64,%s" '
                    'alt="svg"/></p>' % encoded)
            else:
                out.append(
                    '<pre><code class="language-%s">%s</code></pre>' % (
                        html.escape(lang, quote=True),
                        html.escape(code_text, quote=True),
                    )
                )
            continue
        if (
            '|' in line
            and i + 1 < len(lines)
            and _is_table_separator(lines[i + 1])
        ):
            flush_list()
            flush_paragraph()
            rows = [line]
            i += 2
            while (
                i < len(lines)
                and '|' in lines[i]
                and lines[i].strip()
            ):
                rows.append(lines[i])
                i += 1
            out.append(_render_table(rows))
            continue
        heading = _HEADING_RE.match(line)
        if heading:
            flush_list()
            flush_paragraph()
            level = len(heading.group(1))
            out.append('<h%d>%s</h%d>' % (
                level, _inline(heading.group(2)), level))
            i += 1
            continue
        if _HR_RE.match(line):
            flush_list()
            flush_paragraph()
            out.append('<hr/>')
            i += 1
            continue
        if _QUOTE_RE.match(line):
            flush_list()
            flush_paragraph()
            quote = []
            while i < len(lines) and _QUOTE_RE.match(lines[i]):
                quote.append(_QUOTE_RE.match(lines[i]).group(1))
                i += 1
            out.append('<blockquote>%s</blockquote>' % _inline(' '.join(quote)))
            continue
        ul_item = _UL_ITEM_RE.match(line)
        ol_item = _OL_ITEM_RE.match(line)
        if ul_item or ol_item:
            flush_paragraph()
            new_type = 'ul' if ul_item else 'ol'
            if list_type != new_type:
                flush_list()
                out.append('<%s>' % new_type)
                list_type = new_type
            item_text = ul_item.group(1) if ul_item else ol_item.group(2)
            out.append('<li>%s</li>' % _inline(item_text))
            i += 1
            continue
        if not line.strip():
            flush_list()
            flush_paragraph()
            i += 1
            continue
        paragraph.append(line.strip())
        i += 1
    flush_list()
    flush_paragraph()
    return '\n'.join(out)
