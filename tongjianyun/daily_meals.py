from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import getdate, nowdate
from tongjianyun.attendance_scope import allowed_groups, require_group, require_manager, visible_confirmation


CONFIRMATION_DOCTYPE = "Tongjianyun Daily Meal Confirmation"
ADJUSTMENT_DOCTYPE = "Tongjianyun Daily Meal Adjustment"
DEFAULT_MEAL_SERVICE = (
    ("breakfast_count", True),
    ("morning_snack_count", True),
    ("lunch_count", True),
    ("afternoon_snack_count", True),
    ("dinner_count", False),
)
STUDENT_ATTENDANCE_STATUSES = {"Present", "Absent", "Leave"}
ATTENDANCE_EDITOR_ROLES = {
    "System Manager",
    "Education Manager",
    "Instructor",
    "Tongjianyun Administrator",
    "Tongjianyun Director",
    "Tongjianyun Teacher",
}


def _active_groups(student_group=None) -> list[dict]:
    filters = {"disabled": 0}
    if student_group:
        filters["name"] = student_group
    rows = frappe.get_all(
        "Student Group",
        filters=filters,
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


def _active_student_rows(group: str) -> list[dict]:
    return [
        dict(row)
        for row in frappe.get_all(
            "Student Group Student",
            filters={"parent": group, "active": 1},
            fields=["student", "student_name", "group_roll_number"],
            order_by="group_roll_number asc, student asc",
        )
    ]


def _attendance_records(group: str, meal_date) -> dict[str, dict]:
    rows = frappe.get_all(
        "Student Attendance",
        filters={
            "student_group": group,
            "date": meal_date,
            "docstatus": ["!=", 2],
        },
        fields=["name", "student", "status", "leave_application", "docstatus"],
        order_by="modified desc",
    )
    records = {}
    for row in rows:
        records.setdefault(row.student, dict(row))
    return records


def _attendance_by_student(group: str, meal_date) -> dict[str, str]:
    return {
        student: record.get("status") or ""
        for student, record in _attendance_records(group, meal_date).items()
    }


def _leave_records(group: str, students: list[str], meal_date) -> dict[str, dict]:
    if not students:
        return {}
    rows = frappe.get_all(
        "Student Leave Application",
        filters={
            "student": ["in", students],
            "from_date": ["<=", meal_date],
            "to_date": [">=", meal_date],
            "docstatus": ["!=", 2],
            "mark_as_present": 0,
        },
        fields=["name", "student", "reason", "mark_as_present", "docstatus"],
        order_by="modified desc",
    )
    records = {}
    for row in rows:
        records.setdefault(row.student, dict(row))
    return records


def _leave_students(group: str, students: list[str], meal_date) -> set[str]:
    return set(_leave_records(group, students, meal_date))


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


def calculate_student_details(meal_date=None, student_group=None) -> list[dict]:
    meal_date = getdate(meal_date or nowdate())
    all_details = []
    for group in _active_groups(student_group):
        student_rows = _active_student_rows(group["name"])
        students = [row["student"] for row in student_rows]
        attendance = _attendance_records(group["name"], meal_date)
        leave_records = _leave_records(group["name"], students, meal_date)
        absent_students = {
            student
            for student, record in attendance.items()
            if record.get("status") == "Absent"
        }
        missing_names = [
            row["student"] for row in student_rows if not row.get("student_name")
        ]
        name_map = {
            row.name: row.student_name
            for row in (
                frappe.get_all(
                    "Student",
                    filters={"name": ["in", missing_names]},
                    fields=["name", "student_name"],
                )
                if missing_names
                else []
            )
        }
        for row in student_rows:
            student = row["student"]
            attendance_record = attendance.get(student) or {}
            attendance_status = attendance_record.get("status") or ""
            leave_record = leave_records.get(student)
            status = "Present"
            if student in absent_students:
                status = "Absent"
            elif leave_record or attendance_status == "Leave":
                status = "Leave"
            all_details.append(
                {
                    "student_group": group["name"],
                    "class_name": group.get("student_group_name") or group["name"],
                    "student": student,
                    "group_roll_number": row.get("group_roll_number") or 0,
                    "student_name": row.get("student_name") or name_map.get(student) or "",
                    "attendance_status": status,
                    "leave_reason": (leave_record or {}).get("reason") or "",
                    "leave_application": (leave_record or {}).get("name") or "",
                    "attendance_record": attendance_record.get("name") or "",
                    "breakfast": 1 if status == "Present" else 0,
                    "morning_snack": 1 if status == "Present" else 0,
                    "lunch": 1 if status == "Present" else 0,
                    "afternoon_snack": 1 if status == "Present" else 0,
                    "dinner": 0,
                }
            )
    return all_details


def refresh_confirmation(meal_date=None, *, force=False):
    meal_date = getdate(meal_date or nowdate())
    name = frappe.db.exists(CONFIRMATION_DOCTYPE, {"meal_date": meal_date})
    doc = (
        frappe.get_doc(CONFIRMATION_DOCTYPE, name)
        if name
        else frappe.new_doc(CONFIRMATION_DOCTYPE)
    )
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


def prepare_today_confirmation():
    refresh_confirmation(nowdate())


def _require_login():
    if frappe.session.user == "Guest":
        frappe.throw(_("请先登录"), frappe.AuthenticationError)


def _require_attendance_editor():
    if not set(frappe.get_roles()).intersection(ATTENDANCE_EDITOR_ROLES):
        frappe.throw(_("当前角色只能查看学生缺勤，不能修改"), frappe.PermissionError)


def _get_confirmation_for_edit(meal_date):
    meal_date = getdate(meal_date or nowdate())
    name = frappe.db.exists(CONFIRMATION_DOCTYPE, {"meal_date": meal_date})
    if name:
        doc = frappe.get_doc(CONFIRMATION_DOCTYPE, name)
        doc.check_permission("write")
    else:
        if not frappe.has_permission(CONFIRMATION_DOCTYPE, "create"):
            frappe.throw(_("没有创建每日就餐确认的权限"), frappe.PermissionError)
        doc = refresh_confirmation(meal_date)
    if doc.status == "已锁定":
        frappe.throw(_("该日期已锁定，不能修改学生缺勤"), frappe.PermissionError)
    if doc.status == "已确认":
        frappe.throw(_("该日期已确认，请先点击“重新核对”后再修改"), frappe.ValidationError)
    return doc


def _student_name(student: str) -> str:
    return frappe.db.get_value("Student", student, "student_name") or student


def _assert_active_membership(student_group: str, student: str):
    if not frappe.db.exists(
        "Student Group Student",
        {"parent": student_group, "student": student, "active": 1},
    ):
        frappe.throw(_("学生 {0} 不属于班级 {1}，或该学生已停用").format(student, student_group))


def _set_student_status(
    student_group: str, student: str, meal_date, status: str, reason: str = ""
):
    _assert_active_membership(student_group, student)
    attendance_records = _attendance_records(student_group, meal_date)
    attendance_data = attendance_records.get(student)
    leave_record = _leave_records(student_group, [student], meal_date).get(student)

    if status == "Leave":
        if leave_record:
            return leave_record.get("name")
        leave_doc = frappe.new_doc("Student Leave Application")
        leave_doc.student = student
        leave_doc.student_name = _student_name(student)
        leave_doc.attendance_based_on = "Student Group"
        leave_doc.student_group = student_group
        leave_doc.from_date = meal_date
        leave_doc.to_date = meal_date
        leave_doc.reason = (reason or "").strip()
        if not leave_doc.reason:
            frappe.throw(_("标记请假时必须填写请假原因"))
        leave_doc.insert(ignore_permissions=True)
        leave_doc.submit()
        return leave_doc.name

    if leave_record:
        frappe.throw(
            _("学生 {0} 已有生效的请假申请 {1}，请先在请假模块撤销或标记返校").format(
                student, leave_record.get("name")
            )
        )

    if attendance_data:
        attendance_doc = frappe.get_doc("Student Attendance", attendance_data["name"])
        attendance_doc.status = status
        attendance_doc.save(ignore_permissions=True)
        if attendance_doc.docstatus == 0:
            attendance_doc.submit()
        return attendance_doc.name

    attendance_doc = frappe.new_doc("Student Attendance")
    attendance_doc.student = student
    attendance_doc.student_name = _student_name(student)
    attendance_doc.student_group = student_group
    attendance_doc.date = meal_date
    attendance_doc.status = status
    attendance_doc.insert(ignore_permissions=True)
    attendance_doc.submit()
    return attendance_doc.name


@frappe.whitelist()
def get_daily_meal_confirmation(meal_date=None) -> dict:
    _require_login()
    name = frappe.db.exists(
        CONFIRMATION_DOCTYPE,
        {"meal_date": getdate(meal_date or nowdate())},
    )
    if not name:
        require_manager()
    if not name and not frappe.has_permission(CONFIRMATION_DOCTYPE, "create"):
        frappe.throw(_("没有创建每日就餐确认的权限"), frappe.PermissionError)
    doc = (
        frappe.get_doc(CONFIRMATION_DOCTYPE, name)
        if name
        else refresh_confirmation(meal_date)
    )
    doc.check_permission("read")
    return visible_confirmation(doc, allowed_groups())


@frappe.whitelist(methods=["POST"])
def confirm_daily_meal(meal_date=None) -> dict:
    require_manager()
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
    require_manager()
    doc = frappe.get_doc(CONFIRMATION_DOCTYPE, name)
    doc.check_permission("write")
    refreshed = refresh_confirmation(doc.meal_date, force=True)
    return refreshed.as_dict()


@frappe.whitelist()
def get_student_details(meal_date=None, student_group=None) -> list:
    _require_login()
    frappe.has_permission(CONFIRMATION_DOCTYPE, "read", throw=True)
    scope = allowed_groups()
    if student_group:
        require_group(student_group, scope)
        scope = [student_group]
    return [row for group in scope for row in calculate_student_details(meal_date, group)]


@frappe.whitelist(methods=["POST"])
def save_student_meal_attendance(meal_date=None, changes=None) -> dict:
    _require_login()
    _require_attendance_editor()
    changes = frappe.parse_json(changes) if isinstance(changes, str) else changes
    if not isinstance(changes, list) or not changes:
        frappe.throw(_("没有需要保存的学生缺勤变更"))

    scope = allowed_groups()
    # Validate every class before any write (including confirmation creation).
    for change in changes:
        if not isinstance(change, dict):
            frappe.throw(_("学生缺勤变更格式不正确"))
        require_group(change.get("student_group"), scope)
    _get_confirmation_for_edit(meal_date)
    seen = set()
    meal_date = getdate(meal_date or nowdate())
    for change in changes:
        if not isinstance(change, dict):
            frappe.throw(_("学生缺勤变更格式不正确"))
        student_group = (change.get("student_group") or "").strip()
        student = (change.get("student") or "").strip()
        status = (change.get("status") or "").strip()
        if not student_group or not student or status not in STUDENT_ATTENDANCE_STATUSES:
            frappe.throw(_("学生、班级和出勤状态不能为空或不正确"))
        key = (student_group, student)
        if key in seen:
            frappe.throw(_("学生 {0} 在本次提交中重复出现").format(student))
        seen.add(key)
        _set_student_status(
            student_group,
            student,
            meal_date,
            status,
            change.get("leave_reason") or "",
        )

    refreshed = refresh_confirmation(meal_date, force=True)
    return {
        "confirmation": visible_confirmation(refreshed, scope),
        "details": [row for group in scope for row in calculate_student_details(meal_date, group)],
    }


@frappe.whitelist(methods=["POST"])
def reopen_daily_meal(name: str) -> dict:
    require_manager()
    _require_login()
    _require_attendance_editor()
    doc = frappe.get_doc(CONFIRMATION_DOCTYPE, name)
    doc.check_permission("write")
    if doc.status == "已锁定":
        frappe.throw(_("已锁定的每日就餐确认不能重新核对"), frappe.PermissionError)
    if doc.status != "待确认":
        doc.status = "待确认"
        doc.confirmed_by = None
        doc.confirmed_at = None
        doc.save()
    return doc.as_dict()
