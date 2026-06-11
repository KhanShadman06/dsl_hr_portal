# -*- coding: utf-8 -*-

import base64
import json
from datetime import datetime, time

import pytz

from odoo import fields, http
from odoo.exceptions import ValidationError
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.http import request


class DslHrPortal(CustomerPortal):
    def _is_hr_user(self):
        return request.env.user.has_group("hr.group_hr_user")

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

    def _employee_domain(self):
        Employee = request.env["hr.employee"].sudo()
        domain = []
        if "active" in Employee._fields:
            domain.append(("active", "=", True))
        return domain

    def _active_employees(self):
        return request.env["hr.employee"].sudo().search(self._employee_domain(), order="name asc")

    def _visible_employees(self, employee, include_self=True):
        if not employee:
            return request.env["hr.employee"].sudo().browse()
        if "dsl_manager_user_ids" not in request.env["hr.employee"]._fields:
            return employee.sudo()
        return employee._dsl_get_hierarchy_employees(include_self=include_self)

    def _overview_employees(self, employee):
        if self._is_hr_user():
            return self._active_employees()
        if employee:
            return self._visible_employees(employee, include_self=False)
        return request.env["hr.employee"].sudo().browse()

    def _base_values(self, page_name, employee=None):
        if employee is None:
            employee = self._get_employee_record()
        team_employees = self._visible_employees(employee, include_self=False) if employee else employee
        is_hr_user = self._is_hr_user()
        return {
            "page_name": page_name,
            "employee": employee,
            "employee_name": employee.name if employee else request.env.user.name,
            "has_employee": bool(employee),
            "has_team": bool(team_employees),
            "team_count": len(team_employees) if team_employees else 0,
            "is_hr_user": is_hr_user,
            "has_attendance_overview": is_hr_user or bool(team_employees),
        }

    def _today_bounds(self):
        today = fields.Date.context_today(request.env.user)
        tz = pytz.timezone(request.env.user.tz or "UTC")
        start = tz.localize(datetime.combine(today, time.min)).astimezone(pytz.UTC).replace(tzinfo=None)
        end = tz.localize(datetime.combine(today, time.max)).astimezone(pytz.UTC).replace(tzinfo=None)
        return today, start, end

    def _company_day_records(self, date_from=None, date_to=None, company_ids=None, limit=None):
        CompanyDay = request.env["dsl.hr.company.day"].sudo()
        domain = [("active", "=", True)]
        if date_from and date_to:
            domain += [("date_from", "<=", date_to), ("date_to", ">=", date_from)]
        elif date_from:
            domain.append(("date_to", ">=", date_from))

        if company_ids is not None:
            company_ids = [company_id for company_id in company_ids if company_id]
            if company_ids:
                domain += ["|", ("company_id", "=", False), ("company_id", "in", company_ids)]
            else:
                domain.append(("company_id", "=", False))

        return CompanyDay.search(domain, limit=limit, order="date_from asc, name asc")

    def _upcoming_company_days(self, employees=None, employee=None, limit=8):
        today = fields.Date.context_today(request.env.user)
        company_ids = []
        if employees:
            company_ids = employees.mapped("company_id").ids
        elif employee and employee.company_id:
            company_ids = employee.company_id.ids
        elif request.env.company:
            company_ids = request.env.company.ids
        return self._company_day_records(date_from=today, company_ids=company_ids, limit=limit)

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
        if not employee:
            return {
                "open_attendance": request.env["hr.attendance"].sudo().browse(),
                "attendance_records": request.env["hr.attendance"].sudo().browse(),
            }
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

    def _attendance_overview(self, employees):
        employees = employees.sudo() if employees else request.env["hr.employee"].sudo().browse()
        empty = {
            "date": fields.Date.context_today(request.env.user),
            "total_count": 0,
            "present_count": 0,
            "checked_out_count": 0,
            "attended_count": 0,
            "leave_count": 0,
            "holiday_count": 0,
            "absent_count": 0,
            "present_rows": [],
            "checked_out_rows": [],
            "leave_rows": [],
            "holiday_rows": [],
            "absent_rows": [],
            "overview_rows": [],
            "company_days": request.env["dsl.hr.company.day"].sudo().browse(),
        }
        if not employees:
            return empty

        today, start, end = self._today_bounds()
        Attendance = request.env["hr.attendance"].sudo()
        attendances = Attendance.search(
            [
                ("employee_id", "in", employees.ids),
                ("check_in", "<=", end),
                "|",
                ("check_out", "=", False),
                ("check_out", ">=", start),
            ],
            order="check_in desc",
        )
        open_ids = set()
        attended_ids = set()
        last_attendance = {}
        for attendance in attendances:
            employee_id = attendance.employee_id.id
            attended_ids.add(employee_id)
            last_attendance.setdefault(employee_id, attendance)
            if not attendance.check_out:
                open_ids.add(employee_id)

        Leave = request.env["dsl.hr.leave.request"].sudo()
        approved_leaves = Leave.search(
            [
                ("employee_id", "in", employees.ids),
                ("state", "=", "approved"),
                ("date_from", "<=", today),
                ("date_to", ">=", today),
            ],
            order="date_from asc",
        )
        leave_by_employee = {leave.employee_id.id: leave for leave in approved_leaves}

        company_days = self._company_day_records(
            date_from=today,
            date_to=today,
            company_ids=employees.mapped("company_id").ids,
        ).filtered(lambda day: day.day_type == "holiday")
        global_days = company_days.filtered(lambda day: not day.company_id)
        days_by_company = {}
        for day in company_days.filtered(lambda day: day.company_id):
            days_by_company[day.company_id.id] = days_by_company.get(
                day.company_id.id, request.env["dsl.hr.company.day"].sudo().browse()
            ) | day

        buckets = {
            "present": [],
            "checked_out": [],
            "leave": [],
            "holiday": [],
            "absent": [],
        }
        overview_rows = []
        for employee in employees.sorted(lambda item: item.name or ""):
            employee_days = global_days | days_by_company.get(
                employee.company_id.id, request.env["dsl.hr.company.day"].sudo().browse()
            )
            row = {
                "employee": employee,
                "department": employee.department_id.name if employee.department_id else "",
                "job_title": employee.job_id.name if employee.job_id else "",
                "attendance": last_attendance.get(employee.id),
                "leave": leave_by_employee.get(employee.id),
                "company_days": employee_days,
            }
            if employee.id in open_ids:
                row.update({"status": "present", "status_label": "Present Now", "status_class": "present"})
                buckets["present"].append(row)
            elif employee.id in leave_by_employee:
                row.update({"status": "on_leave", "status_label": "On Leave", "status_class": "leave"})
                buckets["leave"].append(row)
            elif employee_days:
                row.update({"status": "holiday", "status_label": "Holiday", "status_class": "holiday"})
                buckets["holiday"].append(row)
            elif employee.id in attended_ids:
                row.update({"status": "checked_out", "status_label": "Checked Out", "status_class": "checked-out"})
                buckets["checked_out"].append(row)
            else:
                row.update({"status": "absent", "status_label": "Absent", "status_class": "absent"})
                buckets["absent"].append(row)
            overview_rows.append(row)

        return {
            "date": today,
            "total_count": len(employees),
            "present_count": len(buckets["present"]),
            "checked_out_count": len(buckets["checked_out"]),
            "attended_count": len(buckets["present"]) + len(buckets["checked_out"]),
            "leave_count": len(buckets["leave"]),
            "holiday_count": len(buckets["holiday"]),
            "absent_count": len(buckets["absent"]),
            "present_rows": buckets["present"],
            "checked_out_rows": buckets["checked_out"],
            "leave_rows": buckets["leave"],
            "holiday_rows": buckets["holiday"],
            "absent_rows": buckets["absent"],
            "overview_rows": overview_rows,
            "company_days": company_days,
        }

    def _request_records(self, model_name, employee, limit=20):
        if not employee:
            return request.env[model_name].sudo().browse()
        return request.env[model_name].sudo().search(
            [("employee_id", "=", employee.id)],
            limit=limit,
            order="submitted_on desc, id desc",
        )

    def _team_request_records(self, model_name, employees, limit=20, pending_only=False):
        if not employees:
            return request.env[model_name].sudo().browse()
        domain = [("employee_id", "in", employees.ids)]
        if pending_only:
            domain.append(("state", "in", ["draft", "submitted", "under_review"]))
        return request.env[model_name].sudo().search(
            domain,
            limit=limit,
            order="submitted_on desc, id desc",
        )

    def _overview_label(self):
        return "Company" if self._is_hr_user() else "Team"

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
        employee = self._get_employee_record()
        if not employee and not self._is_hr_user():
            return request.redirect("/dsl/no-employee")

        attendance_data = self._attendance_values(employee)
        overview_employees = self._overview_employees(employee)
        attendance_overview = self._attendance_overview(overview_employees) if overview_employees else False
        values = self._base_values("dashboard", employee)
        values.update(
            {
                "open_attendance": attendance_data["open_attendance"],
                "recent_attendance": attendance_data["attendance_records"][:4],
                "attendance_overview": attendance_overview,
                "overview_scope_label": self._overview_label(),
                "leave_requests": self._request_records("dsl.hr.leave.request", employee, 5),
                "attendance_requests": self._request_records(
                    "dsl.hr.attendance.request", employee, 5
                ),
                "support_tickets": self._request_records("dsl.hr.support.ticket", employee, 5),
                "settlement_requests": self._request_records(
                    "dsl.hr.settlement.request", employee, 3
                ),
                "pending_leave_requests": self._team_request_records(
                    "dsl.hr.leave.request", overview_employees, 5, pending_only=True
                ),
                "pending_attendance_requests": self._team_request_records(
                    "dsl.hr.attendance.request", overview_employees, 5, pending_only=True
                ),
                "pending_support_tickets": self._team_request_records(
                    "dsl.hr.support.ticket", overview_employees, 5, pending_only=True
                ),
                "pending_settlement_requests": self._team_request_records(
                    "dsl.hr.settlement.request", overview_employees, 5, pending_only=True
                ),
            }
        )
        return request.render("dsl_hr_portal.dsl_dashboard_page", values)

    @http.route("/dsl/attendance", type="http", auth="user", website=True)
    def dsl_attendance(self, **kw):
        employee = self._get_employee_record()
        if not employee and not self._is_hr_user():
            return request.redirect("/dsl/no-employee")

        overview_employees = self._overview_employees(employee)
        values = self._base_values("attendance", employee)
        values.update(self._attendance_values(employee))
        values.update(
            {
                "attendance_overview": self._attendance_overview(overview_employees) if overview_employees else False,
                "overview_scope_label": self._overview_label(),
                "manual_requests": self._request_records("dsl.hr.attendance.request", employee),
                "team_attendance_requests": self._team_request_records(
                    "dsl.hr.attendance.request", overview_employees, 20, pending_only=True
                ),
            }
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
                    {"ok": False, "message": "You are already checked in."}, 400
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
        employee = self._get_employee_record()
        if not employee and not self._is_hr_user():
            return request.redirect("/dsl/no-employee")

        overview_employees = self._overview_employees(employee)
        values = self._base_values("leave", employee)
        values.update(
            {
                "leave_requests": self._request_records("dsl.hr.leave.request", employee),
                "team_leave_requests": self._team_request_records(
                    "dsl.hr.leave.request", overview_employees, 20, pending_only=True
                ),
                "company_days": self._upcoming_company_days(overview_employees, employee),
                "overview_scope_label": self._overview_label(),
                "leave_error": kw.get("error"),
            }
        )
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
        except ValidationError:
            return request.redirect("/dsl/leave?error=blocked")
        except Exception:
            return request.redirect("/dsl/leave?error=request")
        return request.redirect("/dsl/leave?submitted=1")

    @http.route("/dsl/directory", type="http", auth="user", website=True)
    def dsl_directory(self, q=None, **kw):
        employee = self._get_employee_record()
        if not employee and not self._is_hr_user():
            return request.redirect("/dsl/no-employee")

        Employee = request.env["hr.employee"].sudo()
        if self._is_hr_user():
            visible_employees = self._active_employees()
        else:
            if not self._visible_employees(employee, include_self=False):
                return request.redirect("/dsl/dashboard")
            visible_employees = self._visible_employees(employee)

        domain = [("id", "in", visible_employees.ids)]
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

    @http.route("/dsl/team", type="http", auth="user", website=True)
    def dsl_team(self, **kw):
        employee = self._require_employee()
        if not getattr(employee, "id", False):
            return employee

        team_employees = self._visible_employees(employee, include_self=False)
        if not team_employees:
            return request.redirect("/dsl/dashboard")
        values = self._base_values("team", employee)
        values.update({"team_employees": team_employees})
        return request.render("dsl_hr_portal.dsl_team_page", values)

    @http.route(
        "/dsl/team/request/<string:request_type>/<int:record_id>/<string:action_name>",
        type="http",
        auth="user",
        website=True,
        methods=["POST"],
    )
    def dsl_team_request_action(self, request_type, record_id, action_name, **post):
        model_map = {
            "leave": "dsl.hr.leave.request",
            "attendance": "dsl.hr.attendance.request",
            "support": "dsl.hr.support.ticket",
            "settlement": "dsl.hr.settlement.request",
        }
        if action_name not in ("review", "approve", "reject"):
            return request.not_found()

        employee = self._get_employee_record()
        if not employee and not self._is_hr_user():
            return request.not_found()

        team_employees = self._overview_employees(employee)
        model_name = model_map.get(request_type)
        if not model_name or not team_employees:
            return request.not_found()

        record = request.env[model_name].sudo().browse(record_id)
        if not record.exists() or record.employee_id not in team_employees:
            return request.not_found()

        if record.state not in ("approved", "rejected"):
            if action_name == "review":
                record.action_mark_under_review()
            elif action_name == "approve":
                record.action_approve()
            elif action_name == "reject":
                record.action_reject()

        return request.redirect("/dsl/team?updated=1")

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
        if self._get_employee_record() or self._is_hr_user():
            return request.redirect("/dsl/dashboard")
        return super().home(**kw)
