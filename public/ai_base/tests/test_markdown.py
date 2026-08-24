# -*- coding: utf-8 -*-
from odoo.tests import TransactionCase

from odoo.addons.ai_base.tools import markdown_to_html


class TestMarkdownToHtml(TransactionCase):
    def test_escapes_html(self):
        out = markdown_to_html('<script>alert(1)</script>')
        self.assertNotIn('<script>', out)
        self.assertIn('&lt;script&gt;', out)

    def test_code_block(self):
        out = markdown_to_html('```python\nprint(1)\n```')
        self.assertIn('<pre><code', out)
        self.assertIn('print(1)', out)

    def test_svg_block_becomes_data_url(self):
        out = markdown_to_html('```svg\n<svg viewBox="0 0 1 1"></svg>\n```')
        self.assertIn('data:image/svg+xml;base64,', out)
        self.assertNotIn('<svg', out)

    def test_mermaid_stays_code_block(self):
        out = markdown_to_html('```mermaid\ngraph TD; A-->B;\n```')
        self.assertIn('<pre><code', out)
        self.assertIn('graph TD', out)

    def test_inline_formatting(self):
        out = markdown_to_html(
            '**bold** and `code` and [link](https://odoo.com)')
        self.assertIn('<strong>bold</strong>', out)
        self.assertIn('<code>code</code>', out)
        self.assertIn('href="https://odoo.com"', out)
        self.assertIn('rel="noopener noreferrer"', out)

    def test_unsafe_link_dropped(self):
        out = markdown_to_html('[x](javascript:alert(1))')
        self.assertNotIn('href="javascript:', out)
        self.assertNotIn('<a', out)

    def test_headings_and_lists(self):
        out = markdown_to_html('# Title\n\n- a\n- b')
        self.assertIn('<h1>Title</h1>', out)
        self.assertIn('<ul>', out)
        self.assertIn('<li>a</li>', out)

    def test_ordered_list_uses_item_text(self):
        out = markdown_to_html('1. first\n2. second')
        self.assertIn('<ol>', out)
        self.assertIn('<li>first</li>', out)
        self.assertIn('<li>second</li>', out)

    def test_table(self):
        out = markdown_to_html('| A | B |\n| --- | --- |\n| 1 | 2 |')
        self.assertIn('<table>', out)
        self.assertIn('<th>A</th>', out)
        self.assertIn('<td>1</td>', out)

    def test_source_citation(self):
        out = markdown_to_html('See [SOURCE:42]')
        self.assertIn('<sup>[42]</sup>', out)
        self.assertNotIn('[SOURCE:42]', out)
