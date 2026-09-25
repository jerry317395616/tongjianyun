"""Teacher classroom workbench. No schema changes and no simulated telemetry.

All business writes delegate to existing Tongjianyun workflows or ordinary
permission-checked Student Log insertion. A scene position is never a fact.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
from dataclasses import dataclass
from datetime import date

import frappe
from frappe.utils import getdate, now_datetime, today, strip_html

from tongjianyun.attendance_scope import allowed_groups, require_group

LOG_TYPES = {"General", "Academic", "Achievement"}
STATUS_LABELS = {"Present": "已登记到园", "Absent": "缺勤", "Leave": "请假", "Unknown": "待点名"}


def require_user():
    user = frappe.session.user
    if user == "Guest" or not frappe.db.get_value("User", user, "enabled"):
        raise frappe.PermissionError("请使用已启用的账号登录")
    frappe.has_permission("Student Group", "read", throw=True)


def _day(value=None):
    try:
        text = str(value or today())
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            raise ValueError("Invalid date format")
        return date.fromisoformat(text)
    except (ValueError, TypeError):
        frappe.throw("日期格式应为 YYYY-MM-DD")


def _can(doctype, action="read"):
    return bool(frappe.db.exists("DocType", doctype) and frappe.has_permission(doctype, action))


def _groups(workspace=None):
    if workspace not in (None, "", "teacher", "business"):
        raise frappe.PermissionError("无效的工作入口")
    if workspace == "teacher":
        from tongjianyun.workspace_entry import teacher_groups
        return teacher_groups()
    return allowed_groups()


def _scope(group, workspace=None):
    require_user()
    require_group(group, _groups(workspace))
    doc = frappe.get_doc("Student Group", group)
    doc.check_permission("read")
    return doc


def _roster_members(group_doc):
    """One native active-membership order, shared by full and paged readers."""
    members = [r for r in group_doc.get("students", []) if r.get("active") and r.get("student")]
    result, seen = [], set()
    for row in sorted(members, key=lambda r: (int(r.get("group_roll_number") or 0), r.student)):
        if row.student not in seen:
            seen.add(row.student)
            result.append(row)
    return result


def _roster(group_doc):
    frappe.has_permission("Student", "read", throw=True)
    members = _roster_members(group_doc)
    if not members:
        return []
    visible = {r.name: r for r in frappe.get_list(
        "Student", filters={"name": ["in", list({r.student for r in members})], "enabled": 1},
        fields=["name", "student_name"], limit_page_length=0,
    )}
    result = []
    for row in members:
        if row.student in visible:
            result.append({"student": row.student, "student_name": visible[row.student].student_name or row.student,
                           "roll_number": row.get("group_roll_number") or None})
    return result


@dataclass(frozen=True)
class RosterPageReadSources:
    """Private exact-query dependency IDs, including the one-row lookahead."""
    group: str
    revision: str
    students: tuple[str, ...]


def _roster_page(group_doc, *, start=0, revision=None, page_size=25, source_observer=None):
    """Bounded private projection of the SAME native roster, not an HTTP API.

    Scan native active members in their original order, querying only small
    permission-filtered Student batches. An opaque cursor can resume scanning
    without rereading all previous students or exposing inaccessible IDs.
    No whole-class count is computed on later/incomplete pages.
    """
    if (type(start) is not int or start < 0 or type(page_size) is not int or not 1 <= page_size <= 50
            or source_observer is not None and not callable(source_observer)):
        raise ValueError('Invalid private roster page')
    frappe.has_permission('Student', 'read', throw=True)
    members = _roster_members(group_doc)
    current = hashlib.sha256(json.dumps([group_doc.name,
        [(r.student, r.get('group_roll_number') or None) for r in members]],
        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    if (revision is not None and revision != current) or (start and revision is None) or start > len(members):
        raise ValueError('Roster changed; request its first page again')
    scanned, collected, source_ids = 0, [], []
    while start + scanned < len(members) and len(collected) <= page_size and scanned < 500:
        count = min(page_size + 1 - len(collected), 500 - scanned)
        batch = members[start + scanned:start + scanned + count]
        rows = frappe.get_list('Student', filters={'name': ['in', [r.student for r in batch]], 'enabled': 1},
                               fields=['name', 'student_name'], limit_page_length=len(batch))
        visible = {r.name: r for r in rows}
        if len(visible) != len(rows) or not set(visible) <= {r.student for r in batch}:
            raise ValueError('Unexpected native Student projection')
        source_ids.extend(r.name for r in rows)
        for index, member in enumerate(batch, start + scanned):
            if member.student in visible:
                collected.append((index, {'student': member.student,
                    'student_name': visible[member.student].student_name or member.student}))
        scanned += len(batch)
    if len(collected) > page_size:
        more, next_index = True, collected[page_size][0]
    elif start + scanned == len(members):
        more, next_index = False, None
    else:
        more, next_index = None, start + scanned  # Visible rows beyond scan limit are UNKNOWN.
    if source_observer is not None:
        source_observer(RosterPageReadSources(group_doc.name, current, tuple(source_ids)))
    return {'rows': [r for _, r in collected[:page_size]], 'revision': current,
            'has_more': more, 'next_index': next_index, 'scan_limited': more is None,
            'visible_class_count': len(collected) if start == 0 and more is False else None}


def attendance_facts(roster, records, leaves):
    """An empty register is UNKNOWN, not Present. Cancelled rows are filtered upstream."""
    latest = {}
    for row in records:
        latest.setdefault(row["student"], row)
    leave_by_student = {}
    for row in leaves:
        leave_by_student.setdefault(row["student"], row)
    counts = {k: 0 for k in STATUS_LABELS}
    students = []
    for child in roster:
        record = latest.get(child["student"], {})
        leave = leave_by_student.get(child["student"], {})
        raw = record.get("status")
        status = "Absent" if raw == "Absent" else "Leave" if leave or raw == "Leave" else "Present" if raw == "Present" else "Unknown"
        counts[status] += 1
        students.append({**child, "status": status, "status_label": STATUS_LABELS[status],
                         "attendance_record": record.get("name"), "leave_record": leave.get("name"),
                         "source": "请假记录" if leave and status == "Leave" else "考勤登记" if raw else "尚无登记",
                         "modified": str((leave if leave and status == "Leave" else record).get("modified") or "")})
    counts["total"] = len(students)
    counts["rate"] = round(counts["Present"] / len(students) * 100, 1) if students else None
    return students, counts


@dataclass(frozen=True)
class AttendanceReadSources:
    """Private same-query read dependencies; never part of HTTP result JSON."""
    group: str
    day: str
    revision: str
    students: tuple[str, ...]
    attendance_records: tuple[str, ...]
    leave_records: tuple[str, ...]


def _attendance(group_doc, day, *, source_observer=None):
    # Only trusted Python adapters pass this private callback. Whitelisted
    # classroom endpoints do not accept or forward a source_observer parameter.
    if source_observer is not None and not callable(source_observer):
        raise TypeError('Attendance source observer must be callable')
    roster = _roster(group_doc)
    students = [r["student"] for r in roster]
    readable = _can("Student Attendance")
    records = frappe.get_list("Student Attendance", filters={"student_group": group_doc.name,
        "student": ["in", students], "date": day, "docstatus": ["!=", 2]},
        fields=["name", "student", "status", "modified"], order_by="modified desc, name desc", limit_page_length=0
    ) if students and readable else []
    leaves = frappe.get_list("Student Leave Application", filters={"student_group": group_doc.name,
        "student": ["in", students], "from_date": ["<=", day], "to_date": [">=", day],
        "mark_as_present": 0, "docstatus": ["!=", 2]}, fields=["name", "student", "modified"],
        order_by="modified desc, name desc", limit_page_length=0
    ) if students and _can("Student Leave Application") else []
    rows, counts = attendance_facts(roster, records, leaves)
    revision = hashlib.sha256(json.dumps([group_doc.name, str(day), roster, records, leaves],
        sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()
    if source_observer is not None:
        # attendance_facts chooses latest rows, but revision includes ALL rows.
        # Capture from these exact query results, never a later re-query.
        source_observer(AttendanceReadSources(
            group=group_doc.name, day=str(day), revision=revision,
            students=tuple(students), attendance_records=tuple(r['name'] for r in records),
            leave_records=tuple(r['name'] for r in leaves),
        ))
    return {"students": rows, "counts": counts, "revision": revision, "available": readable,
            "source": "Student Attendance / Student Leave Application"}


def _health_allowed():
    from tongjianyun.health_registration import ROLE, DOCTYPE
    return (frappe.session.user == "Administrator" or ROLE in frappe.get_roles()) and _can(DOCTYPE)


def health_counts(students, rows):
    current = {r["student"]: r for r in rows if r["student"] in students}
    return {"total": len(students), "registered": len(current),
            "unregistered": len(set(students) - set(current)),
            "pending": sum(r.get("review_status") != "已核对" for r in current.values()),
            "allergy_declared": sum(r.get("allergy_state") == "已登记" for r in current.values())}


def _health_summary(group, day, students):
    if not _health_allowed():
        return {"available": False, "message": "健康资料仅对专属健康管理人员开放"}
    from tongjianyun.health_registration import DOCTYPE
    rows = frappe.get_list(DOCTYPE, filters={"student_group": group, "student": ["in", students], "month": day.replace(day=1)},
        fields=["student", "review_status", "allergy_state"], limit_page_length=0) if students else []
    return {"available": True, "month": str(day.replace(day=1)), **health_counts(students, rows)}


def _meals(group, day):
    if not _can("Tongjianyun Class Meal Confirmation"):
        return {"available": False, "message": "暂无班级就餐记录查看权限"}
    from tongjianyun.student_meals import get_class_meals
    result = get_class_meals(str(day), group)
    record = result["record"]
    return {"available": True, "status": record.get("status"), "has_plan": bool(result["revision"]),
            "expected": result["expected"], "actual": result["actual"], "meals": result["meals"],
            "confirmed_at": record.get("confirmed_at"), "source": "班级已保存安排" if result["revision"] else "原膳食规则预估，尚未保存安排"}


def _schedules(group, day):
    if not _can("Course Schedule"):
        return {"available": False, "rows": []}
    rows = frappe.get_list("Course Schedule", filters={"student_group": group, "schedule_date": day},
        fields=["name", "title", "course", "room", "from_time", "to_time"], order_by="from_time asc", limit_page_length=100)
    return {"available": True, "rows": rows}


def _logs(students, day):
    if not _can("Student Log"):
        return {"available": False, "rows": []}
    # Do not expose Medical logs via this general-purpose classroom surface.
    rows = frappe.get_list("Student Log", filters={"student": ["in", students], "date": day,
        "type": ["in", sorted(LOG_TYPES)]}, fields=["name", "student", "date", "type", "log", "modified"],
        order_by="modified desc", limit_page_length=20) if students else []
    return {"available": True, "rows": [{**dict(r), "log": html.unescape(strip_html(r.get("log") or ""))[:1000]} for r in rows]}


def _capabilities(day):
    from tongjianyun.daily_meals import ATTENDANCE_EDITOR_ROLES, CONFIRMATION_DOCTYPE, attendance_write_allowed
    editor = bool(set(frappe.get_roles()) & ATTENDANCE_EDITOR_ROLES)
    confirmation = frappe.db.get_value(CONFIRMATION_DOCTYPE, {"meal_date": day}, ["name", "status"], as_dict=True)
    lock = (confirmation or {}).get("status")
    day_editable = day <= getdate(today())
    return {"attendance_write": attendance_write_allowed(day),
            "attendance_lock": lock if lock in {"已确认", "已锁定"} else None,
            "meals_write": editor and _can("Tongjianyun Class Meal Confirmation", "write") and lock != "已锁定",
            "log_create": _can("Student Log", "create") and day_editable,
            "health": _health_allowed(), "future": not day_editable}


@frappe.whitelist()
def get_overview(student_group=None, day=None, workspace=None):
    require_user()
    day = _day(day)
    names = _groups(workspace)
    groups = frappe.get_list("Student Group", filters={"name": ["in", names]}, fields=["name", "student_group_name"],
        order_by="student_group_name asc", limit_page_length=0) if names else []
    if student_group:
        require_group(student_group, names)
    group = student_group or (groups[0].name if groups else None)
    common = {"workspace": "teacher" if workspace == "teacher" else "business", "groups": groups, "day": str(day), "today": today(), "generated_at": str(now_datetime()),
              "user_label": frappe.db.get_value("User", frappe.session.user, "full_name") or "老师",
              "scene": {"mode": "illustrative", "location_connected": False, "layout_verified": False}}
    if not group:
        return {**common, "group": None}
    group_doc = _scope(group, workspace)
    attendance = _attendance(group_doc, day)
    ids = [r["student"] for r in attendance["students"]]
    return {**common, "group": {"name": group, "label": group_doc.student_group_name or group},
            "attendance": attendance, "capabilities": _capabilities(day), "meals": _meals(group, day),
            "health": _health_summary(group, day, ids), "schedule": _schedules(group, day), "logs": _logs(ids, day)}


@frappe.whitelist(methods=["POST"])
def save_attendance(student_group, day, changes, revision, workspace=None):
    doc = _scope(student_group, workspace)
    day = _day(day)
    if not _capabilities(day)["attendance_write"]:
        raise frappe.PermissionError("当前日期、确认状态或权限不允许修改考勤，请在原业务流程中核对")
    changes = frappe.parse_json(changes) if isinstance(changes, str) else changes
    if not isinstance(changes, list) or not changes or len(changes) > 500:
        frappe.throw("请提交有效的点名变更")
    # Serialise submissions from this workbench, then re-read the authoritative facts.
    frappe.db.get_value("Student Group", student_group, "name", for_update=True)
    doc = _scope(student_group, workspace)
    snapshot = _attendance(doc, day)
    if str(revision) != snapshot["revision"]:
        frappe.throw("名单或考勤已变化，请刷新后重新核对，未保存本次变更")
    members = {r["student"] for r in snapshot["students"]}
    seen, validated = set(), []
    for row in changes:
        if not isinstance(row, dict) or row.get("student") not in members or row.get("student") in seen:
            frappe.throw("存在非本班、停用或重复的学生")
        if row.get("status") not in {"Present", "Absent", "Leave"}:
            frappe.throw("出勤状态无效")
        if row["status"] == "Leave" and not str(row.get("leave_reason") or "").strip():
            frappe.throw("请填写请假原因")
        seen.add(row["student"])
        validated.append({"student_group": student_group, "student": row["student"], "status": row["status"],
                          "leave_reason": str(row.get("leave_reason") or "").strip()[:1000]})
    from tongjianyun.daily_meals import save_student_meal_attendance
    save_student_meal_attendance(str(day), validated)
    return {"saved": len(validated)}


@frappe.whitelist(methods=["POST"])
def add_record(student_group, student, day, record_type, content, workspace=None):
    group = _scope(student_group, workspace)
    day = _day(day)
    if day > getdate(today()):
        frappe.throw("不能将未来活动记为已发生")
    if student not in {r["student"] for r in _roster(group)}:
        raise frappe.PermissionError("学生不在当前可见的班级名单中")
    if record_type not in LOG_TYPES:
        frappe.throw("本页面仅支持日常、学习或成长记录，医疗资料请走专属登记")
    content = str(content or "").strip()
    if not 1 <= len(content) <= 2000:
        frappe.throw("请填写 1—2000 字的实际观察记录")
    frappe.has_permission("Student Log", "create", throw=True)
    log = frappe.new_doc("Student Log")
    log.student, log.date, log.type = student, day, record_type
    log.log = "<p>" + html.escape(content).replace("\n", "<br>") + "</p>"
    log.insert()
    return {"name": log.name}


@frappe.whitelist()
def get_health(student_group, day, workspace=None):
    group = _scope(student_group, workspace)
    if not _health_allowed():
        raise frappe.PermissionError("需要专属健康管理权限")
    from tongjianyun.health_registration import roster
    students = {r["student"] for r in _roster(group)}
    result = roster(student_group, str(_day(day)))
    # Health data is only fetched after the authorised user opens this drawer.
    keys = {"name", "student", "student_name", "history_state", "medical_history", "allergy_state",
            "allergy_history", "contact_phone", "information_source", "review_status", "modified", "inherited"}
    return {"month": result["month"], "rows": [{k: r.get(k) for k in keys} for r in result["rows"] if r["student"] in students]}


@frappe.whitelist(methods=["POST"])
def save_health(student_group, day, payload, workspace=None):
    group = _scope(student_group, workspace)
    if not _health_allowed():
        raise frappe.PermissionError("需要专属健康管理权限")
    data = frappe.parse_json(payload) if isinstance(payload, str) else payload
    if not isinstance(data, dict) or data.get("student") not in {r["student"] for r in _roster(group)}:
        raise frappe.PermissionError("学生不在当前可见的班级名单中")
    from tongjianyun.health_registration import save_registration
    return save_registration({**data, "student_group": student_group, "month": str(_day(day).replace(day=1))})


@frappe.whitelist()
def get_meals(student_group, day, workspace=None):
    """Revalidate this workspace before loading the existing meal workflow."""
    return _get_meals(student_group, day, workspace)


def _get_meals(student_group, day, workspace=None, *, source_observer=None):
    """Source-aware trusted Python read; public parameters stay unchanged."""
    if source_observer is not None and not callable(source_observer):
        raise TypeError('Class meal source observer must be callable')
    group = _scope(student_group, workspace)
    from tongjianyun.student_meals import get_class_meals, _get_class_meals
    result = (_get_class_meals(str(_day(day)), group.name, source_observer=source_observer)
              if source_observer is not None else get_class_meals(str(_day(day)), group.name))
    # The legacy response contains every account-visible class. Do not send
    # that cross-school index through the teacher workspace.
    return {key: result[key] for key in ("record", "revision", "expected", "actual", "meals")}


@frappe.whitelist(methods=["POST"])
def save_meals(student_group, day, students, revision="", confirm=0, change_reason="", workspace=None):
    group = _scope(student_group, workspace)
    day = _day(day)
    if not _capabilities(day)["meals_write"]:
        raise frappe.PermissionError("当前权限或锁定状态不允许修改就餐记录")
    from tongjianyun.student_meals import save_class_meals
    # Original workflow retains permission, revision, full-roster, future-date
    # and confirmed-change checks. No status is set in the scene renderer.
    save_class_meals(str(day), group.name, students, revision, confirm, change_reason)
    return {"saved": True}


@frappe.whitelist(methods=["POST"])
def save_meal(student_group, day, meal, students, revision="", confirm=0, change_reason="", workspace=None):
    """Same classroom scope, one actual meal; never marks attendance or other meals."""
    group = _scope(student_group, workspace)
    day = _day(day)
    if not _capabilities(day)["meals_write"]:
        raise frappe.PermissionError("当前权限或锁定状态不允许修改就餐记录")
    from tongjianyun.student_meals import save_class_meal
    save_class_meal(str(day), group.name, meal, students, revision, confirm, change_reason)
    return {"saved": True}
