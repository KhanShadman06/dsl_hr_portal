# -*- coding: utf-8 -*-

from odoo import _, api, models
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    def _dsl_get_portal_partner(self):
        self.ensure_one()
        for field_name in ("work_contact_id", "address_home_id"):
            if field_name in self._fields and self[field_name]:
                return self[field_name]
        return self.env["res.partner"].create(
            {
                "name": self.name,
                "email": self.work_email,
                "company_id": self.company_id.id if self.company_id else False,
            }
        )

    def _dsl_get_portal_login(self):
        self.ensure_one()
        login = self.work_email or False
        if not login:
            raise UserError(_("Set a work email before creating portal access."))
        return login.strip().lower()

    def _dsl_assign_partner_if_possible(self, partner):
        self.ensure_one()
        if "work_contact_id" in self._fields and not self.work_contact_id:
            self.work_contact_id = partner.id
        elif "address_home_id" in self._fields and not self.address_home_id:
            self.address_home_id = partner.id

    def _dsl_create_or_get_portal_user(self):
        self.ensure_one()
        portal_group = self.env.ref("base.group_portal")
        internal_group = self.env.ref("base.group_user")
        Users = self.env["res.users"].sudo()

        if "user_id" in self._fields and self.user_id:
            if internal_group in self.user_id.groups_id:
                raise UserError(
                    _(
                        "%s is already linked to an internal user. "
                        "Portal access must use a separate portal user."
                    )
                    % self.name
                )
            self.user_id.sudo().write({"groups_id": [(4, portal_group.id)]})
            return self.user_id

        login = self._dsl_get_portal_login()
        partner = self._dsl_get_portal_partner()
        self._dsl_assign_partner_if_possible(partner)

        user = Users.search([("login", "=", login)], limit=1)
        if user:
            if internal_group in user.groups_id:
                raise UserError(
                    _(
                        "A backend user already exists with login %s. "
                        "Use a different work email for portal access."
                    )
                    % login
                )
            user.write({"partner_id": partner.id, "groups_id": [(4, portal_group.id)]})
        else:
            user = Users.create(
                {
                    "name": self.name,
                    "login": login,
                    "email": login,
                    "partner_id": partner.id,
                    "groups_id": [(6, 0, [portal_group.id])],
                    "active": True,
                }
            )

        if "user_id" in self._fields:
            self.sudo().write({"user_id": user.id})
        return user

    def action_create_dsl_portal_user(self):
        for employee in self:
            employee._dsl_create_or_get_portal_user()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Portal access ready"),
                "message": _("Portal users were created or linked for the selected employees."),
                "type": "success",
                "sticky": False,
            },
        }

    @api.model_create_multi
    def create(self, vals_list):
        employees = super().create(vals_list)
        if self.env.context.get("dsl_create_portal_user"):
            employees.action_create_dsl_portal_user()
        return employees
