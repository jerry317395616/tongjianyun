"""Class-scoped meal snapshots. Attendance and meal participation are separate facts."""
import hashlib

import frappe
from frappe.utils import getdate, nowdate, now_datetime
from tongjianyun.attendance_scope import allowed_groups, require_group

DOCTYPE = "Tongjianyun Class Meal Confirmation"
MEALS = ("breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner")
STATES = {"未确认", "已就餐", "未就餐", "不供餐"}


def record_name(day, group):
    return "CM-" + str(getdate(day)) + "-" + hashlib.sha256(group.encode()).hexdigest()[:16]


def document_permission(doc, user=None, permission_type=None, **kwargs):
    if user and user != frappe.session.user:
        return False
    return doc.student_group in allowed_groups()


def query_condition(user=None, **kwargs):
    if user and user != frappe.session.user:
        return "1=0"
    groups = allowed_groups()
    if not groups:
        return "1=0"
    return frappe.qb.DocType(DOCTYPE).student_group.isin(groups)


def _editor(group):
    from tongjianyun.daily_meals import _require_login, _require_attendance_editor
    _require_login()
    _require_attendance_editor()
    require_group(group, allowed_groups())


def _roster(day, group):
    from tongjianyun.daily_meals import calculate_student_details
    return calculate_student_details(day, group)


def _load(day, group):
    name = record_name(day, group)
    if frappe.db.exists(DOCTYPE, name):
        return frappe.get_doc(DOCTYPE, name)
    doc = frappe.new_doc(DOCTYPE)
    doc.meal_date, doc.student_group, doc.status = getdate(day), group, "待确认"
    for student in _roster(day, group):
        row = {"student": student["student"], "student_name": student["student_name"],
               "attendance_hint": student["attendance_status"]}
        for meal in MEALS:
            row[meal + "_expected"] = int(student[meal])
            row[meal] = "未确认" if meal != "dinner" else "不供餐"
        doc.append("students", row)
    return doc


def meal_counts(rows, expected=False):
    return {meal + "_count": sum(int(row.get(meal + "_expected") or 0) if expected
                               else int(row.get(meal) == "已就餐") for row in rows)
            for meal in MEALS}


def validate(doc):
    _editor(doc.student_group)
    old = doc.get_doc_before_save()
    if old and (str(getdate(old.meal_date)) != str(getdate(doc.meal_date)) or old.student_group != doc.student_group):
        frappe.throw("不能更改就餐记录的日期或班级")
    locked = frappe.db.get_value("Tongjianyun Daily Meal Confirmation", {"meal_date": doc.meal_date}, "status")
    if locked == "已锁定":
        frappe.throw("该日已锁定，不能修改就餐记录")
    if doc.status not in {"待确认", "已确认"}:
        frappe.throw("无效的确认状态")
    if doc.status == "已确认" and getdate(doc.meal_date) > getdate(nowdate()):
        frappe.throw("未来日期只能保存预计人数，不能确认实际就餐")
    if old and old.status == "已确认" and not str(doc.change_reason or "").strip():
        frappe.throw("修改已确认人数必须填写原因")
    authoritative = {r["student"]: r for r in _roster(doc.meal_date, doc.student_group)} if not old else {r.student: r for r in old.students}
    roster = set(authoritative)
    submitted = [r.student for r in doc.students]
    if len(submitted) != len(set(submitted)) or set(submitted) != roster:
        frappe.throw("学生名单不完整、重复或已变化，请重新加载核对")
    if not submitted:
        frappe.throw("班级暂无启用学生，不能确认人数")
    for row in doc.students:
        original = authoritative[row.student]
        row.student_name = original.get("student_name")
        row.attendance_hint = original.get("attendance_hint", original.get("attendance_status"))
        for meal in MEALS:
            if row.get(meal) not in STATES or row.get(meal + "_expected") not in (0, 1):
                frappe.throw("就餐状态或预计值不正确")
            if doc.status == "已确认" and row.get(meal) == "未确认":
                frappe.throw("请核对全部餐次后确认；不提供的餐次请选择不供餐")
            if doc.status == "待确认" and row.get(meal) in {"已就餐", "未就餐"}:
                frappe.throw("预计记录不能包含实际就餐结论")
    doc.confirmed_by = frappe.session.user if doc.status == "已确认" else None
    doc.confirmed_at = now_datetime() if doc.status == "已确认" else None


@frappe.whitelist()
def get_class_meals(meal_date=None, student_group=None):
    frappe.has_permission(DOCTYPE, "read", throw=True)
    scope = allowed_groups()
    groups = [{"name": g, "label": frappe.db.get_value("Student Group", g, "student_group_name") or g} for g in scope]
    if not student_group:
        return {"groups": groups}
    require_group(student_group, scope)
    doc = _load(meal_date or nowdate(), student_group)
    return {"groups": groups, "record": doc.as_dict(), "revision": "" if doc.is_new() else str(doc.modified or ""),
            "expected": meal_counts(doc.students, True), "actual": meal_counts(doc.students)}


@frappe.whitelist(methods=["POST"])
def save_class_meals(meal_date, student_group, students, revision="", confirm=0, change_reason=""):
    _editor(student_group)
    students = frappe.parse_json(students) if isinstance(students, str) else students
    if not isinstance(students, list) or not all(isinstance(r, dict) for r in students):
        frappe.throw("学生明细格式不正确")
    if str(confirm) not in {"0", "1"}:
        frappe.throw("确认参数不正确")
    name = record_name(meal_date, student_group)
    if frappe.db.exists(DOCTYPE, name):
        frappe.db.get_value(DOCTYPE, name, "name", for_update=True)
    doc = _load(meal_date, student_group)
    if ("" if doc.is_new() else str(doc.modified or "")) != str(revision or ""):
        frappe.throw("人数已被其他人修改，请重新加载后核对")
    by_student = {r.student: r for r in doc.students}
    if len(students) != len(by_student) or {r.get("student") for r in students} != set(by_student):
        frappe.throw("提交的名单与班级名单不一致，请重新加载")
    do_confirm = str(confirm) == "1"
    for entry in students:
        row = by_student[entry["student"]]
        for meal in MEALS:
            value = entry.get(meal)
            if value not in {"就餐", "不就餐", "不供餐"}:
                frappe.throw("请完整选择每名学生的就餐安排")
            row.set(meal + "_expected", int(value == "就餐"))
            row.set(meal, {"就餐": "已就餐", "不就餐": "未就餐", "不供餐": "不供餐"}[value]
                    if do_confirm else ("不供餐" if value == "不供餐" else "未确认"))
    doc.status = "已确认" if do_confirm else "待确认"
    doc.change_reason = change_reason
    doc.save()
    return get_class_meals(meal_date, student_group)


def apply_class_snapshots(rows, day):
    """Return confirmed counts where available, expected counts otherwise."""
    if not frappe.db.exists("DocType", DOCTYPE):
        return rows
    for row in rows:
        name = record_name(day, row["student_group"])
        if frappe.db.exists(DOCTYPE, name):
            doc = frappe.get_doc(DOCTYPE, name)
            row.update(meal_counts(doc.students, expected=doc.status != "已确认"))
            row["enrolled_count"] = len(doc.students)
            row["absent_count"] = sum(r.attendance_hint == "Absent" for r in doc.students)
            row["leave_count"] = sum(r.attendance_hint == "Leave" for r in doc.students)
    return rows


def all_classes_confirmed(rows, day):
    if not rows or not frappe.db.exists("DocType", DOCTYPE):
        return False
    return all(frappe.db.get_value(DOCTYPE, record_name(day, r["student_group"]), "status") == "已确认"
               for r in rows if r["enrolled_count"] > 0) and any(r["enrolled_count"] > 0 for r in rows)


def procurement_counts(day):
    """Only use a complete, readable set of class plans; never expose partial totals."""
    from tongjianyun.daily_meals import _active_groups, _active_students
    if not frappe.db.exists("DocType", DOCTYPE) or not frappe.has_permission(DOCTYPE, "read"):
        return None
    groups = [g["name"] for g in _active_groups() if _active_students(g["name"])]
    scope = set(allowed_groups())
    if not groups or not set(groups).issubset(scope):
        return None
    counts = {m + "_count": 0 for m in MEALS}
    for group in groups:
        name = record_name(day, group)
        if not frappe.db.exists(DOCTYPE, name):
            return None
        doc = frappe.get_doc(DOCTYPE, name)
        doc.check_permission("read")
        for key, value in meal_counts(doc.students, expected=doc.status != "已确认").items():
            counts[key] += value
    return counts
