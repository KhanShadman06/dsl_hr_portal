# -*- coding: utf-8 -*-

import base64
import json
from datetime import datetime

import pytz

from odoo import fields, http
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.http import request


class DslHrPortal(CustomerPortal):
    def _get_employee_record(self):
        Employee = request.env["hr.employee"].sudo()
        user = request.env.user
        partner = user.partner_id

        if "user_id" in Employee._fields:
            employee = Employee.search([("user_id", "=", user.id)], limit=1)
            if employee:
                return employee

        if "work_contact_id" in Employee._fields and partner:
            employee = Employee.search([("work_contact_id", "=", partner.id)], limit=1)
            if employee:
                return employee

        if "address_home_id" in Employee._fields and partner:
            employee = Employee.search([("address_home_id", "=", partner.id)], limit=1)
            if employee:
                return employee

        return Employee.browse()

    def _require_employee(self):
        employee = self._get_employee_record()
        if not employee:
            return request.redirect("/dsl/no-employee")
        return employee

    def _base_values(self, page_name, employee=None):
        employee = employee or self._get_employee_record()
        return {
            "page_name": page_name,
            "employee": employee,
            "employee_name": employee.name if employee else request.env.user.name,
        }

    def _parse_local_datetime(self, date_value, time_value):
        local_date = fields.Date.from_string(date_value)
        local_time = datetime.strptime(time_value, "%H:%M").time()
        local_dt = datetime.combine(local_date, local_time)
        tz = pytz.timezone(request.env.user.tz or "UTC")
        localized = tz.localize(local_dt)
        utc_dt = localized.astimezone(pytz.UTC).replace(tzinfo=None)
        return fields.Datetime.to_string(utc_dt)

    def _json_response(self, payload, status=200):
        if hasattr(request, "make_json_response"):
            return request.make_json_response(payload, status=status)
        return request.make_response(
            json.dumps(payload),
            headers=[("Content-Type", "application/json")],
            status=status,
        )

    def _attendance_location_values(self, Attendance, prefix, latitude, longitude):
        vals = {}
        field_map = {
            f"{prefix}_latitude": latitude,
            f"{prefix}_longitude": longitude,
            f"{prefix}_ip_address": request.httprequest.remote_addr,
        }
        for field_name, value in field_map.items():
            if field_name in Attendance._fields:
                vals[field_name] = value
        return vals

    def _get_open_attendance(self, employee):
        Attendance = request.env["hr.attendance"].sudo()
        return Attendance.search(
            [("employee_id", "=", employee.id), ("check_out", "=", False)],
            limit=1,
            order="check_in desc",
        )

    def _attendance_values(self, employee):
        Attendance = request.env["hr.attendance"].sudo()
        open_attendance = self._get_open_attendance(employee)
        records = Attendance.search(
            [("employee_id", "=", employee.id)],
            limit=10,
            order="check_in desc",
        )
        return {
            "open_attendance": open_attendance,
            "attendance_records": records,
        }

    def _request_records(self, model_name, employee, limit=20):
        return request.env[model_name].sudo().search(
            [("employee_id", "=", employee.id)],
            limit=limit,
            order="submitted_on desc, id desc",
        )

    @http.route("/dsl/login", type="http", auth="public", website=True)
    def dsl_login(self, **kw):
        if not request.env.user._is_public():
            return request.redirect("/dsl/dashboard")
        return request.render(
            "dsl_hr_portal.dsl_login_page",
            {
                "redirect": kw.get("redirect") or "/dsl/dashboard",
            },
        )

    @http.route("/dsl/no-employee", type="http", auth="user", website=True)
    def dsl_no_employee(self, **kw):
        return request.render(
            "dsl_hr_portal.dsl_no_employee_page",
            self._base_values("no_employee"),
        )

    @http.route(["/dsl", "/dsl/dashboard"], type="http", auth="user", website=True)
    def dsl_dashboard(self, **kw):
        employee = self._require_employee()
        if not getattr(employee, "id", False):
            return employee

        attendance_data = self._attendance_values(employee)
        values = self._base_values("dashboard", employee)
        values.update(
            {
                "open_attendance": attendance_data["open_attendance"],
                "recent_attendance": attendance_data["attendance_records"][:4],
                "leave_requests": self._request_records("dsl.hr.leave.request", employee, 5),
                "attendance_requests": self._request_records(
                    "dsl.hr.attendance.request", employee, 5
                ),
                "support_tickets": self._request_records("dsl.hr.support.ticket", employee, 5),
                "settlement_requests": self._request_records(
                    "dsl.hr.settlement.request", employee, 3
                ),
            }
        )
        return request.render("dsl_hr_portal.dsl_dashboard_page", values)

    @http.route("/dsl/attendance", type="http", auth="user", website=True)
    def dsl_attendance(self, **kw):
        employee = self._require_employee()
        if not getattr(employee, "id", False):
            return employee
        values = self._base_values("attendance", employee)
        values.update(self._attendance_values(employee))
        values["manual_requests"] = self._request_records(
            "dsl.hr.attendance.request", employee
        )
        return request.render("dsl_hr_portal.dsl_attendance_page", values)

    @http.route(
        "/dsl/attendance/punch",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def dsl_attendance_punch(self, **post):
        employee = self._get_employee_record()
        if not employee:
            return self._json_response({"ok": False, "message": "Employee record missing."}, 403)

        action = post.get("action")
        latitude = post.get("latitude")
        longitude = post.get("longitude")
        if not latitude or not longitude:
            return self._json_response(
                {"ok": False, "message": "Location permission is required."}, 400
            )

        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            return self._json_response({"ok": False, "message": "Invalid location."}, 400)

        Attendance = request.env["hr.attendance"].sudo()
        now = fields.Datetime.now()
        open_attendance = self._get_open_attendance(employee)

        if action == "clock_in":
            if open_attendance:
                return self._json_response(
                    {"ok": False, "message": "You are already clocked in."}, 400
                )
            vals = {
                "employee_id": employee.id,
                "check_in": now,
            }
            vals.update(self._attendance_location_values(Attendance, "in", latitude, longitude))
            Attendance.create(vals)
            return self._json_response({"ok": True, "message": "Check in recorded."})

        if action == "clock_out":
            if not open_attendance:
                return self._json_response(
                    {"ok": False, "message": "No open attendance found."}, 400
                )
            vals = {"check_out": now}
            vals.update(self._attendance_location_values(Attendance, "out", latitude, longitude))
            open_attendance.write(vals)
            return self._json_response({"ok": True, "message": "Check out recorded."})

        return self._json_response({"ok": False, "message": "Invalid attendance action."}, 400)

    @http.route(
        "/dsl/attendance/manual",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def dsl_attendance_manual(self, **post):
        employee = self._require_employee()
        if not getattr(employee, "id", False):
            return employee
        try:
            request_date = fields.Date.from_string(post.get("request_date"))
            check_in = self._parse_local_datetime(
                post.get("request_date"), post.get("check_in_time")
            )
            check_out = self._parse_local_datetime(
                post.get("request_date"), post.get("check_out_time")
            )
            request.env["dsl.hr.attendance.request"].sudo().create(
                {
                    "employee_id": employee.id,
                    "request_date": request_date,
                    "check_in": check_in,
                    "check_out": check_out,
                    "justification": post.get("justification"),
                }
            )
        except Exception:
            return request.redirect("/dsl/attendance?error=manual")
        return request.redirect("/dsl/attendance?submitted=manual")

    @http.route("/dsl/leave", type="http", auth="user", website=True)
    def dsl_leave(self, **kw):
        employee = self._require_employee()
        if not getattr(employee, "id", False):
            return employee
        values = self._base_values("leave", employee)
        values["leave_requests"] = self._request_records("dsl.hr.leave.request", employee)
        return request.render("dsl_hr_portal.dsl_leave_page", values)

    @http.route(
        "/dsl/leave/request",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def dsl_leave_request(self, **post):
        employee = self._require_employee()
        if not getattr(employee, "id", False):
            return employee
        try:
            leave = request.env["dsl.hr.leave.request"].sudo().create(
                {
                    "employee_id": employee.id,
                    "leave_type": post.get("leave_type"),
                    "date_from": post.get("date_from"),
                    "date_to": post.get("date_to"),
                    "reason": post.get("reason"),
                }
            )
            upload = post.get("attachment")
            if upload and hasattr(upload, "read"):
                request.env["ir.attachment"].sudo().create(
                    {
                        "name": getattr(upload, "filename", "leave_attachment"),
                        "type": "binary",
                        "datas": base64.b64encode(upload.read()),
                        "res_model": "dsl.hr.leave.request",
                        "res_id": leave.id,
                    }
                )
        except Exception:
            return request.redirect("/dsl/leave?error=request")
        return request.redirect("/dsl/leave?submitted=1")

    @http.route("/dsl/directory", type="http", auth="user", website=True)
    def dsl_directory(self, q=None, **kw):
        employee = self._require_employee()
        if not getattr(employee, "id", False):
            return employee

        Employee = request.env["hr.employee"].sudo()
        domain = []
        if "active" in Employee._fields:
            domain.append(("active", "=", True))
        if q:
            domain += [
                "|",
                "|",
                ("name", "ilike", q),
                ("work_email", "ilike", q),
                ("department_id.name", "ilike", q),
            ]

        employees = Employee.search(domain, limit=80, order="name asc")
        directory_rows = []
        for item in employees:
            directory_rows.append(
                {
                    "name": item.name,
                    "employee_code": item.barcode if "barcode" in item._fields else item.id,
                    "department": item.department_id.name if item.department_id else "",
                    "job_title": item.job_id.name if item.job_id else "",
                    "work_email": item.work_email or "",
                }
            )

        values = self._base_values("directory", employee)
        values.update({"directory_rows": directory_rows, "search_query": q or ""})
        return request.render("dsl_hr_portal.dsl_directory_page", values)

    @http.route("/dsl/discuss", type="http", auth="user", website=True)
    def dsl_discuss(self, **kw):
        employee = self._require_employee()
        if not getattr(employee, "id", False):
            return employee
        values = self._base_values("discuss", employee)
        values["support_tickets"] = self._request_records("dsl.hr.support.ticket", employee, 5)
        return request.render("dsl_hr_portal.dsl_discuss_page", values)

    @http.route("/dsl/support", type="http", auth="user", website=True)
    def dsl_support(self, **kw):
        employee = self._require_employee()
        if not getattr(employee, "id", False):
            return employee
        values = self._base_values("support", employee)
        values["support_tickets"] = self._request_records("dsl.hr.support.ticket", employee)
        return request.render("dsl_hr_portal.dsl_support_page", values)

    @http.route(
        "/dsl/support/create",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def dsl_support_create(self, **post):
        employee = self._require_employee()
        if not getattr(employee, "id", False):
            return employee
        try:
            request.env["dsl.hr.support.ticket"].sudo().create(
                {
                    "employee_id": employee.id,
                    "subject": post.get("subject"),
                    "category": post.get("category") or "general",
                    "description": post.get("description"),
                }
            )
        except Exception:
            return request.redirect("/dsl/support?error=ticket")
        return request.redirect("/dsl/support?submitted=1")

    @http.route("/dsl/settlement", type="http", auth="user", website=True)
    def dsl_settlement(self, **kw):
        employee = self._require_employee()
        if not getattr(employee, "id", False):
            return employee
        values = self._base_values("settlement", employee)
        values["settlement_requests"] = self._request_records(
            "dsl.hr.settlement.request", employee
        )
        return request.render("dsl_hr_portal.dsl_settlement_page", values)

    @http.route(
        "/dsl/settlement/submit",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def dsl_settlement_submit(self, **post):
        employee = self._require_employee()
        if not getattr(employee, "id", False):
            return employee
        try:
            request.env["dsl.hr.settlement.request"].sudo().create(
                {
                    "employee_id": employee.id,
                    "last_working_day": post.get("last_working_day"),
                    "notice_acknowledged": bool(post.get("notice_acknowledged")),
                    "reason": post.get("reason"),
                }
            )
        except Exception:
            return request.redirect("/dsl/settlement?error=settlement")
        return request.redirect("/dsl/settlement?submitted=1")

    @http.route(["/my", "/my/home"], type="http", auth="user", website=True)
    def home(self, **kw):
        if self._get_employee_record():
            return request.redirect("/dsl/dashboard")
        return super().home(**kw)
