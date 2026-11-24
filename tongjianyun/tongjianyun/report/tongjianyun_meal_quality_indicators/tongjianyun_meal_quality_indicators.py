import frappe
from tongjianyun.canteen_ops.desk_labels import report_labels
from frappe.utils import getdate

from tongjianyun.canteen_ops.common import CANTEEN, DAY, FINDING, SAMPLE, WEEK, linked, require
from tongjianyun.canteen_ops.meal_operations import DELIVERY, FEEDBACK, PUBLIC
from tongjianyun.canteen_ops.task_menus import WeekMenus


def execute(filters=None):
    from ione_core.meal_adjustments import get_effective_meals
    from tongjianyun.canteen_ops.safety import sample_scope_dishes
    f = frappe._dict(filters or {})
    site = linked(CANTEEN, f.canteen)
    start, end = getdate(f.from_date), getdate(f.to_date)
    require(0 <= (end-start).days <= 366, "请选择一年以内的日期范围。")
    data = []
    def metric(title, numerator, denominator, unit):
        data.append(dict(metric=title, numerator=numerator, denominator=denominator, unit=unit,
                         rate=round(100*numerator/denominator, 2) if denominator else None))
    scope = {"company": site.company, "canteen": site.name, "docstatus": 1}
    if frappe.has_permission(FEEDBACK, "read"):
        served = plate = 0
        for name in frappe.get_list(FEEDBACK, filters={**scope, "service_date":["between",[start,end]]},
                                    pluck="name", limit_page_length=0):
            for row in linked(FEEDBACK, name).observations:
                if row.weighed:
                    served += row.served_g
                    plate += row.plate_g
        metric("称重菜品餐盘剩余率", plate, served, "克")
    if frappe.has_permission(FINDING, "read"):
        findings = frappe.get_list(FINDING, filters={"company":site.company, "canteen":site.name,
            "due_date":["between",[start,end]], "docstatus":["<",2]}, fields=["progress","due_date"], limit_page_length=0)
        metric("到期整改中仍逾期", sum(r.progress != "已销项" and getdate(r.due_date)<getdate() for r in findings),
               len([r for r in findings if getdate(r.due_date)<getdate()]), "项")
    served = planned = samples = expected = 0
    internal_access = frappe.has_permission(WEEK, "read") and frappe.has_permission(DAY, "read")
    external_access = frappe.has_permission(PUBLIC, "read") and frappe.has_permission(DELIVERY, "read")
    if internal_access:
        weeks = frappe.get_list(WEEK, filters={"company":site.company,"docstatus":1,"week_start":["<=",end],
                                "week_end":[">=",start]}, fields=["name","week_start"], limit_page_length=0)
        if weeks:
            menus = WeekMenus(site.company, {getdate(w.week_start) for w in weeks})
        for w in weeks:
            source = menus.match(site.name, getdate(w.week_start))[0]
            if not source or source.name != w.name:
                continue
            week = linked(WEEK, w.name)
            slots = {(getdate(r.meal_date),r.meal_type) for r in get_effective_meals(week)
                     if not r.service_suspended and start <= getdate(r.meal_date) <= min(getdate(),end)}
            planned += len(slots)
            for name in frappe.get_list(DAY, filters={"meal_week":w.name,"docstatus":["<",2],
                    "meal_date":["between",[start,end]]}, pluck="name", limit_page_length=0):
                day = linked(DAY,name)
                for r in day.meals:
                    if not r.actual_confirmed or not r.actual_headcount or (getdate(day.meal_date),r.meal_type) not in slots:
                        continue
                    served += 1
                    if frappe.has_permission(SAMPLE, "read"):
                        dishes = sample_scope_dishes(day,week,r.meal_type)
                        found = frappe.get_list(SAMPLE, filters={**scope,"meal_day":name,"meal_type":r.meal_type},
                                               pluck="dish",limit_page_length=0)
                        expected += len(dishes)
                        samples += len(dishes.intersection(found))
    if external_access:
        from datetime import timedelta
        last = min(end, getdate())
        publications = frappe.get_list(PUBLIC, filters={**scope, "meal_week": ["is", "not set"],
            "week_start": ["between", [start - timedelta(days=6), last]]}, pluck="name", limit_page_length=0)
        for name in publications:
            menu = linked(PUBLIC, name)
            slots = {(getdate(r.service_date), r.meal_type) for r in menu.meals if start <= getdate(r.service_date) <= last}
            planned += len(slots)
            confirmed = set()
            for row in frappe.get_list(DELIVERY, filters={**scope, "publication": name, "result": "接收",
                    "service_date": ["between", [start, last]]}, fields=["name", "service_date", "meal_type"], limit_page_length=0):
                slot = (getdate(row.service_date), row.meal_type)
                if slot not in slots:
                    continue
                confirmed.add(slot)
                if frappe.has_permission(SAMPLE, "read"):
                    dishes = {r.menu for r in menu.meals if (getdate(r.service_date), r.meal_type) == slot}
                    found = frappe.get_list(SAMPLE, filters={**scope, "external_handover": row.name},
                                            pluck="external_dish", limit_page_length=0)
                    expected += len(dishes)
                    samples += len(dishes.intersection(found))
            served += len(confirmed)
    if internal_access or external_access:
        metric("计划餐次已确认实供",served,planned,"餐次")
        if frappe.has_permission(SAMPLE,"read"):
            metric("实供成品已登记留样",samples,expected,"供餐批次×品种")
    cols = [{"fieldname": k, "label": label, "fieldtype": typ, "width":width}
            for k,label,typ,width in (("metric","指标","Data",215),("numerator","分子","Float",100),
            ("denominator","分母","Float",100),("unit","单位","Data",110),("rate","比例（%）","Float",110))]
    return report_labels((cols, data, "按可读记录汇总；分母为零时比例留空。餐盘剩余仅统计已称重且有实际供出量的菜品。"))
