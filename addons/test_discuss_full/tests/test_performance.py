# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from datetime import date
from dateutil.relativedelta import relativedelta

from odoo import Command
from odoo.tests.common import users, tagged, TransactionCase, warmup


@tagged('post_install', '-at_install')
class TestDiscussFullPerformance(TransactionCase):
    def setUp(self):
        super().setUp()
        self.users = self.env['res.users'].create([
            {
                'email': 'e.e@example.com',
                'groups_id': [Command.link(self.env.ref('base.group_user').id)],
                'login': 'emp',
                'name': 'Ernest Employee',
                'notification_type': 'inbox',
                'signature': '--\nErnest',
            },
            {'name': 'test1', 'login': 'test1', 'email': 'test1@example.com'},
            {'name': 'test2', 'login': 'test2', 'email': 'test2@example.com'},
            {'name': 'test3', 'login': 'test3'},
            {'name': 'test4', 'login': 'test4'},
            {'name': 'test5', 'login': 'test5'},
            {'name': 'test6', 'login': 'test6'},
            {'name': 'test7', 'login': 'test7'},
            {'name': 'test8', 'login': 'test8'},
            {'name': 'test9', 'login': 'test9'},
            {'name': 'test10', 'login': 'test10'},
            {'name': 'test11', 'login': 'test11'},
            {'name': 'test12', 'login': 'test12'},
            {'name': 'test13', 'login': 'test13'},
            {'name': 'test14', 'login': 'test14'},
            {'name': 'test15', 'login': 'test15'},
        ])
        self.employees = self.env['hr.employee'].create([{
            'user_id': user.id,
        } for user in self.users])
        self.leave_type = self.env['hr.leave.type'].create({
            'allocation_type': 'no',
            'name': 'Legal Leaves',
            'time_type': 'leave',
            'validity_start': False,
        })
        self.leaves = self.env['hr.leave'].create([{
            'date_from': date.today() + relativedelta(days=-2),
            'date_to': date.today() + relativedelta(days=2),
            'employee_id': employee.id,
            'holiday_status_id': self.leave_type.id,
        } for employee in self.employees])

    @users('emp')
    @warmup
    def test_init_messaging(self):
        """Test performance of `_init_messaging`."""
        channel_general = self.env.ref('mail.channel_all_employees')  # Unfortunately #general cannot be deleted. Assertions below assume data from a fresh db with demo.
        user_root = self.env.ref('base.user_root')
        # create public channels
        channel_public_1 = self.env['mail.channel'].browse(self.env['mail.channel'].channel_create(name='public 1', privacy='public')['id'])
        channel_public_1.add_members((self.users[0] + self.users[2] + self.users[3] + self.users[4] + self.users[8]).partner_id.ids)
        channel_public_2 = self.env['mail.channel'].browse(self.env['mail.channel'].channel_create(name='public 2', privacy='public')['id'])
        channel_public_2.add_members((self.users[0] + self.users[2] + self.users[4] + self.users[7] + self.users[9]).partner_id.ids)
        # create groups channels
        channel_group_1 = self.env['mail.channel'].browse(self.env['mail.channel'].channel_create(name='group 1', privacy='groups')['id'])
        channel_group_1.add_members((self.users[0] + self.users[2] + self.users[3] + self.users[6] + self.users[12]).partner_id.ids)
        channel_group_2 = self.env['mail.channel'].browse(self.env['mail.channel'].channel_create(name='group 2', privacy='groups')['id'])
        channel_group_2.add_members((self.users[0] + self.users[2] + self.users[6] + self.users[7] + self.users[13]).partner_id.ids)
        # create private channels
        channel_private_1 = self.env['mail.channel'].browse(self.env['mail.channel'].channel_create(name='private 1', privacy='private')['id'])
        channel_private_1.add_members((self.users[0] + self.users[2] + self.users[3] + self.users[5] + self.users[10]).partner_id.ids)
        channel_private_2 = self.env['mail.channel'].browse(self.env['mail.channel'].channel_create(name='private 2', privacy='private')['id'])
        channel_private_2.add_members((self.users[0] + self.users[2] + self.users[5] + self.users[7] + self.users[11]).partner_id.ids)
        # create chats
        channel_dm_1 = self.env['mail.channel'].browse(self.env['mail.channel'].channel_get((self.users[0] + self.users[14]).partner_id.ids)['id'])
        channel_dm_2 = self.env['mail.channel'].browse(self.env['mail.channel'].channel_get((self.users[0] + self.users[15]).partner_id.ids)['id'])
        channel_dm_3 = self.env['mail.channel'].browse(self.env['mail.channel'].channel_get((self.users[0] + self.users[2]).partner_id.ids)['id'])
        channel_dm_4 = self.env['mail.channel'].browse(self.env['mail.channel'].channel_get((self.users[0] + self.users[3]).partner_id.ids)['id'])
        # create livechats
        im_livechat_channel = self.env['im_livechat.channel'].sudo().create({'name': 'support', 'user_ids': [Command.link(self.users[0].id)]})
        self.users[0].im_status = 'online'  # make available for livechat (ignore leave)
        channel_livechat_1 = self.env['mail.channel'].browse(im_livechat_channel._open_livechat_mail_channel(anonymous_name='anon 1', previous_operator_id=self.users[0].partner_id.id, user_id=self.users[1].id, country_id=self.env.ref('base.in').id)['id'])
        channel_livechat_1.with_user(self.users[1]).message_post(body="test")
        channel_livechat_2 = self.env['mail.channel'].browse(im_livechat_channel.with_user(self.env.ref('base.public_user'))._open_livechat_mail_channel(anonymous_name='anon 2', previous_operator_id=self.users[0].partner_id.id, country_id=self.env.ref('base.be').id)['id'])
        channel_livechat_2.with_user(self.env.ref('base.public_user')).sudo().message_post(body="test")
        # add needaction
        self.users[0].notification_type = 'inbox'
        message = channel_public_1.message_post(body='test', message_type='comment', author_id=self.users[2].partner_id.id, partner_ids=self.users[0].partner_id.ids)
        # add star
        message.toggle_message_starred()

        self.users[0].flush()
        self.users[0].invalidate_cache()
        with self.assertQueryCount(emp=42):
            init_messaging = self.users[0]._init_messaging()

        self.assertEqual(init_messaging, {
            'needaction_inbox_counter': 1,
            'starred_counter': 1,
            'channels': [
                {
                    'channel_type': 'channel',
                    'create_uid': user_root.id,
                    'custom_channel_name': False,
                    'description': 'General announcements for all employees.',
                    'group_based_subscription': True,
                    'id': channel_general.id,
                    'is_minimized': False,
                    'is_pinned': True,
                    'last_message_id': next(res['message_id'] for res in channel_general._channel_last_message_ids()),
                    'message_needaction_counter': 0,
                    'message_unread_counter': 3,
                    'name': 'general',
                    'public': 'groups',
                    'seen_message_id': False,
                    'state': 'open',
                    'uuid': channel_general.uuid,
                },
                {
                    'channel_type': 'channel',
                    'create_uid': self.env.user.id,
                    'description': False,
                    'group_based_subscription': False,
                    'id': channel_public_1.id,
                    'is_minimized': False,
                    'last_message_id': next(res['message_id'] for res in channel_public_1._channel_last_message_ids()),
                    'message_needaction_counter': 0,
                    'message_unread_counter': 0,
                    'name': 'public 1',
                    'public': 'public',
                    'state': 'open',
                    'uuid': channel_public_1.uuid,
                },
                {
                    'channel_type': 'channel',
                    'create_uid': self.env.user.id,
                    'description': False,
                    'group_based_subscription': False,
                    'id': channel_public_2.id,
                    'is_minimized': False,
                    'last_message_id': next(res['message_id'] for res in channel_public_2._channel_last_message_ids()),
                    'message_needaction_counter': 0,
                    'message_unread_counter': 0,
                    'name': 'public 2',
                    'public': 'public',
                    'state': 'open',
                    'uuid': channel_public_2.uuid,
                },
                {
                    'channel_type': 'channel',
                    'create_uid': self.env.user.id,
                    'description': False,
                    'group_based_subscription': False,
                    'id': channel_group_1.id,
                    'is_minimized': False,
                    'last_message_id': next(res['message_id'] for res in channel_group_1._channel_last_message_ids()),
                    'message_needaction_counter': 0,
                    'message_unread_counter': 0,
                    'name': 'group 1',
                    'public': 'groups',
                    'state': 'open',
                    'uuid': channel_group_1.uuid,
                },
                {
                    'channel_type': 'channel',
                    'create_uid': self.env.user.id,
                    'description': False,
                    'group_based_subscription': False,
                    'id': channel_group_2.id,
                    'is_minimized': False,
                    'last_message_id': next(res['message_id'] for res in channel_group_2._channel_last_message_ids()),
                    'message_needaction_counter': 0,
                    'message_unread_counter': 0,
                    'name': 'group 2',
                    'public': 'groups',
                    'state': 'open',
                    'uuid': channel_group_2.uuid,
                },
                {
                    'channel_type': 'channel',
                    'create_uid': self.env.user.id,
                    'description': False,
                    'group_based_subscription': False,
                    'id': channel_private_1.id,
                    'is_minimized': False,
                    'last_message_id': next(res['message_id'] for res in channel_private_1._channel_last_message_ids()),
                    'message_needaction_counter': 0,
                    'message_unread_counter': 0,
                    'name': 'private 1',
                    'public': 'private',
                    'state': 'open',
                    'uuid': channel_private_1.uuid,
                },
                {
                    'channel_type': 'channel',
                    'create_uid': self.env.user.id,
                    'description': False,
                    'group_based_subscription': False,
                    'id': channel_private_2.id,
                    'is_minimized': False,
                    'last_message_id': next(res['message_id'] for res in channel_private_2._channel_last_message_ids()),
                    'message_needaction_counter': 0,
                    'message_unread_counter': 0,
                    'name': 'private 2',
                    'public': 'private',
                    'state': 'open',
                    'uuid': channel_private_2.uuid,
                },
                {
                    'channel_type': 'chat',
                    'create_uid': self.env.user.id,
                    'description': False,
                    'group_based_subscription': False,
                    'id': channel_dm_1.id,
                    'is_minimized': False,
                    'last_message_id': False,
                    'members': [
                        {
                            'email': 'e.e@example.com',
                            'id': self.users[0].partner_id.id,
                            'im_status': 'leave_offline',
                            'name': 'Ernest Employee',
                            'out_of_office_date_end': self.leaves.filtered(lambda l: l.employee_id.user_id == self.users[0]).date_to,
                        },
                        {
                            'email': False,
                            'id': self.users[14].partner_id.id,
                            'im_status': 'leave_offline',
                            'name': 'test14',
                            'out_of_office_date_end': self.leaves.filtered(lambda l: l.employee_id.user_id == self.users[14]).date_to,
                        },
                    ],
                    'message_needaction_counter': 0,
                    'message_unread_counter': 0,
                    'name': 'Ernest Employee, test14',
                    'public': 'private',
                    'seen_partners_info': [
                        {
                            'fetched_message_id': False,
                            'id': channel_dm_1.channel_last_seen_partner_ids.filtered(lambda p: p.partner_id == self.users[0].partner_id).id,
                            'partner_id': self.users[0].partner_id.id,
                            'seen_message_id': False,
                        },
                        {
                            'fetched_message_id': False,
                            'id': channel_dm_1.channel_last_seen_partner_ids.filtered(lambda p: p.partner_id == self.users[14].partner_id).id,
                            'partner_id': self.users[14].partner_id.id,
                            'seen_message_id': False,
                        },
                    ],
                    'state': 'open',
                    'uuid': channel_dm_1.uuid,
                },
                {
                    'channel_type': 'chat',
                    'create_uid': self.env.user.id,
                    'description': False,
                    'group_based_subscription': False,
                    'id': channel_dm_2.id,
                    'is_minimized': False,
                    'last_message_id': False,
                    'members': [
                        {
                            'email': 'e.e@example.com',
                            'id': self.users[0].partner_id.id,
                            'im_status': 'leave_offline',
                            'name': 'Ernest Employee',
                            'out_of_office_date_end': self.leaves.filtered(lambda l: l.employee_id.user_id == self.users[0]).date_to,
                        },
                        {
                            'email': False,
                            'id': self.users[15].partner_id.id,
                            'im_status': 'leave_offline',
                            'name': 'test15',
                            'out_of_office_date_end': self.leaves.filtered(lambda l: l.employee_id.user_id == self.users[15]).date_to,
                        },
                    ],
                    'message_needaction_counter': 0,
                    'message_unread_counter': 0,
                    'name': 'Ernest Employee, test15',
                    'public': 'private',
                    'seen_partners_info': [
                        {
                            'fetched_message_id': False,
                            'id': channel_dm_2.channel_last_seen_partner_ids.filtered(lambda p: p.partner_id == self.users[0].partner_id).id,
                            'partner_id': self.users[0].partner_id.id,
                            'seen_message_id': False,
                        },
                        {
                            'fetched_message_id': False,
                            'id': channel_dm_2.channel_last_seen_partner_ids.filtered(lambda p: p.partner_id == self.users[15].partner_id).id,
                            'partner_id': self.users[15].partner_id.id,
                            'seen_message_id': False,
                        },
                    ],
                    'state': 'open',
                    'uuid': channel_dm_2.uuid,
                },
                {
                    'channel_type': 'chat',
                    'create_uid': self.env.user.id,
                    'description': False,
                    'group_based_subscription': False,
                    'id': channel_dm_3.id,
                    'is_minimized': False,
                    'last_message_id': False,
                    'members': [
                        {
                            'email': 'e.e@example.com',
                            'id': self.users[0].partner_id.id,
                            'im_status': 'leave_offline',
                            'name': 'Ernest Employee',
                            'out_of_office_date_end': self.leaves.filtered(lambda l: l.employee_id.user_id == self.users[0]).date_to,
                        },
                        {
                            'email': 'test2@example.com',
                            'id': self.users[2].partner_id.id,
                            'im_status': 'leave_offline',
                            'name': 'test2',
                            'out_of_office_date_end': self.leaves.filtered(lambda l: l.employee_id.user_id == self.users[2]).date_to,
                        },
                    ],
                    'message_needaction_counter': 0,
                    'message_unread_counter': 0,
                    'name': 'Ernest Employee, test2',
                    'public': 'private',
                    'seen_partners_info': [
                        {
                            'fetched_message_id': False,
                            'id': channel_dm_3.channel_last_seen_partner_ids.filtered(lambda p: p.partner_id == self.users[0].partner_id).id,
                            'partner_id': self.users[0].partner_id.id,
                            'seen_message_id': False,
                        },
                        {
                            'fetched_message_id': False,
                            'id': channel_dm_3.channel_last_seen_partner_ids.filtered(lambda p: p.partner_id == self.users[2].partner_id).id,
                            'partner_id': self.users[2].partner_id.id,
                            'seen_message_id': False,
                        },
                    ],
                    'state': 'open',
                    'uuid': channel_dm_3.uuid,
                },
                {
                    'channel_type': 'chat',
                    'create_uid': self.env.user.id,
                    'description': False,
                    'group_based_subscription': False,
                    'id': channel_dm_4.id,
                    'is_minimized': False,
                    'last_message_id': False,
                    'members': [
                        {
                            'email': 'e.e@example.com',
                            'id': self.users[0].partner_id.id,
                            'im_status': 'leave_offline',
                            'name': 'Ernest Employee',
                            'out_of_office_date_end': self.leaves.filtered(lambda l: l.employee_id.user_id == self.users[0]).date_to,
                        },
                        {
                            'email': False,
                            'id': self.users[3].partner_id.id,
                            'im_status': 'leave_offline',
                            'name': 'test3',
                            'out_of_office_date_end': self.leaves.filtered(lambda l: l.employee_id.user_id == self.users[3]).date_to,
                        },
                    ],
                    'message_needaction_counter': 0,
                    'message_unread_counter': 0,
                    'name': 'Ernest Employee, test3',
                    'public': 'private',
                    'seen_partners_info': [
                        {
                            'fetched_message_id': False,
                            'id': channel_dm_4.channel_last_seen_partner_ids.filtered(lambda p: p.partner_id == self.users[0].partner_id).id,
                            'partner_id': self.users[0].partner_id.id,
                            'seen_message_id': False,
                        },
                        {
                            'fetched_message_id': False,
                            'id': channel_dm_4.channel_last_seen_partner_ids.filtered(lambda p: p.partner_id == self.users[3].partner_id).id,
                            'partner_id': self.users[3].partner_id.id,
                            'seen_message_id': False,
                        },
                    ],
                    'state': 'open',
                    'uuid': channel_dm_4.uuid,
                },
                {
                    'channel_type': 'livechat',
                    'create_uid': self.env.user.id,
                    'description': False,
                    'group_based_subscription': False,
                    'id': channel_livechat_1.id,
                    'is_minimized': False,
                    'last_message_id': next(res['message_id'] for res in channel_livechat_1._channel_last_message_ids()),
                    'livechat_visitor': {
                        'country': False,
                        'id': self.users[1].partner_id.id,
                        'name': 'test1',
                    },
                    'members': [
                        {
                            'email': 'e.e@example.com',
                            'id': self.users[0].partner_id.id,
                            'name': 'Ernest Employee',
                            'im_status': 'leave_offline',
                            'out_of_office_date_end': self.leaves.filtered(lambda l: l.employee_id.user_id == self.users[0]).date_to,
                        },
                        {
                            'email': 'test1@example.com',
                            'id': self.users[1].partner_id.id,
                            'name': 'test1',
                            'out_of_office_date_end': False,
                        },
                    ],
                    'message_needaction_counter': 0,
                    'message_unread_counter': 0,
                    'name': 'test1 Ernest Employee',
                    'operator_pid': (self.users[0].partner_id.id, 'Ernest Employee'),
                    'public': 'private',
                    'seen_partners_info': [
                        {
                            'fetched_message_id': False,
                            'id': channel_livechat_1.channel_last_seen_partner_ids.filtered(lambda p: p.partner_id == self.users[0].partner_id).id,
                            'partner_id': self.users[0].partner_id.id,
                            'seen_message_id': False,
                        },
                        {
                            'fetched_message_id': next(res['message_id'] for res in channel_livechat_1._channel_last_message_ids()),
                            'id': channel_livechat_1.channel_last_seen_partner_ids.filtered(lambda p: p.partner_id == self.users[1].partner_id).id,
                            'partner_id': self.users[1].partner_id.id,
                            'seen_message_id': next(res['message_id'] for res in channel_livechat_1._channel_last_message_ids()),
                        },
                    ],
                    'state': 'open',
                    'uuid': channel_livechat_1.uuid,
                },
                {
                    'channel_type': 'livechat',
                    'create_uid': self.env.ref('base.public_user').id,
                    'description': False,
                    'group_based_subscription': False,
                    'id': channel_livechat_2.id,
                    'is_minimized': False,
                    'last_message_id': next(res['message_id'] for res in channel_livechat_2._channel_last_message_ids()),
                    'livechat_visitor': {
                        'country': (self.env.ref('base.be').id, 'Belgium'),
                        'id': False,
                        'name': 'anon 2',
                    },
                    'members': [
                        {
                            'email': False,
                            'id': self.env.ref('base.public_partner').id,
                            'name': 'Public user',
                            'out_of_office_date_end': False,
                        },
                        {
                            'email': 'e.e@example.com',
                            'id': self.users[0].partner_id.id,
                            'im_status': 'leave_offline',
                            'name': 'Ernest Employee',
                            'out_of_office_date_end': self.leaves.filtered(lambda l: l.employee_id.user_id == self.users[0]).date_to,
                        },
                    ],
                    'message_needaction_counter': 0,
                    'message_unread_counter': 0,
                    'name': 'anon 2 Ernest Employee',
                    'operator_pid': (self.users[0].partner_id.id, 'Ernest Employee'),
                    'public': 'private',
                    'seen_partners_info': [
                        {
                            'fetched_message_id': next(res['message_id'] for res in channel_livechat_2._channel_last_message_ids()),
                            'id': channel_livechat_2.channel_last_seen_partner_ids.filtered(lambda p: p.partner_id == self.env.ref('base.public_partner')).id,
                            'partner_id': self.env.ref('base.public_user').partner_id.id,
                            'seen_message_id': next(res['message_id'] for res in channel_livechat_2._channel_last_message_ids()),
                        },
                        {
                            'fetched_message_id': False,
                            'id': channel_livechat_2.channel_last_seen_partner_ids.filtered(lambda p: p.partner_id == self.users[0].partner_id).id,
                            'partner_id': self.users[0].partner_id.id,
                            'seen_message_id': False,
                        },
                    ],
                    'state': 'open',
                    'uuid': channel_livechat_2.uuid,
                },
            ],
            'mail_failures': [],
            'shortcodes': [
                {
                    'description': False,
                    'id': 1,
                    'source': 'hello',
                    'substitution': 'Hello. How may I help you?',
                },
                {
                    'description': False,
                    'id': 2,
                    'source': 'bye',
                    'substitution': 'Thanks for your feedback. Good bye!',
                },
            ],
            'menu_id': self.env['ir.model.data']._xmlid_to_res_id('mail.menu_root_discuss'),
            'partner_root': {
                'active': False,
                'display_name': 'OdooBot',
                'email': 'odoobot@example.com',
                'id': user_root.partner_id.id,
                'im_status': 'bot',
                'name': 'OdooBot',
                'user_id': False,
            },
            'public_partners': [{
                'active': False,
                'display_name': 'Public user',
                'email': False,
                'id': self.env.ref('base.public_partner').id,
                'im_status': 'im_partner',
                'is_internal_user': False,
                'name': 'Public user',
                'user_id': self.env.ref('base.public_user').id,
            }],
            'current_partner': {
                'active': True,
                'display_name': 'Ernest Employee',
                'email': 'e.e@example.com',
                'id': self.users[0].partner_id.id,
                'im_status': 'leave_offline',
                'is_internal_user': True,
                'name': 'Ernest Employee',
                'user_id': self.users[0].id,
            },
            'current_user_id': self.users[0].id,
        })
