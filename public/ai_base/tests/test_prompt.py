# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.addons.ai_base.tests.common import AiBaseCase


class TestPrompt(AiBaseCase):
    def test_render_and_missing_var(self):
        template = self.env['ai.prompt.template'].create({
            'name': 'Hello',
            'code': 'test.hello',
            'content': 'Hello {{ name }}',
        })
        self.assertEqual(template.render({'name': 'Ada'}), 'Hello Ada')
        with self.assertRaises(UserError):
            template.render({})

    def test_render_record_fields(self):
        partner = self.env['res.partner'].create({'name': 'Acme'})
        template = self.env['ai.prompt.template'].create({
            'name': 'Rec',
            'code': 'test.record',
            'content': 'Partner {{ record.name }}',
        })
        self.assertEqual(template.render(record=partner), 'Partner Acme')

    def test_version_bump(self):
        template = self.env['ai.prompt.template'].create({
            'name': 'V',
            'code': 'test.version',
            'content': 'one',
        })
        self.assertEqual(template.version, 1)
        self.assertTrue(template.history_ids)
        template.write({'content': 'two'})
        self.assertEqual(template.version, 2)
        self.assertGreaterEqual(len(template.history_ids), 2)

    def test_rollback(self):
        template = self.env['ai.prompt.template'].create({
            'name': 'R',
            'code': 'test.rollback',
            'content': 'one',
        })
        template.write({'content': 'two'})
        first = template.history_ids.filtered(lambda h: h.version == 1)
        template.action_rollback(first.id)
        self.assertEqual(template.content, 'one')

    def test_company_isolation(self):
        other = self.env['res.company'].create({'name': 'Other Co'})
        self.env['ai.prompt.template'].create({
            'name': 'Main',
            'code': 'test.shared',
            'content': 'main {{ who }}',
            'company_id': self.env.company.id,
        })
        self.env['ai.prompt.template'].create({
            'name': 'Other',
            'code': 'test.shared',
            'content': 'other {{ who }}',
            'company_id': other.id,
        })
        found = self.env['ai.prompt.template']._get_by_code('test.shared')
        self.assertEqual(found.content, 'main {{ who }}')
        other_found = self.env['ai.prompt.template'].with_company(
            other)._get_by_code('test.shared', company=other)
        self.assertEqual(other_found.content, 'other {{ who }}')

    def test_preview_fills_sample_items(self):
        template = self.env['ai.prompt.template'].create({
            'name': 'RAG',
            'code': 'test.preview.rag',
            'content': (
                'Q: {{ query }}\n'
                '{% for item in items %}- {{ item.content }}\n{% endfor %}'
            ),
        })
        template.action_preview()
        self.assertIn('Sample question', template.preview_result)
        self.assertIn('Sample knowledge excerpt.', template.preview_result)
        self.assertIn('"items"', template.preview_context)
