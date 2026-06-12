# -*- coding: utf-8 -*-

import base64
import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DslHrPayslipDocument(models.Model):
    _name = "dsl.hr.payslip.document"
    _description = "Payslip Document"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "period_year desc, period_month desc, issue_date desc, id desc"

    MONTH_SELECTION = [
        ("01", "January"),
        ("02", "February"),
        ("03", "March"),
        ("04", "April"),
        ("05", "May"),
        ("06", "June"),
        ("07", "July"),
        ("08", "August"),
        ("09", "September"),
        ("10", "October"),
        ("11", "November"),
        ("12", "December"),
    ]

    name = fields.Char(compute="_compute_name", store=True)
    employee_id = fields.Many2one("hr.employee", required=True, index=True, tracking=True)
    company_id = fields.Many2one(
        "res.company",
        related="employee_id.company_id",
        store=True,
        readonly=True,
    )
    period_month = fields.Selection(
        MONTH_SELECTION,
        required=True,
        default=lambda self: "%02d" % fields.Date.context_today(self).month,
        tracking=True,
    )
    period_year = fields.Integer(
        required=True,
        default=lambda self: fields.Date.context_today(self).year,
        tracking=True,
    )
    period_label = fields.Char(compute="_compute_period_label", store=True)
    issue_date = fields.Date(default=fields.Date.context_today, required=True, tracking=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("published", "Published"),
            ("archived", "Archived"),
        ],
        default="published",
        required=True,
        tracking=True,
    )
    pdf_file = fields.Binary(string="Payslip PDF", required=True, attachment=True)
    pdf_filename = fields.Char(string="PDF Filename")
    uploaded_by = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        readonly=True,
    )
    uploaded_on = fields.Datetime(default=fields.Datetime.now, readonly=True)
    published_on = fields.Datetime(readonly=True)
    note = fields.Text()

    @api.depends("period_month", "period_year")
    def _compute_period_label(self):
        month_names = dict(self.MONTH_SELECTION)
        for document in self:
            month = month_names.get(document.period_month, "")
            year = document.period_year or ""
            document.period_label = ("%s %s" % (month, year)).strip()

    @api.depends("employee_id.name", "period_label")
    def _compute_name(self):
        for document in self:
            employee_name = document.employee_id.name or _("Employee")
            period = document.period_label or _("Payslip")
            document.name = "%s - %s" % (employee_name, period)

    @api.constrains("period_year")
    def _check_period_year(self):
        for document in self:
            if document.period_year < 2000 or document.period_year > 2100:
                raise ValidationError(_("Payslip year must be between 2000 and 2100."))

    @api.constrains("pdf_file", "pdf_filename")
    def _check_pdf_file(self):
        for document in self:
            filename = (document.pdf_filename or "").lower()
            if filename and not filename.endswith(".pdf"):
                raise ValidationError(_("Payslip attachment must use a .pdf file name."))
            if not document.pdf_file:
                continue
            try:
                content = base64.b64decode(document.pdf_file, validate=True)
            except Exception as exc:
                raise ValidationError(_("Payslip attachment is not a valid PDF file.")) from exc
            if not content.startswith(b"%PDF"):
                raise ValidationError(_("Payslip attachment must be a PDF file."))

    @api.model_create_multi
    def create(self, vals_list):
        now = fields.Datetime.now()
        for vals in vals_list:
            if vals.get("state", "published") == "published" and not vals.get("published_on"):
                vals["published_on"] = now
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("state") == "published" and not vals.get("published_on"):
            vals = dict(vals, published_on=fields.Datetime.now())
        return super().write(vals)

    def action_publish(self):
        self.write({"state": "published"})

    def action_set_draft(self):
        self.write({"state": "draft"})

    def action_archive_document(self):
        self.write({"state": "archived"})

    def _filename_part(self, value, fallback):
        cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "").strip("._")
        return cleaned or fallback

    def _pdf_download_filename(self):
        self.ensure_one()
        employee = self._filename_part(self.employee_id.name, "employee")
        period = self._filename_part(self.period_label, "payslip")
        return "%s_Payslip_%s.pdf" % (employee, period)
