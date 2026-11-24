"""Resolve one weekly menu for the meal tasks sharing a canteen and Monday."""

from collections import defaultdict

import frappe
from frappe.utils import getdate

from tongjianyun.canteen_ops.common import CANTEEN, TASK, WEEK, linked, lock_company, require


OWNER = "custom_tjy_canteen"
WEEK_FIELDS = ["name", "title", "week_start", "docstatus", OWNER, "raw_material_warehouse",
               "kitchen_warehouse", "material_request", "procurement_snapshot",
               "kitchen_reconciled", "kitchen_reconciled_at"]
TASK_FIELDS = ["name", "canteen", "week_start", "docstatus", "meal_week", "menu_confirmed", "term_project"]


def compatible(week, site):
    return all(not actual or actual == configured for actual, configured in (
        (week.raw_material_warehouse, site.raw_warehouse), (week.kitchen_warehouse, site.kitchen_warehouse),
    ))


def resolve(canteen, sites, weeks, tasks):
    """Explicit ownership, then a recorded decision, then unambiguous warehouse ownership."""
    options, certain, chosen = [], [], set()
    for week in weeks:
        owners = {site.name for site in sites if compatible(week, site)}
        if week.get(OWNER):
            owners &= {week.get(OWNER)}
        decisions = {row.canteen for row in tasks if row.meal_week == week.name
                     and (row.docstatus == 1 or row.menu_confirmed)}
        if decisions:
            owners &= decisions
        if canteen not in owners:
            continue
        options.append(week)
        if owners == {canteen}:
            certain.append(week)
            if decisions == {canteen}:
                chosen.add(week.name)
    selected = next((week for week in certain if week.name in chosen), None) if len(chosen) == 1 else None
    if not chosen and len(options) == len(certain) == 1:
        selected = certain[0]
    return selected, options


def _rows(doctype, filters, fields, lock):
    if lock:
        return frappe.qb.get_query(doctype, filters=filters, fields=fields, order_by="name asc",
                                   for_update=True, ignore_permissions=True).run(as_dict=True)
    return frappe.get_all(doctype, filters=filters, fields=fields, order_by="name asc")


class WeekMenus:
    def __init__(self, company, mondays, *, lock=False, exclude=None):
        if lock:
            lock_company(company)
        self.sites = _rows(CANTEEN, {"company": company, "disabled": 0},
                           ["name", "raw_warehouse", "kitchen_warehouse"], False)
        self.weeks = defaultdict(list)
        self.tasks = defaultdict(list)
        scope = {"company": company, "week_start": ["in", list(mondays)], "docstatus": ["<", 2]}
        for row in _rows(WEEK, scope, WEEK_FIELDS, lock):
            if row.name != exclude:
                self.weeks[getdate(row.week_start)].append(row)
        for row in _rows(TASK, scope, TASK_FIELDS, lock):
            self.tasks[getdate(row.week_start)].append(row)

    def match(self, canteen, monday):
        return resolve(canteen, self.sites, self.weeks[monday], self.tasks[monday])

    def apply(self, monday, *, confirmation=None):
        rows = self.tasks[monday]
        if confirmation:
            canteen, name = confirmation
            for row in rows:
                if row.docstatus == 0 and row.canteen == canteen:
                    row.meal_week, row.menu_confirmed = name, 1
                    frappe.db.set_value(TASK, row.name, {"meal_week": name, "menu_confirmed": 1},
                                        update_modified=False)
        for canteen in {row.canteen for row in rows if not row.docstatus}:
            menu, options = self.match(canteen, monday)
            possible = {w.name for w in options}
            name = menu.name if menu else None
            for row in rows:
                if row.docstatus or row.canteen != canteen:
                    continue
                # Conflicting recorded choices require explicit resolution and remain evidence until then.
                if row.meal_week != name and not (row.menu_confirmed and not name and
                        row.meal_week in possible):
                    frappe.db.set_value(TASK, row.name, {"meal_week": name, "menu_confirmed": 0},
                                        update_modified=False)


def source_weeks(term, mondays):
    if not mondays:
        return {}
    scope = WeekMenus(term.company, mondays)
    return {day: menu for day in mondays if (menu := scope.match(term.canteen, day)[0])}


def validate_week_owner(doc, method=None):
    lock_company(doc.company)
    if not doc.get(OWNER) and doc.is_new() and (doc.amended_from or doc.source_week):
        doc.set(OWNER, frappe.db.get_value(WEEK, doc.amended_from or doc.source_week, OWNER))
    previous = doc.get_doc_before_save()
    if previous and doc.get(OWNER) != previous.get(OWNER):
        require(not frappe.db.exists(TASK, {"meal_week": doc.name, "docstatus": 1}),
                "已有办理完成的任务引用此食谱，无法更改所属食堂。")
    if doc.get(OWNER):
        site = linked(CANTEEN, doc.get(OWNER))
        require(site.company == doc.company and not site.disabled and compatible(doc, site),
                "周食谱的园所和已填写的仓库须与所选食堂一致。")


def sync_menu(doc, method=None):
    if doc.flags.get("in_delete") or (method == "on_change" and doc.docstatus == 2):
        return
    previous = doc.get_doc_before_save()
    scopes = {(doc.company, getdate(doc.week_start))}
    if previous:
        scopes.add((previous.company, getdate(previous.week_start)))
    from tongjianyun.canteen_ops.term_projects import _queue
    terms = set()
    for company, monday in sorted(scopes):
        scope = WeekMenus(company, [monday], lock=True, exclude=doc.name if method == "on_trash" else None)
        scope.apply(monday)
        terms.update(row.term_project for row in scope.tasks[monday])
    for term in sorted(terms):
        _queue(term)


def _visible(week):
    return frappe.has_permission(WEEK, "read", doc=week.name)


@frappe.whitelist(methods=["GET"])
def menu_context(task):
    doc = linked(TASK, task)
    monday = getdate(doc.week_start)
    if doc.docstatus:
        menu = frappe.db.get_value(WEEK, doc.meal_week, ["name", "title", "docstatus"], as_dict=True) if doc.meal_week else None
        options = []
    else:
        scope = WeekMenus(doc.company, [monday])
        menu, options = scope.match(doc.canteen, monday)
    if menu:
        if not _visible(menu):
            return {"state": "restricted"}
        return {"state": "linked", "menu": menu.name, "title": menu.title, "docstatus": menu.docstatus}
    if doc.docstatus:
        return {"state": "historical"}
    if options:
        return {"state": "ambiguous", "options": [
            {"value": w.name, "label": f"{w.title or w.name} · {w.name}"} for w in options if _visible(w)
        ], "can_confirm": doc.has_permission("write")}
    if scope.weeks[monday]:
        return {"state": "unavailable"}
    site = next((s for s in scope.sites if s.name == doc.canteen), None)
    defaults = {"company": doc.company, OWNER: doc.canteen, "week_start": str(monday)}
    if site:
        defaults.update(raw_material_warehouse=site.raw_warehouse, kitchen_warehouse=site.kitchen_warehouse)
    return {"state": "empty", "can_create": bool(site and frappe.has_permission(WEEK, "create")),
            "defaults": defaults}


def confirm(scope, canteen, monday, name):
    linked(WEEK, name)
    selected, options = scope.match(canteen, monday)
    require(any(row.name == name for row in options) and (not selected or selected.name == name),
            "食谱归属已变更，请刷新任务后重新确认。")
    for row in scope.tasks[monday]:
        if row.canteen == canteen and not row.docstatus:
            linked(TASK, row.name, "write")
    scope.apply(monday, confirmation=(canteen, name))


@frappe.whitelist(methods=["POST"])
def confirm_menu(task, meal_week):
    doc = linked(TASK, task, "write")
    monday = getdate(doc.week_start)
    scope = WeekMenus(doc.company, [monday], lock=True)
    require(any(row.name == task and not row.docstatus and row.canteen == doc.canteen for row in scope.tasks[monday]),
            "请在未办理的本周任务中确认食谱。")
    confirm(scope, doc.canteen, monday, meal_week)
    from tongjianyun.canteen_ops.term_projects import _queue
    for term in {row.term_project for row in scope.tasks[monday]}:
        _queue(term)
