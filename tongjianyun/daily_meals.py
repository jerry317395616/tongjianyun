from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import getdate, nowdate


CONFIRMATION_DOCTYPE = "Tongjianyun Daily Meal Confirmation"
ADJUSTMENT_DOCTYPE = "Tongjianyun Daily Meal Adjustment"
SPECIAL_DIET_DOCTYPE = "Tongjianyun Special Diet"

DEFAULT_MEAL_SERVICE = (
    ("breakfast_count", True),
    ("morning_snack_count", True),
    ("lunch_count", True),
    ("afternoon_snack_count", True),
    ("dinner_count", False),
)


def _active_groups() -> list[dict]:
    rows = frappe.get_all(
        "Student Group",
        filters={"disabled": 0},
        fields=["name", "student_group_name"],
        order_by="student_group_name asc",
    )
    return [dict(row) for row in rows]


def _active_students(group: str) -> list[str]:
    return frappe.get_all(
        "Student Group Student",
        filters={"parent": group, "active": 1},
        pluck="student",
    )


def _attendance_by_student(group: str, meal_date) -> dict[str, str]:
    rows = frappe.get_all(
        "Student Attendance",
        filters={
            "student_group": group,
            "date": meal_date,
            "docstatus": ["!=", 2],
        },
        fields=["student", "status"],
    )
    return {row.student: row.status for row in rows}


def _leave_students(group: str, students: list[str], meal_date) -> set[str]:
    if not students:
        return set()
    rows = frappe.get_all(
        "Student Leave Application",
        filters={
            "student": ["in", students],
            "from_date": ["<=", meal_date],
            "to_date": [">=", meal_date],
            "docstatus": ["!=", 2],
            "mark_as_present": 0,
        },
        pluck="student",
    )
    return set(rows)


def _special_diet_count(students: list[str], meal_date) -> int:
    if not students:
        return 0
    rows = frappe.get_all(
        SPECIAL_DIET_DOCTYPE,
        filters={
            "student": ["in", students],
            "status": "生效中",
            "effective_from": ["<=", meal_date],
        },
        fields=["student", "effective_to"],
    )
    return len(
        {
            row.student
            for row in rows
            if not row.effective_to or getdate(row.effective_to) >= meal_date
        }
    )


def _adjustments(group: str, meal_date) -> dict[str, int]:
    totals = defaultdict(int)
    rows = frappe.get_all(
        ADJUSTMENT_DOCTYPE,
        filters={"student_group": group, "meal_date": meal_date},
        fields=[
            "breakfast_delta",
            "morning_snack_delta",
            "lunch_delta",
            "afternoon_snack_delta",
            "dinner_delta",
        ],
    )
    for row in rows:
        for fieldname in (
            "breakfast_delta",
            "morning_snack_delta",
            "lunch_delta",
            "afternoon_snack_delta",
            "dinner_delta",
        ):
            totals[fieldname] += int(row.get(fieldname) or 0)
    return totals


def calculate_rows(meal_date=None) -> list[dict]:
    meal_date = getdate(meal_date or nowdate())
    results = []
    for group in _active_groups():
        students = _active_students(group["name"])
        attendance = _attendance_by_student(group["name"], meal_date)
        leave_students = _leave_students(group["name"], students, meal_date)
        absent_students = {
            student for student, status in attendance.items() if status == "Absent"
        }
        unavailable = absent_students | leave_students
        present_count = max(len(students) - len(unavailable), 0)
        adjustments = _adjustments(group["name"], meal_date)
        row = {
            "student_group": group["name"],
            "class_name": group.get("student_group_name") or group["name"],
            "enrolled_count": len(students),
            "absent_count": len(absent_students),
            "leave_count": len(leave_students - absent_students),
            "special_diet_count": _special_diet_count(students, meal_date),
        }
        for count_field, is_served in DEFAULT_MEAL_SERVICE:
            delta_field = count_field.replace("_count", "_delta")
            row[count_field] = max(
                (present_count if is_served else 0)
                + adjustments.get(delta_field, 0),
                0,
            )
        results.append(row)
    return results


def refresh_confirmation(meal_date=None, *, force=False):
    meal_date = getdate(meal_date or nowdate())
    name = frappe.db.exists(CONFIRMATION_DOCTYPE, {"meal_date": meal_date})
    doc = frappe.get_doc(CONFIRMATION_DOCTYPE, name) if name else frappe.new_doc(CONFIRMATION_DOCTYPE)
    if name and doc.status in {"已确认", "已锁定"} and not force:
        return doc
    doc.meal_date = meal_date
    doc.status = "待确认"
    doc.source = "Education考勤"
    doc.set("details", [])
    for row in calculate_rows(meal_date):
        doc.append("details", row)
    if name:
        doc.save(ignore_permissions=True)
    else:
        doc.insert(ignore_permissions=True)
    return doc


def refresh_confirmation_from_event(doc, method=None):
    if frappe.db.exists(CONFIRMATION_DOCTYPE, {"meal_date": getdate(doc.date)}):
        refresh_confirmation(doc.date)


def refresh_confirmations_from_leave(doc, method=None):
    start = getdate(doc.from_date)
    end = getdate(doc.to_date)
    current = start
    while current <= end:
        if current >= getdate(nowdate()) or frappe.db.exists(
            CONFIRMATION_DOCTYPE, {"meal_date": current}
        ):
            refresh_confirmation(current)
        current += timedelta(days=1)


def refresh_confirmation_from_adjustment(doc, method=None):
    if getattr(doc, "meal_date", None):
        refresh_confirmation(doc.meal_date)


def refresh_confirmation_from_special_diet(doc, method=None):
    today = getdate(nowdate())
    starts = not doc.effective_from or getdate(doc.effective_from) <= today
    ends = not doc.effective_to or getdate(doc.effective_to) >= today
    if starts and ends and frappe.db.exists(CONFIRMATION_DOCTYPE, {"meal_date": today}):
        refresh_confirmation(today)


def prepare_today_confirmation():
    refresh_confirmation(nowdate())


@frappe.whitelist()
def get_daily_meal_confirmation(meal_date=None) -> dict:
    if frappe.session.user == "Guest":
        frappe.throw(_("请先登录"), frappe.AuthenticationError)
    name = frappe.db.exists(
        CONFIRMATION_DOCTYPE,
        {"meal_date": getdate(meal_date or nowdate())},
    )
    if not name and not frappe.has_permission(CONFIRMATION_DOCTYPE, "create"):
        frappe.throw(_("没有创建每日就餐确认的权限"), frappe.PermissionError)
    doc = frappe.get_doc(CONFIRMATION_DOCTYPE, name) if name else refresh_confirmation(meal_date)
    doc.check_permission("read")
    return doc.as_dict()


@frappe.whitelist(methods=["POST"])
def confirm_daily_meal(meal_date=None) -> dict:
    name = frappe.db.exists(
        CONFIRMATION_DOCTYPE,
        {"meal_date": getdate(meal_date or nowdate())},
    )
    if name:
        doc = frappe.get_doc(CONFIRMATION_DOCTYPE, name)
        doc.check_permission("write")
        doc = refresh_confirmation(meal_date)
    else:
        if not frappe.has_permission(CONFIRMATION_DOCTYPE, "create"):
            frappe.throw(_("没有创建每日就餐确认的权限"), frappe.PermissionError)
        doc = refresh_confirmation(meal_date)
    doc.check_permission("write")
    doc.status = "已确认"
    doc.save()
    return doc.as_dict()


@frappe.whitelist(methods=["POST"])
def recalculate_daily_meal(name: str) -> dict:
    doc = frappe.get_doc(CONFIRMATION_DOCTYPE, name)
    doc.check_permission("write")
    refreshed = refresh_confirmation(doc.meal_date, force=True)
    return refreshed.as_dict()
