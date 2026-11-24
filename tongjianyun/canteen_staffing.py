"""Read-only shift coverage analysis using the native HRMS roster and attendance."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import frappe
from frappe.utils import cint, flt, get_datetime, get_time, getdate, now_datetime

from tongjianyun import meal_ledger
from tongjianyun.canteen_ops.common import lock_company

RULE = "Tongjianyun Canteen Staffing Rule"
REPORT = "Tongjianyun Canteen Staffing Analysis"
SUMMARY, DETAIL, LOAD = "岗位汇总", "班次明细", "供餐负荷"
WEEKDAYS, EVERY_DAY = "周一至周五", "每天"
SHIFT, ATTENDANCE = "Shift Assignment", "Attendance"
ALL_MEALS = "全天五餐"
ROLLUP = ("required", "scheduled", "present", "on_leave", "absent", "partial", "pending", "conflicts")


def validate_rule(doc):
    if not doc.start_date or not doc.end_date or getdate(doc.start_date) > getdate(doc.end_date):
        frappe.throw("结束日期须晚于或等于开始日期。")
    if cint(doc.minimum_staff) <= 0:
        frappe.throw("最低配置人数须大于零。")
    if not str(doc.canteen_name or "").strip():
        frappe.throw("请填写食堂名称。")
    doc.canteen_name = doc.canteen_name.strip()
    frappe.get_doc("Company", doc.company).check_permission("read")
    department = frappe.get_doc("Department", doc.department)
    department.check_permission("read")
    if department.disabled or (department.company and department.company != doc.company):
        frappe.throw("请选择本园所启用的部门。")
    for fieldname, doctype in (("designation", "Designation"), ("shift_type", "Shift Type"),
                               ("shift_location", "Shift Location"), ("kitchen_warehouse", "Warehouse")):
        if doc.get(fieldname):
            record = frappe.get_doc(doctype, doc.get(fieldname))
            record.check_permission("read")
            if fieldname == "kitchen_warehouse" and (record.company != doc.company or record.is_group or record.disabled):
                frappe.throw("请选择本园所启用的明细厨房仓。")
    scope = linked_window(doc, getdate(doc.start_date)) if _has_time(doc.coverage_start) or _has_time(doc.coverage_end) else None
    if scope:
        shift = frappe.get_doc("Shift Type", doc.shift_type)
        start, end = time_window(getdate(doc.start_date), shift.start_time, shift.end_time)
        if scope[0] < start or scope[1] > end:
            frappe.throw("岗位覆盖时段须落在班次的开始与结束时间内。")
    if bool(doc.meal_type) != bool(doc.kitchen_warehouse):
        frappe.throw("统计供餐负荷时须同时选择厨房仓和覆盖餐次。")


def activate_rule(doc):
    lock_company(doc.company)
    filters = {"name": ("!=", doc.name), "docstatus": 1, "company": doc.company,
               "department": doc.department, "designation": doc.designation, "shift_type": doc.shift_type,
               "start_date": ("<=", doc.end_date), "end_date": (">=", doc.start_date)}
    existing = frappe.db.get_values(RULE, filters, ["shift_location"], as_dict=True, for_update=True)
    if any(not row.shift_location or not doc.shift_location or row.shift_location == doc.shift_location for row in existing):
        frappe.throw("该园所、地点及岗位已有日期重叠的班次配置。")


def time_window(day, start, end):
    begin = datetime.combine(day, get_time(start))
    finish = datetime.combine(day, get_time(end))
    if finish <= begin:
        finish += timedelta(days=1)
    return begin, finish


def _has_time(value):
    return value is not None and value != ""


def linked_window(rule, day, shift=None):
    if not _has_time(rule.coverage_start) or not _has_time(rule.coverage_end):
        frappe.throw("请填写完整的岗位覆盖时段。")
    shift = shift or frappe.get_doc("Shift Type", rule.shift_type)
    begin, end = time_window(day, rule.coverage_start, rule.coverage_end)
    shift_start, shift_end = time_window(day, shift.start_time, shift.end_time)
    if shift_end.date() != day and begin.time() < shift_start.time():
        begin += timedelta(days=1)
        end += timedelta(days=1)
    return begin, end


def _between(start, end):
    while start <= end:
        yield start
        start += timedelta(days=1)


def _list(doctype, filters, fields):
    if not frappe.has_permission(doctype, "read"):
        return []
    return frappe.get_list(doctype, filters=filters, fields=fields, limit_page_length=0)


def _doc(doctype, name):
    if not name or not frappe.db.exists(doctype, name):
        return None
    value = frappe.get_doc(doctype, name)
    return value if value.has_permission("read") else None


def _employment(employee, date):
    if employee.date_of_joining and getdate(employee.date_of_joining) > date:
        return False
    if employee.relieving_date:
        return date <= getdate(employee.relieving_date)
    return employee.status == "Active"


def _history(employees):
    result = defaultdict(list)
    if not employees:
        return result
    for dt, date_field, child in (("Employee Promotion", "promotion_date", "promotion_details"),
                                  ("Employee Transfer", "transfer_date", "transfer_details")):
        for token in _list(dt, {"employee": ("in", list(employees)), "docstatus": 1}, ["name", date_field]):
            doc = _doc(dt, token.name)
            if doc:
                for row in doc.get(child, []):
                    if row.get("fieldname") == "designation":
                        result[doc.employee].append((getdate(doc.get(date_field)), row.get("current")))
    return {employee: sorted(changes, key=lambda change: change[0]) for employee, changes in result.items()}


def _designation(employee, date, changes):
    return next((previous for effective, previous in changes.get(employee.name, []) if date < effective),
                employee.designation)


@dataclass
class Slot:
    assignment: object
    date: object
    window: tuple
    uncertain: bool = False
    conflict: bool = False


@dataclass
class StaffLine:
    data: dict
    staff: set = field(default_factory=set)
    worked: dict = field(default_factory=dict)


class Roster:
    def __init__(self, company, start, end, now):
        self.start, self.end, self.now = start, end, now
        self.slots = defaultdict(list)
        self.attendance = defaultdict(list)
        self.staff = {}
        self.shifts = {}
        self.staff_allowed = all(frappe.has_permission(dt, "read") for dt in (SHIFT, "Shift Type", "Employee"))
        self.attendance_allowed = self.staff_allowed and frappe.has_permission(ATTENDANCE, "read")
        from frappe.permissions import get_user_permissions

        restrictions = get_user_permissions(frappe.session.user)
        self.limited = any(restrictions.get(dt) for dt in ("Employee", SHIFT, ATTENDANCE))
        if not self.staff_allowed:
            return
        assignments = frappe.get_list(
            SHIFT, filters=[["company", "=", company], ["docstatus", "=", 1], ["start_date", "<=", end + timedelta(days=1)]],
            or_filters=[["end_date", "is", "not set"], ["end_date", ">=", start - timedelta(days=1)]],
            fields=["name", "employee", "department", "shift_type", "shift_location", "status", "start_date", "end_date", "modified"],
            limit_page_length=0,
        )
        employees = {row.employee for row in assignments}
        if not employees:
            return
        for row in _list("Employee", {"name": ("in", list(employees))},
                         ["name", "department", "designation", "status", "date_of_joining", "relieving_date"]):
            self.staff[row.name] = row
        self.shifts = {row.name: row for row in _list("Shift Type", {"name": ("in", list({a.shift_type for a in assignments}))},
                                                      ["name", "start_time", "end_time"])}
        if self.attendance_allowed and self.staff:
            filters = {"company": company, "employee": ("in", list(self.staff)), "docstatus": 1,
                       "attendance_date": ("between", (start - timedelta(days=1), end + timedelta(days=1)))}
            fields = ["name", "employee", "shift", "attendance_date", "status", "in_time", "out_time", "working_hours"]
            for row in _list(ATTENDANCE, filters, fields):
                self.attendance[(row.employee, getdate(row.attendance_date), row.shift)].append(row)
        self.changes = _history(self.staff)
        self._expand(assignments)

    def _expand(self, assignments):
        by_person = defaultdict(list)
        for assignment in assignments:
            employee = self.staff.get(assignment.employee)
            shift = self.shifts.get(assignment.shift_type)
            if not employee or not shift:
                continue
            first = max(self.start - timedelta(days=1), getdate(assignment.start_date))
            last = min(self.end + timedelta(days=1), getdate(assignment.end_date) if assignment.end_date
                       else self.end + timedelta(days=1))
            inactive = assignment.status != "Active"
            finished = assignment.end_date and getdate(assignment.modified) > getdate(assignment.end_date)
            for day in _between(first, last):
                if not _employment(employee, day):
                    continue
                exact = self.attendance.get((employee.name, day, assignment.shift_type))
                if inactive and not exact and (not assignment.end_date or day >= self.now.date()):
                    continue
                entry = Slot(assignment, day, time_window(day, shift.start_time, shift.end_time),
                             inactive and not finished and not exact)
                self.slots[day].append(entry)
                by_person[employee.name].append(entry)
        for entries in by_person.values():
            live = []
            for entry in sorted(entries, key=lambda slot: slot.window):
                live = [other for other in live if other.window[1] > entry.window[0]]
                for other in live:
                    other.conflict = entry.conflict = True
                live.append(entry)

    def coverage(self, rule, day):
        counts = dict.fromkeys(ROLLUP, 0)
        counts["required"] = rule.minimum_staff
        if not self.staff_allowed:
            return StaffLine(dict(counts, **dict.fromkeys(ROLLUP[1:]), plan_gap=None, actual_gap=None,
                                  status="排班权限待核对", assignments=[], attendance=[]))
        shift = self.shifts.get(rule.shift_type) or _doc("Shift Type", rule.shift_type)
        if not shift:
            return StaffLine(dict(counts, **dict.fromkeys(ROLLUP[1:]), plan_gap=None, actual_gap=None,
                                  status="班次资料待核对", assignments=[], attendance=[]))
        has_window = _has_time(rule.coverage_start) and _has_time(rule.coverage_end)
        window = linked_window(rule, day, shift) if has_window else time_window(day, shift.start_time, shift.end_time)
        status, assignments, verified, attendance = set(), [], set(), []
        worked = {}
        staff, pending_roster = set(), set()
        for entry in self.slots.get(day, []):
            assignment = entry.assignment
            employee = self.staff[assignment.employee]
            if (assignment.shift_type != rule.shift_type
                    or (rule.shift_location and assignment.shift_location != rule.shift_location)
                    or (assignment.department or employee.department) != rule.department
                    or _designation(employee, day, self.changes) != rule.designation):
                continue
            assignments.append(assignment.name)
            if entry.conflict or entry.uncertain:
                pending_roster.add(employee.name)
                if entry.conflict:
                    counts["conflicts"] += employee.name not in staff
                    status.add("排班冲突")
                else:
                    status.add("历史排班待核对")
                staff.add(employee.name)
                continue
            if employee.name in staff:
                continue
            staff.add(employee.name)
            counts["scheduled"] += 1
            rows = self.attendance.get((employee.name, day, rule.shift_type), [])
            attendance.extend(row.name for row in rows)
            if not self.attendance_allowed or (window[0] > self.now and not rows):
                continue
            outcome, hours = _attendance(rows, window, has_window)
            counts[outcome] += 1
            if outcome == "present":
                verified.add(employee.name)
            if outcome in ("present", "partial"):
                worked[employee.name] = hours
        if self.limited:
            status.add("按可见人员统计")
        if counts["pending"]:
            status.add("到岗待核对")
        if counts["absent"] or counts["partial"]:
            status.add("未完整到岗")
        plan_gap = None if self.limited or pending_roster else max(0, counts["required"] - counts["scheduled"])
        if plan_gap:
            status.add("排班缺口")
        actual_known = self.attendance_allowed and (window[0] <= self.now or bool(attendance))
        actual_gap = None
        if actual_known and window[1] <= self.now and not (self.limited or pending_roster or counts["pending"]):
            actual_gap = max(0, counts["required"] - counts["present"])
            if actual_gap:
                status.add("实际缺口")
        if not actual_known:
            counts.update(dict.fromkeys(("present", "on_leave", "absent", "partial", "pending")))
            if not self.attendance_allowed:
                status.add("考勤权限待核对")
        return StaffLine(dict(counts, plan_gap=plan_gap, actual_gap=actual_gap, status="、".join(sorted(status)),
                              assignments=sorted(set(assignments)), attendance=sorted(set(attendance))), verified, worked)


def _attendance(rows, window, has_window):
    if len(rows) != 1:
        return "pending", None
    row = rows[0]
    if row.status == "On Leave":
        return "on_leave", None
    if row.status in ("Absent", "Work From Home"):
        return "absent", None
    if row.status not in ("Present", "Half Day"):
        return "pending", None
    valid_times = row.in_time and row.out_time and get_datetime(row.in_time) < get_datetime(row.out_time)
    require_full_window = row.status == "Half Day" or has_window
    if valid_times:
        arrived, left = get_datetime(row.in_time), get_datetime(row.out_time)
        first, last = max(window[0], arrived), min(window[1], left)
        hours = max(0, (last - first).total_seconds() / 3600)
        partial = not hours or (require_full_window and (arrived > window[0] or left < window[1]))
        return ("partial" if partial else "present"), hours
    if require_full_window:
        return "pending", None
    return "present", flt(row.working_hours) if flt(row.working_hours) > 0 else None


def _column(name, label, fieldtype="Data", width=120, **kwargs):
    return dict(fieldname=name, label=label, fieldtype=fieldtype, width=width, **kwargs)


def columns(view):
    base = [_column("canteen", "食堂", width=135), _column("shift_type", "班次", "Link", options="Shift Type")]
    status = _column("status", "异常与核对", width=240)
    if view == LOAD:
        return [_column("date", "供餐日期", "Date"), *base,
                _column("meal_type", "覆盖餐次", width=96), _column("served", "已确认供餐人次", "Int"),
                _column("present", "已核实到岗人数", "Int"), _column("hours", "岗位覆盖工时", "Float", precision=2),
                _column("per_person", "人均供餐人次", "Float", precision=2),
                _column("per_hour", "每工时供餐人次", "Float", precision=2), status,
                _column("day", "厨房执行", "Link", 155, options=meal_ledger.DAY)]
    counts = zip(ROLLUP, ("需配", "已排", "到岗", "请假", "缺勤或远程", "部分覆盖", "考勤待核对", "冲突人员"), strict=True)
    suffix = "人" if view == DETAIL else "人次"
    fields = [*base, _column("designation", "岗位", "Link", options="Designation"),
              _column("department", "部门", "Link", options="Department"),
              *(_column(key, f"{label}（{suffix}）", "Int", 100) for key, label in counts),
              _column("plan_gap", f"排班缺口（{suffix}）", "Int"), _column("actual_gap", f"实际缺口（{suffix}）", "Int"), status]
    if view == SUMMARY:
        return fields + [_column("slots", "配置班次数", "Int")]
    return [_column("date", "班次日期", "Date"), *fields, _column("assignments", "排班原单", width=212),
            _column("attendance", "考勤原单", width=212), _column("rule", "配置规则", "Link", 140, options=RULE)]


def _rules(filters, start, end):
    scope = {"company": filters.company, "docstatus": 1, "start_date": ("<=", end), "end_date": (">=", start)}
    for fieldname in ("canteen_name", "shift_location", "shift_type", "designation", "department"):
        if filters.get(fieldname):
            scope[fieldname] = filters[fieldname]
    fields = ["name", "canteen_name", "department", "designation", "shift_type", "shift_location", "minimum_staff",
              "start_date", "end_date", "day_scope", "coverage_start", "coverage_end", "meal_type", "kitchen_warehouse"]
    return _list(RULE, scope, fields)


def execute(filters=None):
    filters = frappe._dict(filters or {})
    view = filters.get("view") or SUMMARY
    if view not in (SUMMARY, DETAIL, LOAD):
        frappe.throw("请选择有效的人员分析视图。")
    frappe.has_permission(RULE, "read", throw=True)
    if not filters.get("company"):
        return columns(view), [], "请选择园所。"
    frappe.get_doc("Company", filters.company).check_permission("read")
    now = now_datetime()
    start = getdate(filters.get("from_date") or now.date() - timedelta(days=6))
    end = getdate(filters.get("to_date") or now.date())
    if start > end:
        frappe.throw("结束日期须晚于或等于开始日期。")
    rules = _rules(filters, start, end)
    if not rules:
        return columns(view), [], "所选期间没有已提交的食堂岗位配置。"
    roster = Roster(filters.company, start, end, now)
    lines = []
    for rule in rules:
        dates = _between(max(start, getdate(rule.start_date)), min(end, getdate(rule.end_date)))
        for day in dates:
            if rule.day_scope == WEEKDAYS and day.weekday() >= 5:
                continue
            line = roster.coverage(rule, day)
            line.data.update(date=str(day), canteen=rule.canteen_name, shift_type=rule.shift_type,
                             designation=rule.designation, department=rule.department, shift_location=rule.shift_location,
                             rule=rule.name, meal_type=rule.meal_type, kitchen_warehouse=rule.kitchen_warehouse)
            lines.append(line)
    if view == LOAD:
        rows = _meal_load(filters.company, start, end, lines)
    elif view == SUMMARY:
        rows = _summaries(lines)
    else:
        rows = [_detail(line.data) for line in lines]
    if cint(filters.get("only_anomalies")):
        rows = [row for row in rows if row["status"]]
    rows.sort(key=lambda row: (row.get("date", ""), row["canteen"], row["shift_type"], row.get("designation", "")))
    return columns(view), rows, "报表按已提交的排班核对考勤，岗位汇总按班次计人次。到岗核对完毕后显示实际缺口。"


def _detail(data):
    return dict(data, assignment_links=data["assignments"], attendance_links=data["attendance"],
                assignments="、".join(data["assignments"]), attendance="、".join(data["attendance"]))


def _summaries(lines):
    groups = defaultdict(list)
    fields = ("canteen", "department", "designation", "shift_type", "shift_location")
    for line in lines:
        groups[tuple(line.data[field] for field in fields)].append(line.data)
    result = []
    for key, rows in groups.items():
        amounts = {name: sum(row[name] or 0 for row in rows) if all(row[name] is not None for row in rows) else None
                   for name in (*ROLLUP, "plan_gap", "actual_gap")}
        flags = {flag for row in rows if row["status"] for flag in row["status"].split("、")}
        result.append(dict(zip(fields, key), slots=len(rows), status="、".join(sorted(flags)), **amounts))
    return result


def _meal_load(company, start, end, lines):
    confirmed = {}
    if all(frappe.has_permission(dt, "read") for dt in (meal_ledger.WEEK, meal_ledger.DAY)):
        for _, contexts in meal_ledger._weeks(frappe._dict(company=company), start, end):
            for context in contexts:
                if context.proof:
                    confirmed[(context.date, context.day.kitchen_warehouse)] = context
    groups = defaultdict(list)
    for line in lines:
        data = line.data
        if data["meal_type"] and data["kitchen_warehouse"]:
            key = (data["date"], data["canteen"], data["shift_type"], data["shift_location"], data["kitchen_warehouse"])
            groups[key].append(line)
    meal_owners = defaultdict(set)
    for key, members in groups.items():
        meals = set().union(*(_covered_meals(line.data["meal_type"]) for line in members))
        for meal in meals:
            meal_owners[(key[0], key[4], meal)].add(key)
    result = []
    for (day, canteen, shift, location, warehouse), members in groups.items():
        meals = set().union(*(_covered_meals(line.data["meal_type"]) for line in members))
        context = confirmed.get((day, warehouse))
        overlap = any(len(meal_owners[(day, warehouse, meal)]) > 1 for meal in meals)
        statuses = {flag for member in members for flag in member.data["status"].split("、") if flag}
        if overlap:
            statuses.add("供餐归属重叠")
        elif not context:
            statuses.add("供餐人次待核对")
        served = None
        if context and not overlap:
            served = sum(row["actual_headcount"] for row in context.proof["actual_meals"] if row["meal_type"] in meals)
        staff = set().union(*(member.staff for member in members))
        worked = {employee: hours for member in members for employee, hours in member.worked.items()}
        fully_known = all(member.data["actual_gap"] is not None for member in members)
        present = len(staff) if fully_known else None
        hours = sum(worked.values()) if fully_known and worked and all(value is not None for value in worked.values()) else None
        result.append(dict(date=day, canteen=canteen, shift_type=shift, shift_location=location,
                           meal_type="、".join(slot for slot in meal_ledger.meal_kitchen.SLOTS if slot in meals),
                           day=context.day.name if context else None, served=served, present=present, hours=hours,
                           per_person=served / present if served is not None and present else None,
                           per_hour=served / hours if served is not None and hours else None,
                           status="、".join(sorted(statuses))))
    return result


def _covered_meals(value):
    return set(meal_ledger.meal_kitchen.SLOTS) if value == ALL_MEALS else {value}
