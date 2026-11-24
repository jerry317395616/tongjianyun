"""Project progress from the food service records for a single canteen and term."""

from collections import defaultdict
from contextvars import ContextVar
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from json import loads

import frappe
from frappe.utils import escape_html, get_url_to_form, getdate

from tongjianyun.canteen_ops.common import (
    CANTEEN, DAY, TASK, TERM, WEEK, company_doc, linked, lock_company, permission, require, submitted,
)

_SYNCING = ContextVar("tjy_syncing_meal_tasks", default=False)
_REQUEST = "Material Request"
PROJECT_RESPONSIBLE = "custom_tjy_meal_responsible_user"
_WEEK_FIELDS = [
    "name", "week_start", "docstatus", "raw_material_warehouse", "kitchen_warehouse", "material_request",
    "procurement_snapshot", "kitchen_reconciled", "kitchen_reconciled_at",
]


def _mondays(term):
    start, end = getdate(term.from_date), getdate(term.to_date)
    monday = start - timedelta(days=start.weekday())
    return [monday + timedelta(days=7 * index) for index in range((end - monday).days // 7 + 1)]


def _source_weeks(term, mondays):
    site = frappe.db.get_value(CANTEEN, {"name": term.canteen, "company": term.company},
                               ["raw_warehouse", "kitchen_warehouse"], as_dict=True)
    if not site or not site.raw_warehouse:
        return {}
    unique_raw = frappe.db.count(CANTEEN, {
        "company": term.company, "raw_warehouse": site.raw_warehouse, "disabled": 0,
    }) == 1
    candidates = frappe.get_all(WEEK, filters={
        "company": term.company, "raw_material_warehouse": site.raw_warehouse,
        "week_start": ["in", mondays], "docstatus": ["<", 2],
    }, fields=_WEEK_FIELDS)
    ambiguous = [row.name for row in candidates if not row.kitchen_warehouse and not unique_raw]
    owners = defaultdict(set)
    if ambiguous:
        for row in frappe.get_all(TASK, filters={
            "company": term.company, "meal_week": ["in", ambiguous], "docstatus": ["<", 2],
        }, fields=["meal_week", "canteen"]):
            owners[row.meal_week].add(row.canteen)
    return {getdate(row.week_start): row for row in candidates if row.kitchen_warehouse == site.kitchen_warehouse
            or (not row.kitchen_warehouse and (unique_raw or owners[row.name] == {term.canteen}))}


def _covered_by_stock(snapshot):
    try:
        proof = loads(snapshot) if snapshot else {}
        rows = proof.get("rows")
        if not proof.get("basis_hash") or not isinstance(rows, list):
            return False
        for row in rows:
            if row.get("status") == "purchase":
                quantity = Decimal(str(row.get("purchase_qty")))
                if not quantity.is_finite() or quantity != 0:
                    return False
        return True
    except (ValueError, AttributeError, TypeError, InvalidOperation):
        return False


def _week_steps(week, confirmed, request):
    if not week:
        return [(False, label) for label in ("待编排", "待审核", "待审核", "待审核")]
    approved = week.docstatus == 1
    if not approved:
        return [(False, "待审核")] * 4
    reconciled = bool(week.kitchen_reconciled and week.kitchen_reconciled_at)
    if request:
        purchase = (True, "已生成申请")
    elif _covered_by_stock(week.procurement_snapshot):
        purchase = (True, "无需采购")
    else:
        purchase = (False, "待生成申请")
    closed_days = len(confirmed)
    return [
        (True, "已审核"), purchase,
        (closed_days == 5, f"已日结 {closed_days}/5 天"),
        (reconciled, "已核销" if reconciled else "待核销"),
    ]


def _progress(term, mondays):
    from tongjianyun.canteen_ops.safety import TASKS

    if not mondays:
        return []
    weeks = _source_weeks(term, mondays)
    week_names = [row.name for row in weeks.values()]
    requests = [row.material_request for row in weeks.values() if row.material_request]
    active_requests = set(frappe.get_all(_REQUEST, filters={
        "name": ["in", requests], "company": term.company, "docstatus": ["<", 2],
    }, pluck="name")) if requests else set()
    days = defaultdict(list)
    if week_names:
        for day in frappe.get_all(DAY, filters={
            "meal_week": ["in", week_names], "company": term.company, "docstatus": ["<", 2],
        }, fields=["name", "meal_week", "meal_date", "docstatus"]):
            days[day.meal_week].append(day)
    rows = []
    for monday in mondays:
        week = weeks.get(monday)
        request = week.material_request if week and week.material_request in active_requests else None
        kitchen_days = days[week.name] if week else []
        confirmed = {getdate(day.meal_date) for day in kitchen_days
                     if day.docstatus == 1 and 0 <= (getdate(day.meal_date) - monday).days < 5}
        steps = [{"kind": kind, "complete": complete, "status": status}
                 for (kind, _), (complete, status) in zip(TASKS, _week_steps(week, confirmed, request), strict=True)]
        rows.append(dict(monday=str(monday), week=week.name if week else None, request=request,
                         kitchen_days=[row.name for row in kitchen_days], steps=steps))
    return rows


def _visible(doctype, names):
    names = sorted(set(filter(None, names)))
    if not names or not frappe.has_permission(doctype, "read"):
        return set()
    return set(frappe.get_list(doctype, filters={"name": ["in", names]}, pluck="name", limit_page_length=0))


@frappe.whitelist(methods=["GET"])
def progress(term_project):
    term = linked(TERM, term_project)
    rows = _progress(term, _mondays(term))
    weeks = _visible(WEEK, (row["week"] for row in rows))
    requests = _visible(_REQUEST, (row["request"] for row in rows))
    days = _visible(DAY, (day for row in rows for day in row["kitchen_days"]))
    project = term.management_project
    for row in rows:
        row["week"] = row["week"] if row["week"] in weeks else None
        row["request"] = row["request"] if row["request"] in requests else None
        row["kitchen_days"] = [day for day in row["kitchen_days"] if day in days]
    return {"weeks": rows, "project": project if project in _visible("Project", [project]) else None}


def validate_project_link(doc):
    previous = doc.get_doc_before_save()
    project_name = doc.get("management_project")
    if previous and all(previous.get(field) == doc.get(field)
                        for field in ("management_project", "company", "from_date", "to_date")):
        return
    if not project_name and not (previous and previous.get("management_project")):
        return
    lock_company(doc.company)
    if previous and previous.get("management_project") and previous.management_project != project_name:
        require(not frappe.db.exists(TASK, {"term_project": doc.name, "management_task": ["is", "set"]}),
                "已有每周任务归入原项目，请保留管理项目关联。")
    if not project_name:
        return
    project = company_doc(doc, "Project", project_name)
    require(project.status != "Cancelled", "请选择有效的管理项目。")
    require(
        (not project.expected_start_date or getdate(project.expected_start_date) <= getdate(doc.from_date))
        and (not project.expected_end_date or getdate(project.expected_end_date) >= getdate(doc.to_date)),
        "管理项目日期须覆盖学期起止日期。",
    )
    require(not frappe.db.get_value(TERM, {
        "management_project": project.name, "docstatus": ["<", 2], "name": ["!=", doc.name or ""],
    }, "name", for_update=True), "该管理项目已关联其他学期膳食项目。")


def _new_project(term, *, from_term_submission=False):
    suffix = f" · {term.name}"
    return frappe.get_doc({
        "doctype": "Project", "project_name": term.project_title[:140 - len(suffix)] + suffix, "company": term.company,
        "expected_start_date": term.from_date, "expected_end_date": term.to_date,
        "percent_complete_method": "Task Completion",
        PROJECT_RESPONSIBLE: term.responsible_user,
    }).insert(ignore_permissions=from_term_submission)


def attach_management_project(term, method=None):
    # This runs after the authorized academic-term document has passed its validations.
    if not term.management_project:
        term.management_project = _new_project(term, from_term_submission=True).name


@frappe.whitelist(methods=["POST"])
def create_project(term_project):
    term = submitted(linked(TERM, term_project, "write", lock=True))
    if term.management_project:
        return {"project": company_doc(term, "Project", term.management_project).name}
    permission(frappe.has_permission("Project", "create"), "当前账号没有创建 ERPNext 项目的权限。")
    project = _new_project(term)
    term.management_project = project.name
    term.save()
    return {"project": project.name}


def _sync(term_project):
    term = frappe.get_doc(TERM, term_project, for_update=True)
    if term.docstatus != 1 or not term.management_project:
        return 0
    project = frappe.get_doc("Project", term.management_project, for_update=True)
    require(project.company == term.company and project.status != "Cancelled", "关联的管理项目须为本园所有效项目。")
    sources = frappe.get_all(TASK, filters={"term_project": term.name, "company": term.company, "canteen": term.canteen},
                             fields=["name", "week_start", "task_kind", "due_date", "docstatus", "management_task"])
    scheduled = set(_mondays(term))
    weeks = sorted({getdate(row.week_start) for row in sources if row.docstatus < 2 and getdate(row.week_start) in scheduled})
    completed = {(row["monday"], step["kind"]): step["complete"]
                 for row in _progress(term, weeks) for step in row["steps"]}
    changes = 0
    context = _SYNCING.set(True)
    try:
        for source in sources:
            key = (str(source.week_start), source.task_kind)
            if source.docstatus == 2 or getdate(source.week_start) not in scheduled:
                if not source.management_task:
                    continue
                status = "Cancelled"
            else:
                status = "Completed" if completed.get(key) else "Open"
            if source.management_task:
                task = frappe.get_doc("Task", source.management_task, for_update=True)
                require(task.project == project.name, "原生任务的管理项目归属不一致。")
                if task.status == status:
                    continue
                task.status = status
                task.progress = 100 if status == "Completed" else 0
                task.save(ignore_permissions=True)
            else:
                start = max(getdate(term.from_date), getdate(source.week_start))
                end = min(getdate(term.to_date), getdate(source.due_date))
                url = escape_html(get_url_to_form(TASK, source.name))
                task = frappe.get_doc({
                    "doctype": "Task", "project": project.name, "company": term.company,
                    "subject": f"{source.week_start} · {source.task_kind}", "status": status,
                    "exp_start_date": start, "exp_end_date": max(start, end),
                    "description": f'<a href="{url}">打开每周膳食任务</a>',
                }).insert(ignore_permissions=True)
                frappe.db.set_value(TASK, source.name, "management_task", task.name, update_modified=False)
            changes += 1
    finally:
        _SYNCING.reset(context)
    return changes


@frappe.whitelist(methods=["POST"])
def sync_management_tasks(term_project):
    term = submitted(linked(TERM, term_project, "write"))
    company_doc(term, "Project", term.management_project)
    return {"changed": _sync(term.name)}


def protect_task(doc, method=None):
    previous = doc.get_doc_before_save()
    if _SYNCING.get() or not previous:
        return
    if doc.project != previous.project or doc.status != previous.status or doc.progress != previous.progress:
        require(not frappe.db.exists(TASK, {"management_task": doc.name}), "请通过膳食业务单据更新这项任务的进度。")


def _queue(term):
    frappe.enqueue("tongjianyun.canteen_ops.term_projects._sync", queue="short", enqueue_after_commit=True,
                   term_project=term)


def queue_term(doc, method=None):
    if doc.docstatus == 1 and doc.get("management_project"):
        _queue(doc.name)


def queue_weekly_task(doc, method=None):
    if frappe.db.get_value(TERM, doc.term_project, "management_project"):
        _queue(doc.term_project)


def _queue_week(week):
    if not week or week.docstatus == 0:
        return
    monday = getdate(week.week_start)
    for name in frappe.get_all(TERM, filters={
        "company": week.company, "docstatus": 1, "management_project": ["is", "set"],
        "from_date": ["<=", monday + timedelta(days=6)], "to_date": [">=", monday],
    }, pluck="name"):
        term = frappe.get_doc(TERM, name)
        matched = _source_weeks(term, [monday]).get(monday)
        if (matched and matched.name == week.name) or (week.docstatus == 2 and frappe.db.exists(
                TASK, {"term_project": name, "week_start": monday})):
            _queue(name)


def queue_week(doc, method=None):
    _queue_week(doc)


def queue_day(doc, method=None):
    _queue_week(frappe.db.get_value(WEEK, doc.meal_week, ["name", "company", "week_start", "docstatus"], as_dict=True))


def queue_request(doc, method=None):
    week = frappe.db.get_value(WEEK, {"material_request": doc.name},
                              ["name", "company", "week_start", "docstatus"], as_dict=True)
    _queue_week(week)
