# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    dsl_manager_user_ids = fields.Many2many(
        "res.users",
        "dsl_hr_employee_manager_user_rel",
        "employee_id",
        "user_id",
        compute="_compute_dsl_manager_user_ids",
        store=True,
        recursive=True,
        string="DSL Portal Managers",
        help="Portal users that can see this employee through the manager hierarchy.",
    )

    @api.depends("parent_id", "parent_id.user_id", "parent_id.dsl_manager_user_ids")
    def _compute_dsl_manager_user_ids(self):
        for employee in self:
            manager_users = self.env["res.users"]
            if employee.parent_id:
                if employee.parent_id.user_id:
                    manager_users |= employee.parent_id.user_id
                manager_users |= employee.parent_id.dsl_manager_user_ids
            employee.dsl_manager_user_ids = [(6, 0, manager_users.ids)]

    @api.constrains("parent_id")
    def _check_dsl_manager_hierarchy(self):
        for employee in self:
            manager = employee.parent_id
            while manager:
                if manager == employee:
                    raise ValidationError("An employee cannot report to themselves.")
                manager = manager.parent_id

    def _dsl_get_hierarchy_employees(self, include_self=True):
        self.ensure_one()
        employees = self.env["hr.employee"].sudo()
        if include_self:
            employees |= self.sudo()
        if self.user_id:
            employees |= self.env["hr.employee"].sudo().search(
                [("dsl_manager_user_ids", "in", [self.user_id.id])]
            )
        return employees
