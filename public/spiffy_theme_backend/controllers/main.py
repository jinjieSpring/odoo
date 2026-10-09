# -*- coding: utf-8 -*-
# Part of Bizople Solutions Pvt. Ltd.
# Licensed under the Bizople Proprietary License v1.0.
# Copyright (C) 2026 Bizople Solutions Pvt. Ltd.

import datetime
import time
from odoo import http, fields,_,SUPERUSER_ID
from odoo.http import request
from odoo.addons.web.controllers.webmanifest import WebManifest as SpiffyWebManifest
from odoo.exceptions import AccessError,AccessDenied
from odoo.models import check_method_name
import json
import operator
import re
import mimetypes
import base64
from odoo.addons.web.controllers.export import GroupsTreeNode,ExportXlsxWriter,GroupExportXlsxWriter
from odoo.tools import pycompat,file_open
from odoo.addons.mail.tools.discuss import add_guest_to_context
from werkzeug.exceptions import NotFound
from odoo.addons.auth_totp.controllers.home import Home
from odoo.addons.web.controllers.session import Session
from collections import deque
import io
from odoo.tools import ustr, osutil
import xlsxwriter

import werkzeug.exceptions
from werkzeug.urls import url_parse
from odoo.http import content_disposition, request
from odoo.tools.safe_eval import safe_eval
from odoo.addons.web.controllers.export import ExcelExport
from odoo.exceptions import UserError

import logging
_logger = logging.getLogger(__name__)

TRUSTED_DEVICE_COOKIE = 'td_id'
TRUSTED_DEVICE_AGE = 90*86400 # 90 days expiration

# (dbname, model) -> (monotonic, report dicts). Reports rarely change.
_RIGHT_CLICK_REPORT_CACHE = {}
_RIGHT_CLICK_REPORT_TTL = 300
_RIGHT_CLICK_REPORT_CACHE_LIMIT = 128

# Fields the web client applies as classes, attributes, or CSS variables.
# Binary images are read with bin_size so the payload only says whether a
# file is set; the browser loads the pixels from /web/image.
_THEME_CONFIG_FIELDS = [
    'separator', 'tab', 'checkbox', 'radio', 'popup', 'font_size',
    'chatter_position', 'list_view_density', 'input_style',
    'top_menu_position', 'theme_style', 'shape_style', 'loader_style',
    'google_font_family', 'use_custom_drawer_color', 'drawer_color_pallet',
    'attachment_in_tree_view', 'list_view_sticky_header',
    'apply_menu_shape_style', 'vertical_background', 'apply_light_bg_img',
    'top_menu_bg_vertical', 'color_pallet', 'use_custom_colors',
    'light_primary_bg_color', 'light_primary_text_color',
    'appdrawer_custom_bg_color', 'appdrawer_custom_text_color',
    'menu_shape_bg_color', 'menu_shape_bg_color_opacity', 'show_filter_row',
    'light_bg_image', 'vertical_mini_bg_image_one', 'vertical_mini_bg_image_two',
    'vertical_mini_bg_image_three', 'top_menu_custom_bg_vertical',
]

class BackendConfigration(http.Controller):

    @http.route(['/color/pallet/'], type='jsonrpc', auth='public')
    def get_selected_pallet(self, **kw):
        config_vals = {}
        current_user = request.env.user
        app_light_bg_image = kw.get('app_light_bg_image')

        if app_light_bg_image:
            if 'data:image/' in str(app_light_bg_image):
                light_bg_file = str(app_light_bg_image).split(',')
                app_light_bg_file_mimetype = light_bg_file[0]
                app_light_bg_image = light_bg_file[1]
            else:
                light_bg_file = str(app_light_bg_image).split("'")
                app_light_bg_image = light_bg_file[1]
        else:
            app_light_bg_image = False

        vertical_app_menu_bg_image = kw.get('vertical_app_menu_bg_image')

        if vertical_app_menu_bg_image:
            if 'data:image/' in str(vertical_app_menu_bg_image):
                vertical_menu_bg_file = str(vertical_app_menu_bg_image).split(',')
                app_menu_bg_file_mimetype = vertical_menu_bg_file[0]
                vertical_app_menu_bg_image = vertical_menu_bg_file[1]
            else:
                vertical_menu_bg_file = str(vertical_app_menu_bg_image).split("'")
                vertical_app_menu_bg_image = vertical_menu_bg_file[1]
        else:
            vertical_app_menu_bg_image = False

        config_vals.update({
            'light_primary_bg_color': kw.get('light_primary_bg_color'),
            'light_primary_text_color': kw.get('light_primary_text_color'),
            'light_bg_image': app_light_bg_image,
            'apply_light_bg_img': kw.get('apply_light_bg_img'),
            'top_menu_custom_bg_vertical': vertical_app_menu_bg_image,
            'attachment_in_tree_view': kw.get('attachment_in_tree_view'),
            'separator': kw.get('selected_separator'),
            'tab': kw.get('selected_tab'),
            'checkbox': kw.get('selected_checkbox'),
            'radio': kw.get('selected_radio'),
            'popup': kw.get('selected_popup'),
            'use_custom_colors': kw.get('custom_color_pallet'),
            'color_pallet': kw.get('selected_color_pallet'),
            'appdrawer_custom_bg_color': kw.get('custom_drawer_bg'),
            'appdrawer_custom_text_color': kw.get('custom_drawer_text'),
            'menu_shape_bg_color': kw.get('menu_shape_bg'),
            'menu_shape_bg_color_opacity': kw.get('menu_shape_bg_color_opacity'),
            'use_custom_drawer_color': kw.get('custom_drawer_color_pallet'),
            'drawer_color_pallet': kw.get('selected_drawer_color_pallet'),
            'loader_style': kw.get('selected_loader'),
            # 'font_family': kw.get('selected_fonts'),
            'font_size': kw.get('selected_fontsize'),
            'top_menu_position': kw.get('selected_top_menu_position'),
            'top_menu_bg_vertical': kw.get('selected_top_menu_bg_vertical'),
            'vertical_background': kw.get('vertical_background'),
            'vertical_mini_bg_image_one': kw.get('vertical_mini_bg_image_one'),
            'vertical_mini_bg_image_two': kw.get('vertical_mini_bg_image_two'),
            'vertical_mini_bg_image_three': kw.get('vertical_mini_bg_image_three'),
            'vertical_mini_bg_image_four': kw.get('vertical_mini_bg_image_four'),
            'theme_style': kw.get('selected_theme_style'),
            'apply_menu_shape_style': kw.get('apply_menu_shape_style'),
            'shape_style': kw.get('selected_menu_shape'),
            'list_view_density': kw.get('selected_list_view_density'),
            'list_view_sticky_header': kw.get('selected_list_view_sticky_header'),
            'input_style': kw.get('selected_input_style'),
            'google_font_family': kw.get('google_font_family'),
        })

        if current_user.backend_theme_config:
            current_user.backend_theme_config.sudo().update(config_vals)
        else:
            backend_config_record = request.env['backend.config'].sudo().create(
                config_vals)
            current_user.sudo().write({
                'backend_theme_config': backend_config_record.id
            })

        return True

    @http.route(['/color/pallet/data/'], type='http', auth='public', sitemap=False)
    def selected_pallet_data(self, **kw):
        user = request.env.user
        config_vals, _can_edit = self._get_effective_backend_config()

        values = {}
        separator_selection_dict = dict(
            config_vals._fields['separator'].selection)
        tab_selection_dict = dict(config_vals._fields['tab'].selection)
        checkbox_selection_dict = dict(
            config_vals._fields['checkbox'].selection)
        radio_selection_dict = dict(config_vals._fields['radio'].selection)
        popup_selection_dict = dict(config_vals._fields['popup'].selection)
        light_bg_image = config_vals.light_bg_image
        config_fonts = config_vals.google_font_links_ids.filtered(
            lambda font: font.user_id == user and font.config_id == config_vals
        )
        values.update({
            'config_vals': config_vals,
            'config_fonts': config_fonts,
            'separator_selection_dict': separator_selection_dict,
            'tab_selection_dict': tab_selection_dict,
            'checkbox_selection_dict': checkbox_selection_dict,
            'radio_selection_dict': radio_selection_dict,
            'popup_selection_dict': popup_selection_dict,
            'app_background_image': light_bg_image,
        })

        response = request.render(
            "spiffy_theme_backend.template_backend_config_data", values)

        return response

    @http.route(['/color/pallet/data/json/'], type='jsonrpc', auth='user')
    def selected_pallet_data_json(self, **kw):
        """JSON variant of /color/pallet/data/ for the OWL theme configurator."""
        user = request.env.user
        config_vals, _can_edit = self._get_effective_backend_config()
        config_fonts = config_vals.google_font_links_ids.filtered(
            lambda font: font.user_id == user and font.config_id == config_vals
        )
        field_names = [
            'theme_style', 'top_menu_position', 'vertical_background',
            'top_menu_bg_vertical', 'apply_menu_shape_style', 'shape_style',
            'menu_shape_bg_color', 'menu_shape_bg_color_opacity',
            'list_view_density', 'input_style', 'list_view_sticky_header',
            'attachment_in_tree_view', 'tab', 'checkbox', 'radio', 'popup',
            'separator', 'use_custom_colors', 'color_pallet',
            'light_primary_bg_color', 'light_primary_text_color',
            'use_custom_drawer_color', 'drawer_color_pallet',
            'appdrawer_custom_bg_color', 'appdrawer_custom_text_color',
            'apply_light_bg_img', 'font_size', 'loader_style',
        ]
        config = {}
        for field_name in field_names:
            config[field_name] = config_vals[field_name] if config_vals else False

        def _b64(value):
            return value.decode('utf-8') if value else False

        return {
            'config_id': config_vals.id if config_vals else False,
            'config': config,
            'light_bg_image': _b64(config_vals.light_bg_image) if config_vals else False,
            'top_menu_custom_bg_vertical': _b64(config_vals.top_menu_custom_bg_vertical) if config_vals else False,
            'fonts': [{
                'id': font.id,
                'name': font.name,
                'url': font.url,
                'is_selected': font.is_selected,
            } for font in config_fonts],
        }

    @http.route('/color/pallet/reset/', type='jsonrpc', auth='user')
    def reset_backend_theme_config(self):
        # get user config record (adjust model name to yours)
        user = request.env.user.sudo()
        config = user.backend_theme_config
        if config:
            config.write({
                'use_custom_colors': False,
                'use_custom_drawer_color': False,
                'light_bg_image': config._default_app_drawer_bg_image(),
                'show_filter_row': False,
                'color_pallet': "pallet_12",
                'drawer_color_pallet': "drawer_pallet_12",
                'google_font_family': False,
                'appdrawer_custom_bg_color': "#B9375D",
                'appdrawer_custom_text_color': "#ffffff",
                'menu_shape_bg_color': "#ffffff",
                'menu_shape_bg_color_opacity': 1,
                'light_primary_bg_color': "#B9375D",
                'light_primary_text_color': "#ffffff",
                'apply_light_bg_img': False,
                'dark_primary_bg_color': "#B9375D",
                'dark_primary_text_color': "#ffffff",
                'dark_secondry_bg_color': "#242424",
                'dark_secondry_text_color': "#ffffff",
                'dark_body_bg_color': "#1d1d1d",
                'dark_body_text_color': "#ffffff",
                'separator': "separator_style_2",
                'tab': "tab_style_2",
                'checkbox': "checkbox_style_4",
                'radio': "radio_style_1",
                'popup': "popup_style_2",
                'chatter_position': "chatter_right",
                'top_menu_position': "top_menu_vertical",
                'top_menu_bg_vertical': "top_menu_vertical_bg1",
                'theme_style': "biz_theme_rounded",
                'apply_menu_shape_style': False,
                'shape_style': "biz_shape_rounded",
                'attachment_in_tree_view': False,
                'font_size': "font_medium",
                'loader_style': "loader_style_10",
                # 'font_family': "rubik",
                'list_view_density': "list_comfortable",
                'input_style': "input_bottom_border",
                'list_view_sticky_header': False,
                'vertical_background': False,
            })
        return {"status": "success"}

    def _first_admin_backend_config(self):
        """Earliest Settings user who already has a theme config."""
        admin_users = request.env['res.users'].sudo().search([
            ('group_ids', 'in', request.env.ref('base.group_system').id),
            ('backend_theme_config', '!=', False),
        ], order="id asc", limit=1)
        return admin_users, admin_users.backend_theme_config

    def _resolve_backend_config(self):
        """Config record the current user sees, plus edit flags.

        Company-level themes reuse the first Settings user's config.
        User-level themes prefer the user's own record.
        """
        company = request.env.company
        user = request.env.user
        is_admin = user.has_group('base.group_system')
        admin_users, admin_config = self._first_admin_backend_config()
        Config = request.env['backend.config'].sudo()
        if company.backend_theme_level == 'user_level':
            show_edit_mode = True
            if user.backend_theme_config:
                record_vals = user.backend_theme_config
            elif admin_config:
                record_vals = admin_config
            else:
                record_vals = Config.search([], order="id asc", limit=1)
        else:
            show_edit_mode = user.id in admin_users.ids
            record_vals = admin_config or Config.search([], order="id asc", limit=1)
        return record_vals, show_edit_mode, is_admin

    def _favorite_apps_payload(self):
        """Favorite apps with icon metadata, without icon binaries."""
        apps = request.env.user.app_ids
        if not apps:
            return False
        menu_ids = []
        for app in apps:
            if str(app.app_id).isdigit():
                menu_ids.append(int(app.app_id))
        menus = request.env['ir.ui.menu'].sudo().browse(menu_ids).exists()
        rows = menus.with_context(bin_size=True).read([
            'use_icon', 'icon_class_name', 'icon_img', 'web_icon', 'web_icon_data',
        ])
        by_id = {row['id']: row for row in rows}
        app_list = []
        for app in apps:
            if not str(app.app_id).isdigit():
                continue
            row = by_id.get(int(app.app_id))
            if not row:
                continue
            app_list.append({
                'name': app.name,
                'app_id': app.app_id,
                'app_xmlid': app.app_xmlid,
                'app_actionid': app.app_actionid,
                'line_id': app.id,
                'use_icon': row['use_icon'],
                'icon_class_name': row['icon_class_name'],
                'icon_img': bool(row['icon_img']),
                'web_icon': row['web_icon'],
                'has_web_icon_data': bool(row['web_icon_data']),
            })
        if not app_list:
            return False
        return {'app_list': app_list}

    @http.route(['/get/model/record'], type='jsonrpc', auth='public')
    def get_record_data(self, **kw):
        company = request.env.company
        user = request.env.user
        record_vals, show_edit_mode, is_admin = self._resolve_backend_config()
        record_dict = record_vals.with_context(bin_size=True).read(_THEME_CONFIG_FIELDS)
        font_links = []
        if record_vals:
            font_links = request.env['google.font.family'].sudo().search([
                ('config_id', '=', record_vals.id),
                ('is_selected', '=', True),
            ]).read(['id', 'name', 'url', 'is_selected'])

        return {
            'record_dict': record_dict,
            'darkmode': "dark_mode" if user.dark_mode else False,
            'bookmark_panel': user.bookmark_panel,
            'pinned_sidebar': "pinned" if user.vertical_sidebar_pinned else False,
            'show_edit_mode': show_edit_mode,
            'is_admin': is_admin,
            'todo_list_enable': "enable_todo_list" if user.enable_todo_list else False,
            'prevent_auto_save': "prevent_auto_save" if company.prevent_auto_save else False,
            'font_dict': font_links,
            'bookmarks': user.bookmark_ids.sudo().read(['id', 'name', 'title', 'url']),
            'favorite_apps': self._favorite_apps_payload(),
        }

    @http.route(['/get-favorite-apps'], type='jsonrpc', auth='public')
    def get_favorite_apps(self, **kw):
        return self._favorite_apps_payload()

    @http.route(['/update-user-fav-apps'], type='jsonrpc', auth='user')
    def update_favorite_apps(self, **kw):
        user_id = request.env.user
        user_id.sudo().write({
            'app_ids': [(0, 0, {
                'name': kw.get('app_name'),
                'app_id': kw.get('app_id'),
            })]
        })
        return True

    @http.route(['/remove-user-fav-apps'], type='jsonrpc', auth='user')
    def remove_favorite_apps(self, **kw):
        user_id = request.env.user

        for line in user_id.app_ids:
            if line.app_id == str(kw.get('app_id')):
                user_id.sudo().write({
                    'app_ids': [(3, line.id)]
                })
        return True

    @http.route(['/get/active/menu'], type='jsonrpc', auth='public')
    def get_active_menu_data(self, **kw):
        menu_items = []
        menu_records = request.env['ir.ui.menu'].search(
            [('parent_id', '=', False)])
        for menu in menu_records:
            menu_items.append({
                'menu_name': menu.complete_name,
                'menu_id': menu.id
            })
        return menu_items

    @http.route(['/get/appsearch/data'], type='jsonrpc', auth='public')
    def get_appsearch_data(self, menuOption=None, **kw):
        domain = [('name', 'ilike', kw.get('searchvals') or ''), ('child_id', '=', False)]
        if menuOption:
            if not str(menuOption).isdigit():
                return []
            domain.append(('parent_path', '=like', '%s/%%' % int(menuOption)))
        rows = request.env['ir.ui.menu'].search_read(
            domain, ['complete_name', 'parent_id', 'action'], order='id asc',
        )
        if menuOption:
            return [{'name': row['complete_name'], 'menu_id': row['id']} for row in rows]
        menu_items = []
        for row in rows:
            action = row.get('action') or ''
            action_id = None
            if ',' in action:
                action_part = action.split(',', 1)[1]
                if action_part.isdigit():
                    action_id = int(action_part)
            parent = row.get('parent_id')
            menu_items.append({
                'name': row['complete_name'],
                'menu_id': row['id'],
                'previous_menu_id': parent[0] if parent else False,
                'action_id': action_id,
            })
        return menu_items

    @http.route(['/get/tab/title/'], type='jsonrpc', auth='public')
    def get_tab_title(self, **kw):
        company_id = request.env.company
        new_name = company_id.tab_name
        return new_name

    @http.route(['/get/active/lang'], type='jsonrpc', auth='public')
    def get_active_lang(self, **kw):
        lang_records = request.env['res.lang'].sudo().search(
            [('active', '=', 'True')])
        lang_list = []
        for lang in lang_records:
            lang_list.append({
                'lang_name': lang.name,
                'lang_code': lang.code,
            })

        return lang_list

    @http.route(['/change/active/lang'], type='jsonrpc', auth='user')
    def biz_change_active_lang(self, **kw):
        lang = kw.get('lang')
        request.env.user.lang = lang
        request.session.context = dict(request.session.context, lang=lang)
        return True

    @http.route([
        '/report/<converter>/<reportname>',
        '/report/<converter>/<reportname>/<docids>',
    ], type='http', auth='user', website=True, readonly=True)
    def report_routes(self, reportname, docids=None, converter=None, **data):
        report = request.env['ir.actions.report']
        context = dict(request.env.context)
        if docids:
            docids = [int(i) for i in docids.split(',') if i.isdigit()]
        if data.get('options'):
            data.update(json.loads(data.pop('options')))
        if data.get('context'):
            data['context'] = json.loads(data['context'])
            context.update(data['context'])
        if converter == 'html':
            html = report.with_context(context)._render_qweb_html(reportname, docids, data=data)[0]
            return request.make_response(html)
        elif converter == 'pdf':
            if request.session.get("bg_color"):
                pdf,format = report.with_context(context)._render_qweb_pdf(reportname, docids, data=data)
                base64pdf = base64.b64encode(pdf)
                newbase64pdf = str(base64pdf).replace("b'","").replace("'","")
                return newbase64pdf
            else:
                pdf = report.with_context(context)._render_qweb_pdf(reportname, docids, data=data)[0]
                pdfhttpheaders = [('Content-Type', 'application/pdf'), ('Content-Length', len(pdf))]
                return request.make_response(pdf, headers=pdfhttpheaders)
        elif converter == 'text':
            text = report.with_context(context)._render_qweb_text(reportname, docids, data=data)[0]
            texthttpheaders = [('Content-Type', 'text/plain'), ('Content-Length', len(text))]
            return request.make_response(text, headers=texthttpheaders)
        else:
            raise werkzeug.exceptions.HTTPException(description='Converter %s not implemented.' % converter)
    
    @http.route('/text_color/label_color',type='jsonrpc',auth="user")
    def text_color_label_color(self,**kw):
        generated_file_data = ''
        if 'options' in kw:
            if 'file_generator' and 'options' in kw['options']:
                check_method_name(kw['options']['file_generator'])
                file_generator = kw['options']['file_generator']
                options = json.loads(kw['options']['options'])
                allowed_company_ids = [company_data['id'] for company_data in options.get('multi_company', [])]
                if not allowed_company_ids:
                    company_str = request.httprequest.cookies.get('cids', str(request.env.user.company_id.id))
                    allowed_company_ids = [int(str_id) for str_id in company_str.split(',')]
                report = request.env['account.report'].with_context(allowed_company_ids=allowed_company_ids).browse(options['report_id'])
                btn_report_data = report.dispatch_report_action(options, file_generator)
                pdf_report_name = btn_report_data['file_name'].split('.')[0]
                new_pdf_report_name = pdf_report_name.replace(" ","")
                base64xls = base64.b64encode(btn_report_data['file_content'])
                newbase64xls = str(base64xls).replace("b'","").replace("'","")
                generated_file_data  = {
                    'file_content':newbase64xls,
                    'file_type':'.'+str(btn_report_data['file_type']),
                    'file_name':new_pdf_report_name
                }    
            elif 'data' and 'context' in kw['options']:
                # Download pdf report 
                requestcontent = json.loads(kw['options']['data'])

                url, type_ = requestcontent[0], requestcontent[1]
                reportname = '???'
                context = kw['options']['context']

                if type_ in ['qweb-pdf', 'qweb-text']:
                    converter = 'pdf' if type_ == 'qweb-pdf' else 'text'
                    extension = '.pdf' if type_ == 'qweb-pdf' else '.txt'

                    pattern = '/report/pdf/' if type_ == 'qweb-pdf' else '/report/text/'
                    reportname = url.split(pattern)[1].split('?')[0]
                    docids = None
                    if '/' in reportname:
                        reportname, docids = reportname.split('/')
                    if docids:
                        # Generic report:
                        response = self.report_routes(reportname, docids=docids, converter=converter, context=context)
                    else:
                        # Particular report:
                        data = url_parse(url).decode_query(cls=dict)  # decoding the args represented in JSON
                        if 'context' in data:
                            context, data_context = json.loads(context or '{}'), json.loads(data.pop('context'))
                            context = json.dumps({**context, **data_context})
                        response = self.report_routes(reportname, converter=converter, context=context, **data)

                    report = request.env['ir.actions.report']._get_report_from_name(reportname)
                    file_name = report.name if report else 'Test'
                    pdf_report_name = file_name.replace(" ","")
                    filename = re.sub('[/]',"_",pdf_report_name)
                    if docids:
                        ids = [int(x) for x in docids.split(",") if x.isdigit()]
                        obj = request.env[report.model].browse(ids)
                        if report.print_report_name and not len(obj) > 1:
                            report_name = safe_eval(report.print_report_name, {'object': obj, 'time': time})
                            pdf_report_name = report_name.replace(" ","")
                            filename = re.sub('[/]',"_",pdf_report_name)
                    response.headers.add('Content-Disposition', content_disposition(filename))
                    generated_file_data = {
                        'file_content':response.data,
                        'file_type':extension,
                        'file_name':filename
                    }
                    return generated_file_data
                else:
                    return
            elif 'import_compat' in kw['options']['data']:
                # Download excel report from tree view
                params = json.loads(kw['options']['data'])
                model, fields, ids, domain, import_compat = \
                    operator.itemgetter('model', 'fields', 'ids', 'domain', 'import_compat')(params)

                try:
                    Model = request.env[model].with_context(import_compat=import_compat, **params.get('context', {}))
                except KeyError:
                    return {}
                Model.check_access('read')
                if not Model._is_an_ordinary_table():
                    fields = [field for field in fields if field['name'] != 'id']

                field_names = [f['name'] for f in fields]
                if import_compat:
                    columns_headers = field_names
                else:
                    columns_headers = [val['label'].strip() for val in fields]
                groupby = params.get('groupby')
                model_description = request.env['ir.model']._get(model).name

                # Use only the part before '/' and remove spaces to avoid mobile download issues
                model_description = request.env['ir.model']._get(model).name  # e.g., 'Lead/Opportunity'
                filename = model_description.split('/')[0].replace(' ', '')

                if not import_compat and groupby:
                    groupby_type = [Model._fields[x.split(':')[0]].type for x in groupby]
                    domain = [('id', 'in', ids)] if ids else domain
                    groups_data = Model.with_context(active_test=False).read_group(domain, ['__count'], groupby, lazy=False)

                    tree = GroupsTreeNode(Model, field_names, groupby, groupby_type)
                    for leaf in groups_data:
                        tree.insert_leaf(leaf)
                    with GroupExportXlsxWriter(fields, columns_headers, tree.count) as xlsx_writer:
                        x, y = 1, 0
                        for group_name, group in tree.children.items():
                            x, y = xlsx_writer.write_group(x, y, group_name, group)
                    base64xls = base64.b64encode(xlsx_writer.value)
                    newbase64xls = str(base64xls).replace("b'","").replace("'","")
                    
                    generated_file_data = {
                        'file_content':newbase64xls,
                        'file_type':'.xlsx',
                        'file_name':filename
                    } 
                    
                else:
                    records = Model.browse(ids) if ids else Model.search(domain, offset=0, limit=False, order=False)
                    export_data = records.export_data(field_names).get('datas', [])
                    with ExportXlsxWriter(fields, columns_headers, len(export_data)) as xlsx_writer:
                        for row_index, row in enumerate(export_data):
                            for cell_index, cell_value in enumerate(row):
                                xlsx_writer.write_cell(row_index + 1, cell_index, cell_value)
                    base64xls = base64.b64encode(xlsx_writer.value)
                    newbase64xls = str(base64xls).replace("b'","").replace("'","")
                    generated_file_data = {
                        'file_content':newbase64xls,
                        'file_type':'.xlsx',
                        'file_name':filename
                    }     
                    records = Model.browse(ids) if ids else Model.search(domain, offset=0, limit=False, order=False)
                    export_data = records.export_data(field_names).get('datas', [])
                    with ExportXlsxWriter(fields, columns_headers, len(export_data)) as xlsx_writer:
                        for row_index, row in enumerate(export_data):
                            for cell_index, cell_value in enumerate(row):
                                xlsx_writer.write_cell(row_index + 1, cell_index, cell_value)
                    base64xls = base64.b64encode(xlsx_writer.value)
                    newbase64xls = str(base64xls).replace("b'","").replace("'","")
                    generated_file_data = {
                        'file_content':newbase64xls,
                        'file_type':'.xlsx',
                        'file_name':filename
                    }       
            elif 'col_group_headers' in kw['options']['data']:
                jdata = json.loads(kw['options']['data'])
                output = io.BytesIO()
                workbook = xlsxwriter.Workbook(output, {'in_memory': True})
                worksheet = workbook.add_worksheet(jdata.get('title', 'Pivot Export'))

                header_bold = workbook.add_format({'bold': True, 'pattern': 1, 'bg_color': '#AAAAAA'})
                header_plain = workbook.add_format({'pattern': 1, 'bg_color': '#AAAAAA'})
                bold = workbook.add_format({'bold': True})

                x, y, carry = 1, 0, deque()
                for header_row in jdata.get('col_group_headers', []):
                    worksheet.write(y, 0, '', header_plain)
                    for header in header_row:
                        for j in range(header.get('width', 1)):
                            worksheet.write(y, x + j, header['title'] if j == 0 else '', header_plain)
                        x += header.get('width', 1)
                    x, y = 1, y + 1

                for measure in jdata.get('measure_headers', []):
                    worksheet.write(y, x, measure['title'], header_bold if measure.get('is_bold') else header_plain)
                    x += 1
                x, y = 0, y + 1

                for row in jdata.get('rows', []):
                    worksheet.write(y, x, (' ' * (row.get('indent', 0) * 5)) + str(row.get('title', '')), header_plain)
                    for cell in row.get('values', []):
                        x += 1
                        worksheet.write(y, x, cell.get('value', ''), bold if cell.get('is_bold') else header_plain)
                    x, y = 0, y + 1

                workbook.close()
                generated_file_data = {
                    'file_content': base64.b64encode(output.getvalue()).decode(),
                    'file_type': '.xlsx',
                    'file_name': jdata.get('title', 'Pivot_Report')
                }
        return generated_file_data   
    
    @http.route('/attach/get_data', type='jsonrpc', auth="user")
    def download_attach_data(self,**kw):
        attach_id = kw.get('id')
        data = []
        if attach_id:
            attach_obj = request.env['ir.attachment'].browse(int(attach_id))
            if attach_obj:
                attach_type = mimetypes.guess_extension(attach_obj.mimetype)
                if attach_obj.name:
                    attach_list = attach_obj.name.split('.')
                    attachname = attach_list[0]
                else:
                    attachname = ''
                newbase64pdf = str(attach_obj.datas).replace("b'","").replace("'","")
                data = {
                    'pdf_data':newbase64pdf,
                    'attach_name':attachname,
                    'attach_type':attach_type
                }
        return data
    
    @http.route("/app/attachment/upload", methods=["POST"], type="http", auth="public",csrf=False)
    @add_guest_to_context
    def mail_attachment_upload_from_app(self, ufile, thread_id, thread_model, is_pending=False, **kwargs):
        thread = request.env[thread_model].search([("id", "=", thread_id)])
        if not thread:
            raise NotFound()
        if thread_model == "discuss.channel" and not thread.allow_public_upload and not request.env.user._is_internal():
            raise AccessError(_("You are not allowed to upload attachments on this channel."))
        vals = {
            "name": ufile.filename,
            "raw": ufile.read(),
            "res_id": int(thread_id),
            "res_model": thread_model,
        }
        if is_pending and is_pending != "false":
            # Add this point, the message related to the uploaded file does
            # not exist yet, so we use those placeholder values instead.
            vals.update(
                {
                    "res_id": 0,
                    "res_model": "mail.compose.message",
                }
            )
        if request.env.user.share:
            # Only generate the access token if absolutely necessary (= not for internal user).
            vals["access_token"] = request.env["ir.attachment"]._generate_access_token()
        try:
            # sudo: ir.attachment - posting a new attachment on an accessible thread
            attachment = request.env["ir.attachment"].sudo().create(vals)
            attachment._post_add_create(**kwargs)
            attachmentData = attachment._attachment_format()[0]
            if attachment.access_token:
                attachmentData["accessToken"] = attachment.access_token
        except AccessError:
            attachmentData = {"error": _("You are not allowed to upload an attachment here.")}
        return request.make_json_response(attachmentData)

    @http.route(['/active/dark/mode'], type='jsonrpc', auth='user')
    def active_dark_mode(self, **kw):
        dark_mode = kw.get('dark_mode')
        user = request.env.user
        if dark_mode == 'on':
            user.update({
                'dark_mode': True,
            })
            dark_mode = user.dark_mode
            return dark_mode
        elif dark_mode == 'off':
            user.update({
                'dark_mode': False,
            })
            dark_mode = user.dark_mode
            return dark_mode
    
    @http.route(['/update/bookmark/panel/show'], type='jsonrpc', auth='user')
    def update_bookmark_panel_show(self, **kw):
        bookmark_panel = kw.get('bookmark_panel')
        user = request.env.user
        user.update({
            'bookmark_panel': bookmark_panel,
        })

    @http.route(['/sidebar/behavior/update'], type='jsonrpc', auth='user')
    def sidebar_behavior(self, **kw):
        user = request.env.user
        sidebar_pinned = kw.get('sidebar_pinned')
        user.update({
            'vertical_sidebar_pinned': sidebar_pinned,
        })
        return True

    @http.route(['/get/dark/mode/data'], type='jsonrpc', auth='public')
    def dark_mode_on(self, **kw):
        user = request.env.user
        dark_mode_value = user.dark_mode

        return dark_mode_value

    @http.route(['/add/bookmark/link'], type='jsonrpc', auth='user')
    def add_bookmark_link(self, **kw):
        user = request.env.user
        bookmark_ids = user.bookmark_ids.filtered(
            lambda b: b.name == kw.get('name'))
        if not bookmark_ids:
            user.sudo().write({
                'bookmark_ids': [(0, 0,  {
                    'name': kw.get('name'),
                    'url': kw.get('url'),
                    'title': kw.get('title'),
                })]
            })

        return True

    @http.route(['/update/bookmark/link'], type='jsonrpc', auth='user')
    def update_bookmark_link(self, **kw):
        bookmark = request.env['bookmark.link'].sudo().search(
            [('id', '=', kw.get('bookmark_id')), ('user_id', '=', request.env.user.id)])
        if not bookmark:
            return False
        bookmark.update({
            'name': kw.get('bookmark_name'),
            'title': kw.get('bookmark_title'),
        })
        return True

    @http.route(['/remove/bookmark/link'], type='jsonrpc', auth='user')
    def remove_bookmark_link(self, **kw):
        bookmark = request.env['bookmark.link'].sudo().search(
            [('id', '=', kw.get('bookmark_id')), ('user_id', '=', request.env.user.id)])
        if not bookmark:
            return False
        bookmark.unlink()
        return True

    @http.route(['/get/bookmark/link'], type='jsonrpc', auth='public')
    def get_bookmark_link(self, **kw):
        return request.env.user.bookmark_ids.sudo().read(['id', 'name', 'title', 'url'])

    @http.route(['/update/chatter/position'], type='jsonrpc', auth='user')
    def update_chatter_position(self, **kw):
        current_user = request.env.user
        if not kw:
            if current_user.backend_theme_config:
                # current_user.backend_theme_config.sudo().update(config_vals)
                return current_user.backend_theme_config.chatter_position
            else:
                return False
        config_vals = {}

        config_vals.update({
            'chatter_position': kw.get('chatter_position')
        })
        if current_user.backend_theme_config:
            current_user.backend_theme_config.sudo().update(config_vals)
        else:
            backend_config_record = request.env['backend.config'].sudo().create(
                config_vals)
            current_user.sudo().write({
                'backend_theme_config': backend_config_record.id
            })
        return True

    @http.route('/update/filter/row', type='jsonrpc', auth='user')
    def update_filter_row(self, **kwargs):
        current_user = request.env.user

        if not kwargs:
            return current_user.backend_theme_config.show_filter_row if current_user.backend_theme_config else False

        value = kwargs.get('show_filter_row', False)
        config_vals = {'show_filter_row': value}

        if current_user.backend_theme_config:
            current_user.backend_theme_config.sudo().write(config_vals)
        else:
            config = request.env['backend.config'].sudo().create(config_vals)
            current_user.sudo().write({'backend_theme_config': config.id})

        return True

    @http.route('/filter/relational/field/list', type='jsonrpc', auth='user')
    def filter_list(self, **kw):
        rec_model = kw.get('resModel')
        rec_field = kw.get('resField')
        search_term = kw.get('searchTerm', '').strip()

        if not rec_model or not rec_field:
            return {'error': 'Missing model or field name'}

        try:
            Model = request.env[rec_model]
        except KeyError:
            return {'error': 'Invalid model name'}
        Model.check_access('read')
        field_info = Model._fields.get(rec_field)

        if not field_info or not field_info.relational:
            return {'error': 'Invalid or non-relational field'}

        related_model = field_info.comodel_name
        RelatedModel = request.env[related_model]
        RelatedModel.check_access('read')

        # Determine a displayable field for search
        search_field = None
        if 'name' in RelatedModel._fields:
            search_field = 'name'
        elif 'display_name' in RelatedModel._fields:
            search_field = 'display_name'
        else:
            # Fallback to first char field
            for field_name, field in RelatedModel._fields.items():
                if field.type == 'char':
                    search_field = field_name
                    break

        if not search_field:
            return {'error': f"No displayable field found in model '{related_model}'"}

        # The dropdown shows 6 rows and a "search more" entry, so 7 is enough.
        limit = 7
        rec_name = RelatedModel._rec_name
        if rec_name and rec_name in RelatedModel._fields:
            pairs = RelatedModel.name_search(search_term or '', operator='ilike', limit=limit)
            records = [{'id': rec_id, 'name': label} for rec_id, label in pairs]
            search_field = rec_name
        else:
            domain = [(search_field, 'ilike', search_term)] if search_term else []
            rows = RelatedModel.search_read(domain, [search_field], limit=limit)
            records = [{'id': rec['id'], 'name': rec.get(search_field)} for rec in rows]

        return {
            'related_model': related_model,
            'search_field': search_field,
            'records': records,
        }

    @http.route('/filter/relational/field/data', type='jsonrpc', auth='user', methods=['POST'])
    def get_relational_field_data(self, resModel=None, resField=None):
        if not resModel or not resField:
            return []

        selected_ids = resField if isinstance(resField, list) else [resField]

        try:
            Model = request.env[resModel]
        except KeyError:
            return []
        Model.check_access('read')

        display_field = None
        if 'name' in Model._fields:
            display_field = 'name'
        elif 'display_name' in Model._fields:
            display_field = 'display_name'
        else:
            for field_name, field in Model._fields.items():
                if field.type == 'char':
                    display_field = field_name
                    break

        records = Model.browse(selected_ids)
        if display_field:
            return [{'id': rec.id, 'name': rec[display_field]} for rec in records]
        else:
            return [{'id': rec.id, 'name': str(rec)} for rec in records]

    @http.route('/selection/filter/list', type='jsonrpc', auth='user')
    def selection_filter_list(self, **kw):
        rec_model = kw.get('resModel')
        rec_field = kw.get('resField')
        search_term = kw.get('searchTerm', '').strip().lower()

        if not rec_model:
            return {'error': 'Missing model name'}
        if not rec_field:
            return {'error': 'Missing field name'}

        try:
            Model = request.env[rec_model]
        except KeyError:
            return {'error': 'Invalid model name'}
        Model.check_access('read')
        field_info = Model._fields.get(rec_field)
        if not field_info or field_info.type != 'selection':
            return {'error': f'Field {rec_field} is not a selection field'}

        selection_options = field_info.selection
        if callable(selection_options):
            # If selection is dynamic, call it
            selection_options = selection_options(Model)

        # Filter selection options by search_term
        if search_term:
            filtered = [
                {'value': val, 'display_name': label}
                for val, label in selection_options
                if search_term in label.lower() or search_term in val.lower()
            ]
        else:
            filtered = [{'value': val, 'display_name': label} for val, label in selection_options]

        # Limit the results to 7 for dropdown
        show_more = False
        if len(filtered) > 6:
            filtered = filtered[:6]
            show_more = True

        return {
            'records': filtered,
            'count': len(filtered),
            'show_more': show_more,
        }





    @http.route(['/get/attachment/data'], type='jsonrpc', auth='user')
    def get_attachment_data(self, **kw):
        rec_ids = [
            rec_id for rec_id in (kw.get('rec_ids') or [])
            if not isinstance(rec_id, str)
        ]
        if not kw.get('model') or not rec_ids:
            return [{}]

        rows = request.env['ir.attachment'].search_read(
            [('res_model', '=', kw.get('model')), ('res_id', 'in', rec_ids)],
            ['res_id', 'mimetype', 'name'],
        )
        grouped = {}
        for row in rows:
            grouped.setdefault(row['res_id'], []).append({
                'attachment_id': row['id'],
                'attachment_mimetype': row['mimetype'],
                'attachment_name': row['name'],
            })
        return [grouped]

    @http.route(['/get/irmenu/icondata'], type='jsonrpc', auth='user')
    def get_irmenu_icondata(self, **kw):
        menu_ids = kw.get('menu_ids') or []
        Menu = request.env['ir.ui.menu'].sudo()
        menus = Menu.browse(menu_ids).exists()
        # bin_size returns a size marker for icon_img. The client loads the
        # image itself from /web/image and only needs to know it is set.
        menu_rows = menus.with_context(bin_size=True).read([
            'use_icon', 'icon_class_name', 'icon_img',
            'spiffy_app_group_id', 'web_icon',
        ])

        icon_data_ids = []
        for row in menu_rows:
            web_icon = row.get('web_icon') or ''
            needs_icon_data = (
                web_icon
                and not row.get('icon_img')
                and not (row.get('use_icon') and row.get('icon_class_name'))
                and '/icon.svg' not in web_icon
            )
            if needs_icon_data:
                icon_data_ids.append(row['id'])
        icon_data_by_id = {}
        if icon_data_ids:
            for row in Menu.browse(icon_data_ids).read(['web_icon_data']):
                icon_data_by_id[row['id']] = row.get('web_icon_data') or False

        ungrouped_ids = [
            row['id'] for row in menu_rows if not row.get('spiffy_app_group_id')
        ]
        app_menu_list = str(ungrouped_ids) if ungrouped_ids else "[]"

        app_menu_dict = {}
        linked_group_ids = []
        seen_groups = set()
        for row in menu_rows:
            group = row.get('spiffy_app_group_id')
            if group and group[0] not in seen_groups:
                seen_groups.add(group[0])
                linked_group_ids.append(group[0])
            row['web_icon_data'] = icon_data_by_id.get(row['id']) or False
            row['app_menu_list'] = app_menu_list
            app_menu_dict[row['id']] = [row]

        groups = []
        if linked_group_ids:
            groups = request.env['spiffy.app.group'].sudo().with_context(bin_size=True).search_read(
                [('id', 'in', linked_group_ids)],
                ['name', 'sequence', 'group_menu_icon', 'group_menu_list_ids', 'use_group_icon', 'group_icon_class_name'],
                order='sequence, id',
            )
        app_menu_dict['spiffy_app_group'] = groups
        return app_menu_dict

    # TO DO LIST CONTROLLERS
    def _todo_note_dict(self, note, user):
        user_tz_offset = user.tz_offset
        user_tz_offset_time = datetime.datetime.strptime(
            user_tz_offset, '%z').utcoffset()
        today_date_with_offset = datetime.datetime.now() + user_tz_offset_time
        note_create_date = note.write_date + user_tz_offset_time
        if today_date_with_offset.strftime('%d-%b-%Y') == note_create_date.strftime('%d-%b-%Y'):
            display_date = note_create_date.strftime('%I:%M %p')
        else:
            display_date = note_create_date.strftime('%d-%b-%Y')
        return {
            'id': note.id,
            'name': note.name or '',
            'description': note.description or '',
            'note_color_pallet': note.note_color_pallet or '',
            'display_date': display_date,
        }

    @http.route(['/show/user/todo/list/data'], type='jsonrpc', auth='user')
    def show_user_todo_list_data(self, **kw):
        user = request.env.user
        notes = user.sudo().todo_list_ids
        return {
            'user_id': user.id,
            'notes': [self._todo_note_dict(note, user) for note in notes],
        }

    @http.route(['/show/user/todo/list/'], type='http', auth='public', sitemap=False)
    def show_user_todo_list(self, **kw):
        company = request.env.company
        user = request.env.user

        values = {}
        user_tz_offset = user.tz_offset
        user_tz_offset_time = datetime.datetime.strptime(user_tz_offset, '%z').utcoffset()
        today_date = datetime.datetime.now()
        today_date_with_offset = datetime.datetime.now() + user_tz_offset_time

        values.update({
            'user': user.sudo(),
            'today_date': today_date_with_offset,
            'user_tz_offset_time': user_tz_offset_time,
        })

        response = request.render("spiffy_theme_backend.to_do_list_template", values)

        return response

    @http.route(['/create/todo'], type='jsonrpc', auth='user')
    def create_todo(self, **kw):
        note_title = kw.get('note_title', None)
        note_description = kw.get('note_description', None)
        is_update = kw.get('is_update')
        note_id = kw.get('note_id', None)
        note_pallet = kw.get('note_pallet', None)

        user = request.env.user

        if note_title or note_description:
            user_tz_offset = user.tz_offset
            user_tz_offset_time = datetime.datetime.strptime(user_tz_offset, '%z')

            todo_obj = request.env['todo.list'].sudo()

            if is_update:
                todo_record = todo_obj.browse(int(note_id)).filtered(
                    lambda r: r.user_id.id == user.id)
                if not todo_record:
                    raise AccessError(_("You cannot update this note."))
                todo_record.update({
                    'name': note_title,
                    'description': note_description,
                    'note_color_pallet': note_pallet,
                })
            else:
                todo_record = todo_obj.create({
                    'user_id': user.id,
                    'name': note_title,
                    'description': note_description,
                    'note_color_pallet': note_pallet,
                })

            return self._todo_note_dict(todo_record, user)

    @http.route(['/delete/todo'], type='jsonrpc', auth='user')
    def delete_todo(self, **kw):
        note_id = kw.get('noteID', None)
        if note_id:
            todo_obj = request.env['todo.list'].sudo()
            todo_record = todo_obj.browse(int(note_id)).filtered(
                lambda r: r.user_id.id == request.env.user.id)
            if not todo_record:
                return False
            todo_record.unlink()
            return True
        else:
            return False
        
    @http.route('/theme_color/parameter_check', type='jsonrpc', auth="none")
    def ThemecolorParameterCheck(self, uid,**post):
        module_obj = request.env['ir.module.module'].sudo().search([('name','=','spiffy_theme_backend'),('state','=','installed')])
        if module_obj:
            if post.get('color_data'):
                color_data = post.get('color_data')
                color_id = post.get('color_id')
                theme_color = post.get('theme_color')
                view_obj = request.env['ir.ui.view'].sudo().search(['|',('key','=',color_data),('key','=',theme_color)])
                if view_obj:
                    view_color = view_obj.arch.find(color_id)
                    if view_color == -1:
                        return {
                            'code':201,
                            'message':'Spiffy Theme is not installed in your Odoo'
                            }
                else:
                    return {
                            'code':201,
                            'message':'Spiffy Theme is not installed in your Odoo'
                            }
        else:
            return {
                    'code':201,
                    'message':'Spiffy Theme is not installed in your Odoo'
                    }
        request.session['bg_color'] = True

        if uid == "null" and request.session.get('pre_uid'):
            uid = request.session.get('pre_uid')
            url = request.env(user=uid)['res.users'].browse(uid)._mfa_url()
            csrf_token = request.csrf_token()
            url_dict = {"code":202,"2fa_required":True,"url":url,"csrf_token":csrf_token,"redirect":"/web?"}
            return url_dict
        else:
            if 'device_token' in post and 'device_name' in post:
                device_token = post.get('device_token')
                device_name = post.get('device_name')
                session_uid = request.session.uid
                if device_token and device_name and session_uid and int(uid) == int(session_uid):
                    user_obj = request.env['mail.firebase'].sudo().search([('user_id','=',int(uid)),('token','=',device_token)])
                    if not user_obj:
                        request.env['mail.firebase'].sudo().create({'user_id':int(uid),'os':device_name,'token':device_token})
        return {'code':200, 'message':'Data match successfully'}

    @http.route('/add/google/font', type='jsonrpc', auth='user', methods=['POST'])
    def add_google_font(self, **post):
        current_user = request.env.user
        name = post.get("name")
        url = post.get("url")

        if not (name and url):
            return {"status": "error", "message": "Missing data"}

        effective_config, can_edit = self._get_effective_backend_config()
        if not can_edit:
            raise AccessError(_("You are not allowed to manage fonts for this configuration."))

        existing_font_user = request.env['google.font.family'].sudo().search([
            ('name', '=', name),
            ('user_id', '=', current_user.id),
            ('config_id', '=', effective_config.id),
        ], limit=1)

        if existing_font_user:
            request.env['google.font.family'].sudo().search([
                ('user_id', '=', current_user.id),
                ('config_id', '=', effective_config.id),
            ]).write({'is_selected': False})

            existing_font_user.write({'is_selected': True})
            return {
                "status": "duplicate",
                "id": existing_font_user.id,
                "name": existing_font_user.name,
                "url": existing_font_user.url,
            }

        existing_font_global = request.env['google.font.family'].sudo().search([
            ('name', '=', name),
            ('user_id', '!=', current_user.id)
        ], limit=1)

        user_fonts = request.env['google.font.family'].sudo().search([
            ('user_id', '=', current_user.id),
            ('config_id', '=', effective_config.id),
        ])
        if len(user_fonts) >= 5:
            return {
                "status": "limit_reached",
                "message": "Maximum 5 fonts are allowed. Please delete one before adding a new font."
            }

        user_fonts.write({'is_selected': False})

        new_font = request.env['google.font.family'].sudo().create({
            'name': name,
            'url': url if existing_font_global else url,
            'user_id': current_user.id,
            'is_selected': True,
            'config_id': effective_config.id,
        })

        # If config_id was False but backend config exists now, update it
        if not new_font.config_id and current_user.backend_theme_config:
            new_font.sudo().write({'config_id': current_user.backend_theme_config.id})
        return {
            "status": "success",
            "id": new_font.id,
            "name": new_font.name,
            "url": new_font.url,
        }

    @http.route('/delete/google/font', type='jsonrpc', auth='user', methods=['POST'])
    def delete_google_font(self, **post):
        font_id = post.get("id")
        if font_id:
            font = request.env['google.font.family'].sudo().browse(int(font_id)).filtered(
                lambda f: f.user_id.id == request.env.user.id)
            if font.exists():
                font.unlink()
                return {"status": "success"}
        return {"status": "error", "message": "Font not found"}


    def _get_effective_backend_config(self):
        """Resolve the backend.config the current user is allowed to edit.

        The record matches ``_resolve_backend_config``. A user may edit their
        own user-level config, and a Settings user may edit the shared one.
        """
        user = request.env.user
        is_admin = user.has_group('base.group_system')
        record_vals, _show_edit_mode, _is_admin = self._resolve_backend_config()
        if request.env.company.backend_theme_level == 'user_level' and user.backend_theme_config:
            return record_vals, True
        return record_vals, is_admin

    @http.route('/update_single_font_selection', type='jsonrpc', auth='user')
    def update_single_font_selection(self, font_id, backend_config_id):
        effective_config, can_edit = self._get_effective_backend_config()
        if not can_edit or backend_config_id != effective_config.id:
            raise AccessError(_("You cannot update font selection for this configuration."))
        if font_id == None:
            request.env['google.font.family'].sudo().search([
                ('config_id', '=', backend_config_id),
            ]).write({'is_selected': False})
            return {'status': 'success'}
        else:
            font = request.env['google.font.family'].sudo().browse(font_id).filtered(
                lambda f: f.config_id.id == effective_config.id)
            if font:
                request.env['google.font.family'].sudo().search([
                    ('config_id', '=', font.config_id.id),
                    ('id', '!=', font_id)
                ]).write({'is_selected': False})
                font.is_selected = True
            return {'status': 'success', 'font_id': font}

    # ── Right-Click Context Menu data endpoint ────────────────────────────────

    @http.route(['/spiffy/right_click_menu/data'], type='jsonrpc', auth='user')
    def get_right_click_menu_data(self, res_model, res_id, active_field_value=None, **kw):
        """Return access rights, archive state, and report info
        for the context menu of a given record.

        Returns ``{'enabled': False}`` when the feature is disabled globally
        or when the model is in the exclusion list.
        """
        company = request.env.company.sudo()

        # Feature toggle
        if not company.enable_right_click_menu:
            return {'enabled': False}

        # Model exclusion list
        excluded_models = company.right_click_menu_excluded_models.mapped('model')
        if res_model in excluded_models:
            return {'enabled': False}

        # Validate model exists
        if res_model not in request.env:
            return {'enabled': False}

        try:
            Model = request.env[res_model]
        except Exception:
            return {'enabled': False}

        # Access rights (non-raising)
        def _check(perm):
            try:
                Model.check_access(perm)
                return True
            except Exception:
                return False

        access = {
            'read':   _check('read'),
            'write':  _check('write'),
            'create': _check('create'),
            'unlink': _check('unlink'),
        }

        # Active field detection & current state
        has_active = 'active' in Model._fields
        is_active = True
        if has_active and res_id:
            try:
                # Use active_test=False to read archived records too
                rec = Model.with_context(active_test=False).browse(int(res_id))
                rec_data = rec.read(['active'])
                is_active = rec_data[0]['active'] if rec_data else True
            except Exception:
                is_active = True
        # Allow client to override with a fresher value it already has
        if active_field_value is not None:
            is_active = active_field_value

        reports = self._right_click_reports(res_model)
        has_report = bool(reports)

        return {
            'enabled': True,
            'access': access,
            'has_active': has_active,
            'is_active': is_active,
            'has_report': has_report,
            'reports': reports,
        }

    def _right_click_reports(self, res_model):
        """PDF reports bound to a model, reused across right-clicks."""
        key = (request.env.cr.dbname, res_model)
        now = time.monotonic()
        cached = _RIGHT_CLICK_REPORT_CACHE.get(key)
        if cached and now - cached[0] < _RIGHT_CLICK_REPORT_TTL:
            return cached[1]
        try:
            reports = request.env['ir.actions.report'].sudo().search_read(
                [
                    ('model', '=', res_model),
                    ('report_type', '=', 'qweb-pdf'),
                    ('binding_model_id', '!=', False),
                ],
                fields=['id', 'name', 'report_name'],
                order='id asc',
                limit=20,
            )
        except Exception:
            reports = []
        if len(_RIGHT_CLICK_REPORT_CACHE) >= _RIGHT_CLICK_REPORT_CACHE_LIMIT:
            _RIGHT_CLICK_REPORT_CACHE.clear()
        _RIGHT_CLICK_REPORT_CACHE[key] = (now, reports)
        return reports


class WebManifest(SpiffyWebManifest):
    def _icon_path(self):
        return 'spiffy_theme_backend/static/src/image/loader_2.gif'
    
    @http.route('/web/offline', type='http', auth='public', methods=['GET'])
    def offline(self):
        """ Returns the offline page delivered by the service worker """
        return request.render('web.webclient_offline', {
            'odoo_icon': base64.b64encode(file_open(self._icon_path(), 'rb').read())
        })
        
class AuthHome(Home):
    @http.route(
        '/web/login/totp',
        type='http', auth='public', methods=['GET', 'POST'], sitemap=False,
        website=True, multilang=False # website breaks the login layout...
    )
    def web_totp(self, redirect=None, **kwargs):
        if request.session.get('uid'):
            return request.redirect(self._login_redirect(request.session.get('uid'), redirect=redirect))

        if not request.session.get('pre_uid'):
            return request.redirect('/web/login')

        error = None

        user = request.env['res.users'].browse(request.session.get('pre_uid'))
        if user and request.httprequest.method == 'GET':
            cookies = request.httprequest.cookies
            key = cookies.get(TRUSTED_DEVICE_COOKIE)
            if key:
                user_match = request.env['auth_totp.device']._check_credentials_for_uid(
                    scope="browser", key=key, uid=user.id)
                if user_match:
                    request.session.finalize(request.env)
                    return request.redirect(self._login_redirect(request.session.get('uid'), redirect=redirect))

        elif user and request.httprequest.method == 'POST' and kwargs.get('totp_token'):
            try:
                with user._assert_can_auth(user=user.id):
                    token = int(re.sub(r'\s', '', kwargs['totp_token']))
                    credentials = {
                        'type': 'totp',
                        'token': token,
                    }
                    user._check_credentials(credentials, {'interactive': True})
            except AccessDenied as e:
                if 'tool_color_id' in kwargs:
                    error = str(e)
                    value = {'code':201,'error':error}
                    new_value  = json.dumps(value)
                    return new_value
                else:
                    error = str(e)
            except ValueError:
                if 'tool_color_id' in kwargs:
                    value = {'code':201,'error':_("Invalid authentication code format.")}
                    new_value  = json.dumps(value)
                    return new_value
                else:
                    error = _("Invalid authentication code format.")
            else:
                request.session.finalize(request.env)
                request.update_env(user=request.session.get('uid'))
                request.update_context(**request.session.context)
                response = request.redirect(self._login_redirect(request.session.get('uid'), redirect=redirect))
                if kwargs.get('remember'):
                    name = _("%(browser)s on %(platform)s",
                        browser=request.httprequest.user_agent.browser.capitalize(),
                        platform=request.httprequest.user_agent.platform.capitalize(),
                    )

                    if request.geoip.city.name:
                        name += f" ({request.geoip.city.name}, {request.geoip.country_name})"

                    key = request.env['auth_totp.device']._generate("browser", name)
                    response.set_cookie(
                        key=TRUSTED_DEVICE_COOKIE,
                        value=key,
                        max_age=TRUSTED_DEVICE_AGE,
                        httponly=True,
                        samesite='Lax'
                    )
                # Crapy workaround for unupdatable Odoo Mobile App iOS (Thanks Apple :@)
                request.session.touch()
                if 'tool_color_id' in kwargs:
                    value = {'code':200,'message':"Authentication Success","is_2fa_login":True}
                    new_value  = json.dumps(value)
                    uid = request.session.get('uid')
                    device_token = kwargs.get('device_token')
                    device_name = kwargs.get('tool_color_id')
                    if device_name and device_token:
                        user_obj = request.env['mail.firebase'].search([('user_id','=',int(uid)),('token','=',device_token)])
                        if not user_obj:
                            request.env['mail.firebase'].create({'user_id':int(uid),'os':device_name,'token':device_token})
                    return new_value
                return response

        # Crapy workaround for unupdatable Odoo Mobile App iOS (Thanks Apple :@)
        request.session.touch()
        return request.render('auth_totp.auth_totp_form', {
            'user': user,
            'error': error,
            'redirect': redirect,
        })
    
class CustomExportXlsxWriter(ExportXlsxWriter):
    def __init__(self, fields, columns_headers, row_count):
        self.fields = fields
        self.columns_headers = columns_headers
        self.output = io.BytesIO()
        self.workbook = xlsxwriter.Workbook(self.output, {'in_memory': True})
        self.header_style = self.workbook.add_format({'bold': True})
        self.date_style = self.workbook.add_format({'text_wrap': True, 'num_format': 'yyyy-mm-dd'})
        self.datetime_style = self.workbook.add_format({'text_wrap': True, 'num_format': 'yyyy-mm-dd hh:mm:ss'})
        self.base_style = self.workbook.add_format({'text_wrap': True})
        # FIXME: Should depends of the field digits
        self.float_style = self.workbook.add_format({'text_wrap': True, 'num_format': '#,##0.00'})

        # FIXME: Should depends of the currency field for each row (also maybe add the currency symbol)
        decimal_places = request.env['res.currency'].sudo()._read_group([], aggregates=['decimal_places:max'])[0][0]
        self.monetary_style = self.workbook.add_format({'text_wrap': True, 'num_format': f'#,##0.{(decimal_places or 2) * "0"}'})

        header_bold_props = {'text_wrap': True, 'bold': True, 'bg_color': '#e9ecef'}
        self.header_bold_style = self.workbook.add_format(header_bold_props)
        self.header_bold_style_float = self.workbook.add_format(dict(**header_bold_props, num_format='#,##0.00'))
        self.header_bold_style_monetary = self.workbook.add_format(dict(**header_bold_props, num_format=f'#,##0.{(decimal_places or 2) * "0"}'))

        self.worksheet = self.workbook.add_worksheet()
        self.value = False

        if row_count > self.worksheet.xls_rowmax:
            raise UserError(request.env._('There are too many rows (%(count)s rows, limit: %(limit)s) to export as Excel 2007-2013 (.xlsx) format. Consider splitting the export.', count=row_count, limit=self.worksheet.xls_rowmax))
        
ExportXlsxWriter.__init__ = CustomExportXlsxWriter.__init__
