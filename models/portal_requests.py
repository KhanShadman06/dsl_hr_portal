# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DslHrEmployeeRequestMixin(models.AbstractModel):
    _name = "dsl.hr.employee.request.mixin"
    _description = "DSL HR Employee Request Mixin"

    employee_id = fields.Many2one("hr.employee", required=True, index=True)
    company_id = fields.Many2one(
        "res.company",
        related="employee_id.company_id",
        store=True,
        readonly=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("submitted", "Submitted"),
            ("under_review", "Under Review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="submitted",
        required=True,
        tracking=True,
    )
    submitted_on = fields.Datetime(default=fields.Datetime.now, readonly=True)
    reviewed_by = fields.Many2one("res.users", readonly=True)
    reviewed_on = fields.Datetime(readonly=True)
    rejection_reason = fields.Text()

    def action_mark_under_review(self):
        self.write({"state": "under_review"})

    def action_reject(self):
        self.write(
            {
                "state": "rejected",
                "reviewed_by": self.env.user.id,
                "reviewed_on": fields.Datetime.now(),
            }
        )

    def _approval_values(self):
        return {
            "state": "approved",
            "reviewed_by": self.env.user.id,
            "reviewed_on": fields.Datetime.now(),
        }


class DslHrAttendanceRequest(models.Model):
    _name = "dsl.hr.attendance.request"
    _description = "Manual Attendance Request"
    _inherit = ["dsl.hr.employee.request.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "submitted_on desc, id desc"

    request_date = fields.Date(required=True, default=fields.Date.context_today)
    check_in = fields.Datetime(required=True)
    check_out = fields.Datetime(required=True)
    justification = fields.Text(required=True)
    attendance_id = fields.Many2one("hr.attendance", readonly=True)

    @api.constrains("check_in", "check_out")
    def _check_attendance_range(self):
        for request in self:
            if request.check_in and request.check_out and request.check_out <= request.check_in:
                raise ValidationError(_("Punch out must be later than punch in."))

    def action_approve(self):
        Attendance = self.env["hr.attendance"].sudo()
        for request in self:
            attendance = request.attendance_id
            if not attendance:
                attendance = Attendance.create(
                    {
                        "employee_id": request.employee_id.id,
                        "check_in": request.check_in,
                        "check_out": request.check_out,
                    }
                )
            request.write(dict(request._approval_values(), attendance_id=attendance.id))


class DslHrLeaveRequest(models.Model):
    _name = "dsl.hr.leave.request"
    _description = "Portal Leave Request"
    _inherit = ["dsl.hr.employee.request.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "submitted_on desc, id desc"

    leave_type = fields.Selection(
        [
            ("casual", "Casual"),
            ("sick", "Sick"),
            ("annual", "Annual"),
            ("unpaid", "Unpaid"),
            ("other", "Other"),
        ],
        required=True,
        tracking=True,
    )
    date_from = fields.Date(required=True)
    date_to = fields.Date(required=True)
    day_count = fields.Integer(compute="_compute_day_count", store=True)
    reason = fields.Text(required=True)
    attachment_count = fields.Integer(string="Leave Attachments", compute="_compute_attachment_count")

    @api.depends("date_from", "date_to")
    def _compute_day_count(self):
        for request in self:
            if request.date_from and request.date_to and request.date_to >= request.date_from:
                request.day_count = (request.date_to - request.date_from).days + 1
            else:
                request.day_count = 0

    def _compute_attachment_count(self):
        Attachment = self.env["ir.attachment"].sudo()
        for request in self:
            request.attachment_count = Attachment.search_count(
                [("res_model", "=", self._name), ("res_id", "=", request.id)]
            )

    @api.constrains("date_from", "date_to")
    def _check_leave_dates(self):
        for request in self:
            if request.date_from and request.date_to and request.date_to < request.date_from:
                raise ValidationError(_("End date must be on or after start date."))

    def action_approve(self):
        self.write(self._approval_values())


class DslHrSettlementRequest(models.Model):
    _name = "dsl.hr.settlement.request"
    _description = "Settlement Request"
    _inherit = ["dsl.hr.employee.request.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "submitted_on desc, id desc"

    last_working_day = fields.Date(required=True, tracking=True)
    notice_acknowledged = fields.Boolean(required=True)
    reason = fields.Text(required=True)

    @api.constrains("notice_acknowledged")
    def _check_notice_acknowledged(self):
        for request in self:
            if not request.notice_acknowledged:
                raise ValidationError(_("Notice period acknowledgement is required."))

    def action_approve(self):
        self.write(self._approval_values())


class DslHrSupportTicket(models.Model):
    _name = "dsl.hr.support.ticket"
    _description = "HR Support Ticket"
    _inherit = ["dsl.hr.employee.request.mixin", "mail.thread", "mail.activity.mixin"]
    _order = "submitted_on desc, id desc"

    name = fields.Char(default="/", readonly=True, copy=False)
    subject = fields.Char(required=True, tracking=True)
    category = fields.Selection(
        [
            ("general", "General"),
            ("attendance", "Attendance"),
            ("leave", "Leave"),
            ("documents", "Documents"),
            ("settlement", "Settlement"),
        ],
        default="general",
        required=True,
    )
    description = fields.Text(required=True)
    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"].sudo()
        for vals in vals_list:
            if not vals.get("name") or vals["name"] == "/":
                vals["name"] = sequence.next_by_code("dsl.hr.support.ticket") or "/"
        return super().create(vals_list)

    def action_approve(self):
        self.write(self._approval_values())
