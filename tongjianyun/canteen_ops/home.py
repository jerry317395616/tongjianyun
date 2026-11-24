"""Read model for the native meal workspace. Opening it never creates business documents."""
from collections import defaultdict
from datetime import timedelta

import frappe
from frappe.utils import getdate

from ione_core import meal_kitchen
from ione_core.meal_adjustments import get_effective_meals
from tongjianyun import meal_ledger
from tongjianyun.canteen_ops import common
from tongjianyun.canteen_ops.meal_operations import PUBLIC, DELIVERY as HANDOVER
from tongjianyun.canteen_ops.task_menus import WeekMenus


def _list(dt, filters, fields, order="name asc"):
    if not frappe.has_permission(dt, "read"):
        return []
    return frappe.get_list(dt, filters=filters, fields=fields, order_by=order, limit_page_length=0)


def _form(dt, name, label):
    return dict(kind="form", doctype=dt, name=name, label=label)


def _blank(slot):
    return dict(slot=slot, menu="", planned=None, actual=None, status="未编排", action=None)


def _internal(site, monday, dates, today):
    days = {d: [] for d in dates}
    closed = set()
    if not frappe.has_permission(common.WEEK, "read"):
        return days, None, "当前账号没有周食谱查看权限。", closed
    match, options = WeekMenus(site.company, [monday]).match(site.name, monday)
    if not match or not frappe.has_permission(common.WEEK, "read", doc=match.name):
        return days, None, "本周暂无可查看的食谱。" if not options else "本周暂无已确定且可查看的食谱。", closed
    week = frappe.get_doc(common.WEEK, match.name)
    menu_action = _form(common.WEEK, week.name, "打开周食谱")
    plans = defaultdict(dict)
    for plan in get_effective_meals(week) if week.docstatus else week.meals:
        plans[str(plan.meal_date)][plan.meal_type] = plan
    tokens = defaultdict(list)
    for token in _list(common.DAY, {"company": site.company, "meal_week": week.name, "docstatus": ["<", 2]},
                       ["name", "company", "meal_date", "docstatus"]):
        tokens[str(token.meal_date)].append(token)
    proof = meal_ledger._week_proof(week) if week.docstatus else None
    may_create = (week.docstatus == 1 and week.kitchen_warehouse and frappe.has_permission(common.DAY, "create")
                  and bool(common.roles() & {"Stock User", "Stock Manager", "System Manager", "膳食业务经办员"}))
    for date in dates:
        if not plans[date]:
            continue
        multiple = len(tokens[date]) > 1
        token = tokens[date][0] if len(tokens[date]) == 1 else None
        ctx = meal_ledger._day_context(week, date, token, plans[date], proof)
        if ctx.status == meal_ledger.CLOSED_DAY:
            closed.add(date)
        writable = bool(ctx.day and not ctx.day.docstatus and ctx.day.has_permission("write"))
        for entry in meal_ledger._meals(week, ctx):
            plan = plans[date].get(entry["slot"])
            if not plan:
                days[date].append(_blank(entry["slot"]))
                continue
            stopped = bool(plan.get("service_suspended"))
            action = _form(common.WEEK, week.name, "看食谱")
            status = "已编排" if plan.menu else "待编排"
            if stopped:
                status = "已停供"
                action = dict(kind="reason", label="查看原因", reason=entry["reason"] or "食谱已标记整餐停供。")
            elif multiple or ctx.status == meal_ledger.UNVERIFIED_DAY:
                status = "待核对"
                if ctx.day:
                    action = _form(common.DAY, ctx.day.name, "查看记录")
            elif ctx.day:
                status = entry["actual_status"]
                action = _form(common.DAY, ctx.day.name, "确认供餐" if writable and entry["actual"] is None else "查看")
            elif week.docstatus and date <= today and plan.menu and may_create:
                status = "待确认"
                action = dict(kind="kitchen", label="开始登记", week=week.name, date=date)
            days[date].append(dict(slot=entry["slot"], menu=entry["reason"] if stopped else entry["menu"],
                                   planned=entry["planned"], actual=entry["actual"], status=status, action=action))
    return days, menu_action, "", closed


def _external(site, monday, dates, today):
    days = {d: [] for d in dates}
    scope = {"company": site.company, "canteen": site.name}
    pubs = _list(PUBLIC, {**scope, "week_start": monday, "docstatus": 1, "meal_week": ["is", "not set"]}, ["name"])
    if len(pubs) != 1 or not frappe.has_permission(PUBLIC, "read", doc=pubs[0].name):
        return days, None, "本周暂无可查看的园外供餐公示菜单。", set()
    pub = frappe.get_doc(PUBLIC, pubs[0].name)
    receipts = defaultdict(list)
    for row in _list(HANDOVER, {**scope, "publication": pub.name, "docstatus": 1},
                     ["name", "service_date", "meal_type", "result", "portions"]):
        receipts[str(row.service_date), row.meal_type].append(row)
    menus = defaultdict(list)
    for row in pub.meals:
        menus[str(row.service_date), row.meal_type].append(row.menu)
    menu_action = _form(PUBLIC, pub.name, "打开公示菜单")
    for (date, slot), dishes in menus.items():
        if date not in days:
            continue
        batches = receipts[date, slot]
        accepted = [r for r in batches if r.result == "接收"]
        action = menu_action
        if len(batches) == 1:
            action = _form(HANDOVER, batches[0].name, "查看交接")
        elif batches:
            action = dict(kind="handovers", label="查看交接", publication=pub.name, date=date, slot=slot)
        elif date <= today and frappe.has_permission(HANDOVER, "create"):
            action = dict(kind="handover", label="登记交接", publication=pub.name, date=date, slot=slot)
        status = "部分拒收" if accepted and len(batches) != len(accepted) else "已接收" if accepted else "已拒收" if batches else "待交接"
        days[date].append(dict(slot=slot, menu="、".join(filter(None, dishes)), planned=None,
                               actual=sum(r.portions or 0 for r in accepted) if batches else None,
                               status=status, action=action))
    for rows in days.values():
        rows.sort(key=lambda r: meal_kitchen.SLOTS.index(r["slot"]) if r["slot"] in meal_kitchen.SLOTS else 99)
    return days, menu_action, "", set()


def _day_status(rows, date, today, weekend):
    if not rows:
        return "暂无安排" if weekend else "未编排"
    states = {row["status"] for row in rows}
    if states == {"已停供"}:
        return "已停供"
    live = states - {"已停供"}
    if live <= {"已确认", "已确认零供餐", "已接收"}:
        return "已确认"
    if live & {"已拒收", "部分拒收", "待核对"}:
        return "待核对"
    if live <= {"待编排", "未编排"}:
        return "待编排"
    return "供餐中" if date == today else "待确认" if date < today else "已编排"


def _todos(site, selected, today, meals):
    cutoff = min(selected, today)
    scope = {"company": site.company, "canteen": site.name}
    user = frappe.session.user
    roles = common.roles()
    due = []
    def add(date, title, action):
        due.append(dict(date=str(date), title=title, action=action))

    if frappe.has_permission(common.FINDING, "write"):
        for r in _list(common.FINDING, {**scope, "docstatus": ["<", 2], "progress": ["in", ["待整改", "待复核"]],
                       "due_date": ["<=", cutoff]}, ["name", "finding_title", "progress", "assigned_to", "due_date"]):
            review = r.progress == "待复核"
            allowed = (r.assigned_to != user and roles & (common.REGULATORS | {"System Manager"})) if review else (r.assigned_to == user or "System Manager" in roles)
            if allowed and frappe.has_permission(common.FINDING, "write", doc=r.name):
                add(r.due_date, r.finding_title, _form(common.FINDING, r.name, "去复查" if review else "去整改"))
    for r in _list(common.TASK, {**scope, "docstatus": 0, "assigned_to": user, "due_date": ["<=", cutoff]},
                   ["name", "task_kind", "due_date", "management_task"]):
        if frappe.has_permission(common.TASK, "write", doc=r.name):
            if r.management_task and frappe.db.get_value("Task", r.management_task, "status") in ("Completed", "Cancelled"):
                continue
            add(r.due_date, r.task_kind, _form(common.TASK, r.name, "去办理"))
    if frappe.has_permission(common.RECEIVING, "read") and frappe.has_permission(common.RECEIVING, "write"):
        deliveries = _list(common.DELIVERY, {**scope, "docstatus": 1, "progress": ["in", ["配送", "到货"]],
                           "expected_on": ["<=", cutoff]}, ["name", "supplier", "expected_on"])
        if deliveries:
            # A receipt hidden by a user permission must not cause a second 'unreceived' prompt.
            receipts = {r.delivery:r for r in frappe.get_all(common.RECEIVING, filters={**scope,
                "delivery": ["in", [d.name for d in deliveries]], "docstatus": ["<", 2]}, fields=["delivery","name","docstatus"])}
            for d in deliveries:
                receipt = receipts.get(d.name)
                if receipt and (receipt.docstatus or not frappe.has_permission(common.RECEIVING, "write", doc=receipt.name)):
                    continue
                if receipt:
                    action = _form(common.RECEIVING, receipt.name, "去验收")
                elif frappe.has_permission(common.RECEIVING, "create"):
                    action = dict(kind="receive", delivery=d.name, label="扫码验收")
                else:
                    continue
                add(d.expected_on, f"{d.supplier} · 配送验收", action)
    if selected <= today:
        for meal in meals:
            action = meal["action"]
            if action and action["label"] in ("确认供餐", "开始登记", "登记交接"):
                add(selected, meal["slot"] + ("到园交接" if action["kind"] == "handover" else "供餐人数确认"), action)
    return sorted(due, key=lambda item: item["date"])


@frappe.whitelist(methods=["GET"])
def dashboard(service_date=None, company=None, canteen=None):
    today = str(getdate())
    selected = getdate(service_date or today)
    monday = selected - timedelta(days=selected.weekday())
    dates = [str(monday + timedelta(days=i)) for i in range(7)]
    sites = _list(common.CANTEEN, {"disabled": 0}, ["name", "canteen_name", "company", "service_mode"],
                  "company asc, canteen_name asc, name asc")
    companies = list(dict.fromkeys(row.company for row in sites))
    default = frappe.defaults.get_user_default("Company")
    if company:
        common.permission(company in companies)
    if canteen:
        common.permission(any(s.name == canteen and (not company or s.company == company) for s in sites))
    site = next((s for s in sites if s.name == canteen), None)
    company = company or (site.company if site else default if default in companies else next(iter(companies), None))
    site = site or next((s for s in sites if s.company == company), None)
    result = dict(sites=sites, today=today, date=str(selected), company=company, canteen=None,
                  rows=[], todos=[], days=[], menu=None, note="当前账号暂无可查看的食堂。")
    if not site:
        return result
    common.linked(common.CANTEEN, site.name)
    external = site.service_mode == "园外供餐"
    load = _external if external else _internal
    days, menu, note, closed = load(site, monday, dates, today)
    rows = days[str(selected)]
    result.update(canteen=site.name, external=external, rows=rows, menu=menu, note=note,
        todos=_todos(site, str(selected), today, rows), days=[dict(date=date, status="已日结" if date in closed else _day_status(days[date], date, today, i>=5))
        for i,date in enumerate(dates)])
    return result
