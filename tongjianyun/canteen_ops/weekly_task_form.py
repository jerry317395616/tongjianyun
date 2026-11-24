"""Read-only business records shown on the weekly meal task form."""

from collections import defaultdict

import frappe
from frappe.utils import getdate

from tongjianyun.canteen_ops.common import CANTEEN, DAY, TASK, TERM, WEEK, linked
from tongjianyun.canteen_ops.task_menus import _menu_context
from tongjianyun.canteen_ops.term_projects import _covered_by_stock
from tongjianyun.canteen_ops.term_schedule import term_weeks


def _readable(doctype, name):
    return bool(name and frappe.has_permission(doctype, "read", doc=name))


def _service_days(task, term, menu):
    if not term:
        return {"restricted": True}
    dates = term_weeks(term).get(getdate(task.week_start), {}).get("days", [])
    records = defaultdict(list)
    if dates and menu["state"] == "linked":
        for row in frappe.get_all(DAY, filters={"company": task.company, "meal_week": menu["menu"],
                "meal_date": ["in", dates], "docstatus": ["<", 2]}, fields=["name", "meal_date", "docstatus"],
                order_by="meal_date asc, name asc"):
            record = {"name": row.name, "submitted": row.docstatus == 1} if _readable(DAY, row.name) else None
            records[getdate(row.meal_date)].append(record)
    days = []
    for date in dates:
        found = records[date]
        if menu["state"] == "restricted" or None in found:
            days.append({"date": str(date), "status": "无查看权限"})
        elif len(found) > 1:
            days.append({"date": str(date), "status": "记录待核对"})
        elif found:
            days.append({"date": str(date), "status": "已日结" if found[0]["submitted"] else "待日结",
                         "record": found[0]["name"]})
        else:
            days.append({"date": str(date), "status": "待建档" if menu.get("docstatus") == 1 else "待食谱就绪"})
    return {"days": days}


def _procurement(task, week):
    if week.docstatus != 1:
        return {"status": "待食谱审核"}
    if week.material_request:
        request = frappe.db.get_value("Material Request", {"name": week.material_request, "company": task.company},
                                      ["name", "docstatus"], as_dict=True)
        if request and request.docstatus != 2:
            if not _readable("Material Request", request.name):
                return {"status": "已关联采购申请", "request": None}
            return {"status": "申请已提交" if request.docstatus else "申请草稿", "request": request.name}
    return {"status": "无需采购" if _covered_by_stock(week.procurement_snapshot) else "待生成申请"}


@frappe.whitelist(methods=["GET"])
def get_context(task):
    doc = linked(TASK, task)
    term = frappe.get_doc(TERM, doc.term_project) if _readable(TERM, doc.term_project) else None
    site_name = frappe.db.get_value(CANTEEN, doc.canteen, "canteen_name") if _readable(CANTEEN, doc.canteen) else None
    menu = _menu_context(doc)
    result = {"menu": menu, "canteen_title": site_name, "term_title": term.project_title if term else None}
    if doc.task_kind == "逐餐供餐与日结":
        result["service"] = _service_days(doc, term, menu)
    elif menu["state"] == "linked" and doc.task_kind in ("准备采购", "周核销"):
        week = frappe.get_doc(WEEK, menu["menu"])
        if doc.task_kind == "准备采购":
            result["procurement"] = _procurement(doc, week)
        else:
            result["reconciled_at"] = week.kitchen_reconciled_at if week.kitchen_reconciled else None
    return result
