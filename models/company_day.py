# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DslHrCompanyDay(models.Model):
    _name = "dsl.hr.company.day"
    _description = "Company Holiday or Important Day"
    _order = "date_from asc, name asc"

    name = fields.Char(required=True)
    day_type = fields.Selection(
        [
            ("holiday", "Holiday"),
            ("important", "Important Day"),
        ],
        default="holiday",
        required=True,
    )
    date_from = fields.Date(required=True, default=fields.Date.context_today)
    date_to = fields.Date(required=True, default=fields.Date.context_today)
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        index=True,
        help="Leave empty to apply this day to every company.",
    )
    active = fields.Boolean(default=True)
    note = fields.Text()

    @api.constrains("date_from", "date_to")
    def _check_date_range(self):
        for day in self:
            if day.date_from and day.date_to and day.date_to < day.date_from:
                raise ValidationError(_("End date must be on or after start date."))
