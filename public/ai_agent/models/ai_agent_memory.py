# -*- coding: utf-8 -*-
from odoo import api, fields, models

_MAX_MEMORY_CHARS = 800


class AiAgentMemory(models.Model):
    _name = 'ai.agent.memory'
    _description = 'AI Agent Memory'
    _order = 'write_date desc, id desc'
    _check_company_auto = True

    agent_id = fields.Many2one(
        'ai.agent', string='Agent', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one(
        'res.users', string='User', required=True, ondelete='cascade',
        index=True, default=lambda self: self.env.user)
    company_id = fields.Many2one(
        'res.company', string='Company', index=True,
        default=lambda self: self.env.company)
    content = fields.Text(string='Content', required=True)

    @api.model
    def _search_for(self, agent, user=None, company=None, limit=None):
        if not agent:
            return self.browse()
        user = user or self.env.user
        company = company if company is not None else self.env.company
        limit = limit if limit is not None else (agent.memory_limit or 20)
        return self.search([
            ('agent_id', '=', agent.id),
            ('user_id', '=', user.id),
            '|', ('company_id', '=', False),
            ('company_id', '=', company.id),
        ], order='write_date desc, id desc', limit=max(0, limit))

    @api.model
    def _prompt_text(self, agent, user=None, company=None):
        memories = self._search_for(agent, user=user, company=company)
        if not memories:
            return ''
        lines = [self.env._('Agent memory (most recent last):')]
        for memory in reversed(memories):
            text = (memory.content or '').strip()
            if text:
                lines.append('- %s' % text)
        return '\n'.join(lines) if len(lines) > 1 else ''

    @api.model
    def _remember(self, agent, content, user=None, company=None):
        if not agent or not agent.memory_enabled:
            return self.browse()
        text = ' '.join((content or '').split())
        if not text:
            return self.browse()
        user = user or self.env.user
        company = company if company is not None else self.env.company
        record = self.create({
            'agent_id': agent.id,
            'user_id': user.id,
            'company_id': company.id if company else False,
            'content': text[:_MAX_MEMORY_CHARS],
        })
        self.env['ai.audit.log']._record(
            'memory_write',
            agent_id=agent.id,
            status='success',
            input_summary=text[:_MAX_MEMORY_CHARS],
        )
        keep = max(1, agent.memory_limit or 20)
        extra = self.search([
            ('agent_id', '=', agent.id),
            ('user_id', '=', user.id),
            '|', ('company_id', '=', False),
            ('company_id', '=', company.id if company else False),
        ], order='write_date desc, id desc', offset=keep)
        if extra:
            extra.unlink()
        return record

    @api.model
    def _remember_from_turn(self, agent, user_text, reply, user=None, company=None):
        if not agent or not agent.memory_enabled:
            return self.browse()
        blob = '\n'.join(part for part in (
            (user_text or '').strip(),
            (reply or '').strip(),
        ) if part)
        if not blob:
            return self.browse()
        summary = self._summarize(blob)
        return self._remember(agent, summary, user=user, company=company)

    @api.model
    def _summarize(self, blob):
        snippet = (blob or '')[:2000]
        try:
            result = self.env['ai.agent.service'].chat(
                'Summarize the following exchange in at most two sentences '
                'for later agent memory. Keep concrete facts, drop greetings.\n\n%s'
                % snippet,
                session=None,
                options={'max_tokens': 120, 'skip_memory': True},
                scenario='summary',
            )
            text = (result.get('reply') or '').strip()
            if text:
                return text[:_MAX_MEMORY_CHARS]
        except Exception:  # noqa: BLE001
            pass
        return snippet[:_MAX_MEMORY_CHARS]
