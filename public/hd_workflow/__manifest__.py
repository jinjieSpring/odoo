# -*- coding: utf-8 -*-
{
    'name': '工作流引擎',
    'summary': '工作流应用,提供丰富的流程节点管理',
    'author': 'Jinjie',
    'website': '',
    'category': '公共/公共',
    'depends' : ['base', 'web', 'hr', 'mail'],
    'version': '1.0',
    'data': [
        # 'security/security_chown.xml',
        'security/security.xml',
        'security/ir.model.access.csv',
        # 'data/message.xml',
        'data/model_category.xml',
        # 'data/report_paperformat_data.xml',
        'views/res_users_views.xml',
        # 'views/todo_all_view.xml',
        'views/ir_process_view.xml',
        'views/workflow_role.xml',
        # 'views/amos_workflow_view.xml',
        'views/hd_personnel_process_record_view.xml',
        # 'views/basic_attachment_form_view.xml',
        # 'views/amos_approval_check_user_wizard.xml',
        # 'views/chown_model.xml',
        # 'wizard/ban.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'assets': {
            # 'web.assets_qweb': [
            #     'amos_workflow/static/src/xml/workflow_buttons.xml',
            #     'amos_workflow/static/src/xml/todo_menu.xml',
            # ],
            'web.assets_backend': [
                'hd_workflow/static/src/model/*.js',
                'hd_workflow/static/src/components/*/*.js',
                'hd_workflow/static/src/components/*/*.scss',
                'hd_workflow/static/src/components/*/*.xml',
                'hd_workflow/static/src/models/*.js',
                'hd_workflow/static/src/services/*.js',
                # 'amos_workflow/static/src/js/statebar_invisible.js',
                # 'amos_workflow/static/src/js/hide_edit_btn.js',
                # 'amos_workflow/static/src/js/datepicker_widget.js',
                # 'amos_workflow/static/src/js/radio_do_action.js',
                # 'amos_workflow/static/src/css/pretty-checkbox.min.css',
                # 'amos_workflow/static/src/js/todo_menu.js',
                # 'amos_workflow/static/src/js/todo_all_kanban_record.js',
                # 'amos_workflow/static/src/css/signature.css'
            ]
    },
    'license': 'LGPL-3',
}
