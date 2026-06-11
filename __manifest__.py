# -*- coding: utf-8 -*-
{
    "name": "DSL HR Portal",
    "version": "17.0.1.0.0",
    "summary": "Creative employee self-service portal for HR workflows",
    "description": """
        Employee portal for attendance, leave requests, directory, support,
        and settlement workflows on Odoo Community.
    """,
    "category": "Human Resources",
    "author": "DSL",
    "license": "LGPL-3",
    "depends": [
        "base",
        "hr",
        "hr_attendance",
        "website",
        "portal",
        "auth_signup",
        "mail",
    ],
    "data": [
        "data/ir_sequence.xml",
        "security/dsl_hr_portal_security.xml",
        "security/ir.model.access.csv",
        "views/dsl_hr_portal_views.xml",
        "views/dsl_hr_portal_user_wizard_views.xml",
        "views/hr_employee_views.xml",
        "views/dsl_hr_portal_menus.xml",
        "views/dsl_hr_portal_templates.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "dsl_hr_portal/static/src/scss/dsl_hr_portal.scss",
            "dsl_hr_portal/static/src/js/dsl_hr_portal.js",
        ],
    },
    "installable": True,
    "application": True,
}
