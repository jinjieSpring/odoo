# -*- coding: utf-8 -*-
from odoo.exceptions import UserError
from odoo.addons.ai_base.tests.common import AiBaseCase


class TestPrompt(AiBaseCase):
    def test_render_and_missing_var(self):
        template = self.env['ai.prompt.template'].create({
            'name': 'Hello',
            'code': 'test.hello',
            'user_template': 'Hello {{ name }}',
        })
        self.assertEqual(template.render({'name': 'Ada'}), 'Hello Ada')
        with self.assertRaises(UserError):
            template.render({})

    def test_render_joins_system_and_user(self):
        template = self.env['ai.prompt.template'].create({
            'name': 'Join',
            'code': 'test.join',
            'system_prompt': 'Be brief.',
            'user_template': 'Say hi to {{ name }}',
        })
        self.assertEqual(
            template.render({'name': 'Ada'}),
            'Be brief.\n\nSay hi to Ada')

    def test_render_record_fields(self):
        partner = self.env['res.partner'].create({'name': 'Acme'})
        template = self.env['ai.prompt.template'].create({
            'name': 'Rec',
            'code': 'test.record',
            'user_template': 'Partner {{ record.name }}',
        })
        self.assertEqual(template.render(record=partner), 'Partner Acme')

    def test_version_bump(self):
        template = self.env['ai.prompt.template'].create({
            'name': 'V',
            'code': 'test.version',
            'user_template': 'one',
        })
        self.assertEqual(template.version, 1)
        self.assertTrue(template.history_ids)
        template.write({'user_template': 'two'})
        self.assertEqual(template.version, 2)
        self.assertGreaterEqual(len(template.history_ids), 2)

    def test_rollback(self):
        template = self.env['ai.prompt.template'].create({
            'name': 'R',
            'code': 'test.rollback',
            'user_template': 'one',
        })
        template.write({'user_template': 'two'})
        first = template.history_ids.filtered(lambda h: h.version == 1)
        template.action_rollback(first.id)
        self.assertEqual(template.user_template, 'one')

    def test_company_isolation(self):
        other = self.env['res.company'].create({'name': 'Other Co'})
        self.env['ai.prompt.template'].create({
            'name': 'Main',
            'code': 'test.shared',
            'user_template': 'main {{ who }}',
            'company_id': self.env.company.id,
        })
        self.env['ai.prompt.template'].create({
            'name': 'Other',
            'code': 'test.shared',
            'user_template': 'other {{ who }}',
            'company_id': other.id,
        })
        found = self.env['ai.prompt.template']._get_by_code('test.shared')
        self.assertEqual(found.user_template, 'main {{ who }}')
        other_found = self.env['ai.prompt.template'].with_company(
            other)._get_by_code('test.shared', company=other)
        self.assertEqual(other_found.user_template, 'other {{ who }}')

    def test_preview_joins_both_parts(self):
        template = self.env['ai.prompt.template'].create({
            'name': 'RAG',
            'code': 'test.preview.rag',
            'system_prompt': 'Answer using sources.',
            'user_template': (
                'Q: {{ query }}\n'
                '{% for item in items %}- {{ item.content }}\n{% endfor %}'
            ),
        })
        template.action_preview()
        self.assertIn('System Prompt', template.preview_result)
        self.assertIn('Answer using sources.', template.preview_result)
        self.assertIn('User Template', template.preview_result)
        self.assertIn('Sample question', template.preview_result)
        self.assertIn('Sample knowledge excerpt.', template.preview_result)
        self.assertIn('"items"', template.preview_context)
