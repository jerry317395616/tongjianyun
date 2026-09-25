"""Class-scoped meal snapshots. Attendance and meal participation are separate facts."""
import hashlib
from dataclasses import dataclass

import frappe
from frappe.utils import getdate, nowdate, now_datetime
from tongjianyun.attendance_scope import allowed_groups, require_group

DOCTYPE = "Tongjianyun Class Meal Confirmation"
MEALS = ("breakfast", "morning_snack", "lunch", "afternoon_snack", "dinner")
STATES = {"未确认", "已就餐", "未就餐", "不供餐"}
LABELS = dict(zip(MEALS, ("早餐", "早点", "午餐", "午点", "晚餐")))
ACTUAL_STATES = {"已就餐", "未就餐"}


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


def _roster(day, group, *, source_observer=None):
    from tongjianyun.daily_meals import calculate_student_details, _calculate_student_details
    if source_observer is not None:
        return _calculate_student_details(day, group, source_observer=source_observer)
    return calculate_student_details(day, group)


@dataclass(frozen=True)
class ClassMealReadSources:
    """Private snapshot/estimate provenance from the same native read."""
    group: str
    day: str
    revision: str
    record: str | None
    students: tuple[str, ...]
    estimates: object | None = None


def _load(day, group, *, source_observer=None):
    if source_observer is not None and not callable(source_observer):
        raise TypeError('Class meal source observer must be callable')
    name = record_name(day, group)
    if frappe.db.exists(DOCTYPE, name):
        doc = frappe.get_doc(DOCTYPE, name)
        if source_observer is not None:
            source_observer(ClassMealReadSources(group, str(getdate(day)), str(doc.modified or ''),
                doc.name, tuple(row.student for row in doc.students)))
        return doc
    doc = frappe.new_doc(DOCTYPE)
    doc.meal_date, doc.student_group, doc.status = getdate(day), group, "待确认"
    sources = []
    options = {'source_observer': sources.append} if source_observer is not None else {}
    for student in _roster(day, group, **options):
        row = {"student": student["student"], "student_name": student["student_name"],
               "attendance_hint": student["attendance_status"]}
        for meal in MEALS:
            row[meal + "_expected"] = int(student[meal])
            # The old service schedule only supplies an estimate. Zero expected
            # dinner is not evidence that dinner is actually not provided.
            row[meal] = "未确认"
        doc.append("students", row)
    if source_observer is not None:
        from tongjianyun.daily_meals import StudentMealReadSources
        if (len(sources) != 1 or not isinstance(sources[0], StudentMealReadSources)
                or sources[0].day != str(getdate(day)) or sources[0].groups != (group,)):
            raise ValueError('Original meal estimate source capture is incomplete')
        source_observer(ClassMealReadSources(group, str(getdate(day)), '', None,
            tuple(row.student for row in doc.students), sources[0]))
    return doc


def meal_facts(rows):
    """A complete meal is independent of other meals in the same class-day.

    Explicit non-service rows are not attendance facts. An unfinished or empty
    roster has no final actual count; its confirmed subtotal is named separately.
    No new field or migration is required for historical all-day confirmations.
    """
    rows = list(rows or [])
    result = {}
    for meal in MEALS:
        pending = sum(row.get(meal) not in ACTUAL_STATES | {"不供餐"} for row in rows)
        actual = sum(row.get(meal) == "已就餐" for row in rows)
        known = sum(row.get(meal) in ACTUAL_STATES for row in rows)
        complete = bool(rows) and not pending
        no_service = bool(rows) and all(row.get(meal) == "不供餐" for row in rows)
        result[meal] = {
            "expected": sum(int(row.get(meal + "_expected") or 0) for row in rows),
            "actual": actual if complete else None, "confirmed_subtotal": actual,
            "pending_count": pending, "student_count": len(rows), "complete": complete,
            "status": ("无学生" if not rows else "不供餐" if no_service else
                       "已确认" if complete else "部分确认" if known else "未确认"),
        }
    return result


def meal_counts(rows, expected=False):
    return {meal + "_count": facts["expected" if expected else "actual"]
            for meal, facts in meal_facts(rows).items()}


def planning_counts(rows):
    """Per-meal operational counts: actual when complete, otherwise expected.

    This intentionally is not an actual-count API. Procurement and provisional
    daily totals still need estimates for meals which have not happened yet.
    """
    return {meal + "_count": facts["actual"] if facts["complete"] else facts["expected"]
            for meal, facts in meal_facts(rows).items()}


def _whole_day_status(rows, day):
    complete = all(facts["complete"] for facts in meal_facts(rows).values())
    return "已确认" if complete and getdate(day) <= getdate(nowdate()) else "待确认"


def _changed_confirmed_values(old, doc):
    if not old:
        return False
    original = {row.student: row for row in old.students}
    return any(previous.get(meal) in ACTUAL_STATES and
               (previous.get(meal) != row.get(meal) or previous.get(meal + "_expected") != row.get(meal + "_expected"))
               for row in doc.students if (previous := original.get(row.student))
               for meal in MEALS)


def validate(doc):
    _editor(doc.student_group)
    old = doc.get_doc_before_save()
    if old and (str(getdate(old.meal_date)) != str(getdate(doc.meal_date)) or old.student_group != doc.student_group):
        frappe.throw("不能更改就餐记录的日期或班级")
    locked = frappe.db.get_value("Tongjianyun Daily Meal Confirmation", {"meal_date": doc.meal_date}, "status", for_update=True)
    if locked == "已锁定":
        frappe.throw("该日已锁定，不能修改就餐记录")
    if doc.status not in {"待确认", "已确认"}:
        frappe.throw("无效的确认状态")
    has_actual = any(row.get(meal) in ACTUAL_STATES for row in doc.students for meal in MEALS)
    if (doc.status == "已确认" or has_actual) and getdate(doc.meal_date) > getdate(nowdate()):
        frappe.throw("未来日期只能保存预计人数，不能确认实际就餐")
    if old and (old.status == "已确认" or _changed_confirmed_values(old, doc)) and not str(doc.change_reason or "").strip():
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
    # The legacy class-day status remains binary for old consumers. It is an
    # aggregate, not an instruction to reset the other four meals.
    doc.status = _whole_day_status(doc.students, doc.meal_date)
    doc.confirmed_by = frappe.session.user if doc.status == "已确认" else None
    doc.confirmed_at = now_datetime() if doc.status == "已确认" else None


@frappe.whitelist()
def get_class_meals(meal_date=None, student_group=None):
    return _get_class_meals(meal_date, student_group)


def _get_class_meals(meal_date=None, student_group=None, *, source_observer=None):
    if source_observer is not None and not callable(source_observer):
        raise TypeError('Class meal source observer must be callable')
    frappe.has_permission(DOCTYPE, "read", throw=True)
    scope = allowed_groups()
    groups = [{"name": g, "label": frappe.db.get_value("Student Group", g, "student_group_name") or g} for g in scope]
    if not student_group:
        return {"groups": groups}
    require_group(student_group, scope)
    options = {'source_observer': source_observer} if source_observer is not None else {}
    doc = _load(meal_date or nowdate(), student_group, **options)
    if not doc.is_new():
        doc.check_permission("read")
    return {"groups": groups, "record": doc.as_dict(), "revision": "" if doc.is_new() else str(doc.modified or ""),
            "expected": meal_counts(doc.students, True), "actual": meal_counts(doc.students),
            "meals": meal_facts(doc.students)}


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
            if do_confirm:
                row.set(meal, {"就餐": "已就餐", "不就餐": "未就餐", "不供餐": "不供餐"}[value])
            elif row.get(meal) not in ACTUAL_STATES:
                # Saving an estimate must not erase a previously confirmed fact.
                row.set(meal, "不供餐" if value == "不供餐" else "未确认")
    doc.status = "已确认" if do_confirm else _whole_day_status(doc.students, meal_date)
    doc.change_reason = change_reason
    doc.save()
    return get_class_meals(meal_date, student_group)


@frappe.whitelist(methods=["POST"])
def save_class_meal(meal_date, student_group, meal, students, revision="", confirm=0, change_reason=""):
    """Save one complete class-meal, leaving the other four meals unchanged."""
    _editor(student_group)
    if meal not in MEALS or str(confirm) not in {"0", "1"}:
        frappe.throw("请选择有效餐次及确认方式")
    students = frappe.parse_json(students) if isinstance(students, str) else students
    if not isinstance(students, list) or not students or not all(isinstance(row, dict) for row in students):
        frappe.throw("请提交完整的班级餐次名单")
    if any(set(row) - {"student", "value"} or not isinstance(row.get("student"), str)
           or not isinstance(row.get("value"), str) or row["value"] not in {"就餐", "不就餐", "不供餐"}
           for row in students):
        frappe.throw("餐次只接受学生编号及就餐安排，不能混入其他餐次")
    name = record_name(meal_date, student_group)
    if frappe.db.exists(DOCTYPE, name):
        frappe.db.get_value(DOCTYPE, name, "name", for_update=True)
    doc = _load(meal_date, student_group)
    doc.check_permission("create" if doc.is_new() else "write")
    if ("" if doc.is_new() else str(doc.modified or "")) != str(revision or ""):
        frappe.throw("人数已被其他人修改，请重新加载后核对")
    by_student = {row.student: row for row in doc.students}
    if len(students) != len(by_student) or {row.get("student") for row in students} != set(by_student):
        frappe.throw("提交的名单与班级名单不一致，请重新加载")
    do_confirm = str(confirm) == "1"
    if do_confirm and getdate(meal_date) > getdate(nowdate()):
        frappe.throw("未来日期只能保存预计人数，不能确认实际就餐")
    for entry in students:
        row, value = by_student[entry["student"]], entry["value"]
        if not do_confirm:
            row.set(meal + "_expected", int(value == "就餐"))
        if do_confirm:
            row.set(meal, {"就餐": "已就餐", "不就餐": "未就餐", "不供餐": "不供餐"}[value])
        elif row.get(meal) not in ACTUAL_STATES:
            row.set(meal, "不供餐" if value == "不供餐" else "未确认")
    doc.status = _whole_day_status(doc.students, meal_date)
    doc.change_reason = change_reason
    doc.save()
    # Existing Frappe history retains before/after values and the acting user.
    # This marker identifies which meal was confirmed without another schema.
    if do_confirm:
        doc.add_comment("Info", text=LABELS[meal] + "实际就餐已按班级名单核对；每日汇总自动更新。")
    return get_class_meals(meal_date, student_group)


def apply_class_snapshots(rows, day):
    """Return confirmed counts where available, expected counts otherwise."""
    if not frappe.db.exists("DocType", DOCTYPE):
        return rows
    for row in rows:
        name = record_name(day, row["student_group"])
        if frappe.db.exists(DOCTYPE, name):
            doc = frappe.get_doc(DOCTYPE, name)
            row.update(planning_counts(doc.students))
            row["enrolled_count"] = len(doc.students)
            row["absent_count"] = sum(r.attendance_hint == "Absent" for r in doc.students)
            row["leave_count"] = sum(r.attendance_hint == "Leave" for r in doc.students)
    return rows


def all_classes_confirmed(rows, day, meal=None):
    if meal is not None and meal not in MEALS:
        frappe.throw("无效餐次")
    if not rows or not frappe.db.exists("DocType", DOCTYPE):
        return False
    nonempty = [row for row in rows if row["enrolled_count"] > 0]
    if not nonempty:
        return False
    if getdate(day) > getdate(nowdate()):
        return False
    for row in nonempty:
        name = record_name(day, row["student_group"])
        if not frappe.db.exists(DOCTYPE, name):
            return False
        facts = meal_facts(frappe.get_doc(DOCTYPE, name).students)
        if not all(facts[key]["complete"] for key in ([meal] if meal else MEALS)):
            return False
    return True


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
        for key, value in planning_counts(doc.students).items():
            counts[key] += value
    return counts
