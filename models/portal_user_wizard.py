# -*- coding: utf-8 -*-

from odoo import _, fields, models
from odoo.exceptions import UserError


class DslHrPortalUserWizard(models.TransientModel):
    _name = "dsl.hr.portal.user.wizard"
    _description = "Create Employee Portal User"

    name = fields.Char(required=True)
    work_email = fields.Char(required=True)
    department_id = fields.Many2one("hr.department")
    job_id = fields.Many2one("hr.job")
    parent_id = fields.Many2one("hr.employee", string="Manager")
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        required=True,
    )

    def action_create_employee_portal_user(self):
        self.ensure_one()
        login = self.work_email.strip().lower()
        existing_user = self.env["res.users"].sudo().search([("login", "=", login)], limit=1)
        internal_group = self.env.ref("base.group_user")
        if existing_user and internal_group in existing_user.groups_id:
            raise UserError(_("A backend user already exists with this email."))

        employee = self.env["hr.employee"].sudo().create(
            {
                "name": self.name,
                "work_email": login,
                "department_id": self.department_id.id,
                "job_id": self.job_id.id,
                "parent_id": self.parent_id.id,
                "company_id": self.company_id.id,
            }
        )
        employee._dsl_create_or_get_portal_user()

        return {
            "type": "ir.actions.act_window",
            "name": _("Employee"),
            "res_model": "hr.employee",
            "res_id": employee.id,
            "view_mode": "form",
            "target": "current",
        }
