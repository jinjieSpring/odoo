# -*- coding: utf-8 -*-
"""Shared AI channel operator service.

Answers new user messages inside any linked ``discuss.channel`` (regular
channels created by Open in Discuss, Livechat channels and groups) using the
linked AI agent. The service runs from cron so it always has a valid
environment; it never streams and posts replies as the bot partner.

Both extension modules reuse it: ``lia_livechat`` ensures every Livechat
channel of the AI operator has a link, ``lia_discuss`` creates the link when
the user opens a conversation in Discuss.
"""

import logging

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.tools import html2plaintext

from odoo.addons.hdai_base.models.llm_service import LLMError, LLMService
from odoo.addons.hdai_base.models.hdai_format import markdown_to_html

_logger = logging.getLogger(__name__)


class HdaiChannelOperator(models.AbstractModel):
    _name = 'hdai.channel.operator'
    _description = 'AI Channel Operator'

    @api.model
    def _bot_partner(self):
        partner = self.env.ref(
            'hdai.bot_partner', raise_if_not_found=False)
        if not partner:
            partner = self.env.ref(
                'hdai_livechat.bot_partner', raise_if_not_found=False)
        return partner or self.env['res.partner']

    @api.model
    def _bot_user(self):
        user = self.env.ref('hdai.bot_user', raise_if_not_found=False)
        if not user:
            user = self.env.ref(
                'hdai_livechat.bot_user', raise_if_not_found=False)
        return user or self.env['res.users']

    @api.model
    def _ensure_link(self, channel, agent=None):
        """Return (creating it if needed) the active link of a channel."""
        bot = self._bot_partner()
        link = self.env['hdai.channel.link'].search(
            [('channel_id', '=', channel.id), ('active', '=', True)],
            limit=1)
        if not link:
            session = self.env['hdai.session'].with_user(
                self._bot_user() or self.env.user).sudo().create({
                    'user_id': (self._bot_user() or self.env.user).id,
                    'name': channel.display_name or _('Channel conversation'),
                    'agent_id': agent.id if agent else False,
                    'model_id': (
                        agent._resolve_model().id if agent else False),
                    'provider_id': (
                        agent._resolve_model().provider_id.id if agent else False),
                })
            link = self.env['hdai.channel.link'].create({
                'channel_id': channel.id,
                'session_id': session.id,
                'agent_id': agent.id if agent else False,
                'bot_partner_id': bot.id,
                'last_processed_dt': fields.Datetime.now(),
                'last_message_id': max(
                    channel.message_ids.ids or [0]),
            })
        elif agent and not link.agent_id:
            link.agent_id = agent.id
        return link

    @api.model
    def _channel_messages(self, link, bot_partner):
        """New user-originated messages of the channel since the last run."""
        messages = link.channel_id.message_ids.filtered(
            lambda m: (
                m.author_id.id != bot_partner.id
                and (not link.last_message_id
                     or m.id > link.last_message_id)
                and m.message_type != 'notification'
                and (m.body or '').strip()
            )
        )
        return messages.sorted(lambda m: (m.create_date, m.id))

    @api.model
    def _history_from_channel(self, messages, bot_partner):
        history = []
        for message in messages:
            role = 'assistant' if message.author_id.id == bot_partner.id else 'user'
            history.append({
                'role': role,
                'content': html2plaintext(message.body or ''),
            })
        return history

    @api.model
    def _reply(self, link):
        """Generate and post the reply for one link; returns an error dict or
        ``False`` on success."""
        self = self.with_user(self._bot_user() or self.env.user).sudo()
        bot = self._bot_partner()
        channel = link.channel_id
        new_messages = self._channel_messages(link, bot)
        if not new_messages:
            return False
        history = self._history_from_channel(new_messages, bot)
        agent = link.agent_id or self.env['hdai.agent']._get_default_agent()
        model = (agent._resolve_model()
                 if agent
                 else self.env['hdai.model']._get_model_for_scenario(
                     'channel'))
        if not model:
            channel.message_post(
                body=_('The AI assistant is not configured yet. Ask an '
                       'administrator to configure a model provider.'),
                author_id=bot.id, message_type='comment',
                subtype_xmlid='mail.mt_comment')
            return {'code': 'no_model'}
        max_turns = int(self.env['ir.config_parameter'].sudo().get_param(
            'hdai.channel.max_turns', '50') or 50)
        if link.turn_count >= max_turns:
            if link.turn_count == max_turns:
                channel.message_post(
                    body=_('This conversation reached its answer limit. '
                           'Start a new conversation to continue.'),
                    author_id=bot.id, message_type='comment',
                    subtype_xmlid='mail.mt_comment')
            link.write({'turn_count': link.turn_count + 1})
            return False
        options = {
            'reasoning_strength': 'none',
            'web_search': False,
            'language_mode': 'auto',
            'lang': False,
            'system_prompt': agent.system_prompt if agent else False,
        }
        try:
            reply, reasoning, usage = LLMService.chat(model, history, options)
        except LLMError as exc:
            _logger.warning('hdai channel reply failed: %s', exc)
            channel.message_post(
                body=_('I am unable to complete this request at the moment. '
                       'Please try again later.'),
                author_id=bot.id, message_type='comment',
                subtype_xmlid='mail.mt_comment')
            self.env['hdai.action.log'].create({
                'user_id': self.env.user.id,
                'channel_id': channel.id,
                'session_id': link.session_id.id,
                'action': (
                    'livechat_reply' if channel.channel_type == 'livechat'
                    else 'discuss_reply'),
                'query': '\n'.join(m['content'] for m in history[-3:]),
                'error': str(exc),
            })
            return {'code': 'model_call_failed', 'detail': str(exc)}
        reply = (reply or '').strip()
        if not reply and not reasoning:
            return False
        channel.message_post(
            body=Markup(markdown_to_html(reply or _('...'))),
            author_id=bot.id, message_type='comment',
            subtype_xmlid='mail.mt_comment')
        self.env['hdai.action.log'].create({
            'user_id': self.env.user.id,
            'channel_id': channel.id,
            'session_id': link.session_id.id,
            'action': (
                'livechat_reply' if channel.channel_type == 'livechat'
                else 'discuss_reply'),
            'query': '\n'.join(m['content'] for m in history[-3:]),
            'result': reply[:500],
        })
        if link.session_id:
            self.env['hdai.message'].create([
                {
                    'session_id': link.session_id.id,
                    'role': 'assistant',
                    'content': reply,
                    'reasoning_content': reasoning,
                    'prompt_tokens': usage.get('prompt_tokens', 0),
                    'completion_tokens': usage.get('completion_tokens', 0),
                    'total_tokens': usage.get('total_tokens', 0),
                },
            ])
        link.write({
            'last_processed_dt': fields.Datetime.now(),
            'last_message_id': max(channel.message_ids.ids or [0]),
            'turn_count': link.turn_count + 1,
        })
        return False

    @api.model
    def _process_links(self, links=None):
        links = links or self.env['hdai.channel.link'].search(
            [('active', '=', True)])
        for link in links:
            if link.state == 'running':
                continue
            link.state = 'running'
            self.env.cr.commit()
            try:
                self._reply(link)
            except Exception:  # noqa: BLE001
                _logger.exception('hdai channel operator failed for %s',
                                  link.channel_id.display_name)
            finally:
                link.state = 'idle'
                self.env.cr.commit()

    @api.model
    def _cron_reply_pending_channels(self):
        self._process_links()
        return True
