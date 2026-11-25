"""Dates shared by menu editing, task progress and kitchen reconciliation."""
from datetime import timedelta

import frappe
from frappe.utils import getdate

from tongjianyun.canteen_ops.common import CANTEEN, TERM
from tongjianyun.canteen_ops.term_schedule import term_weeks


def scheduled_dates(week):
    start = getdate(week.week_start)
    dates = {start + timedelta(days=i) for i in range(5)}
    site = week.get("custom_tjy_canteen")
    if not site:
        from tongjianyun.canteen_ops.task_menus import compatible
        options = frappe.get_all(CANTEEN, filters={"company": week.company, "disabled": 0},
                                 fields=["name", "raw_warehouse", "kitchen_warehouse"])
        owners = [row.name for row in options if compatible(week, row)]
        if len(owners) != 1:
            return dates
        site = owners[0]
    terms = frappe.get_all(TERM, filters={"company": week.company, "canteen": site, "docstatus": 1,
        "from_date": ["<=", max(dates)], "to_date": [">=", start]}, pluck="name")
    if not terms:
        return dates
    return {day for name in terms for day in term_weeks(frappe.get_doc(TERM, name)).get(start, {}).get("days", [])}


def apply_calendar(week, method=None):
    if week.docstatus != 0 or not week.meals:
        return
    dates = scheduled_dates(week)
    for row in week.meals:
        if getdate(row.meal_date) not in dates:
            row.service_suspended = 1
            row.suspension_reason = "学期供餐日历停供"


def effective_dates(week, lock=False):
    from tongjianyun.meal_adjustments import get_effective_meals

    return {getdate(row.meal_date) for row in get_effective_meals(week, lock=lock) if not row.service_suspended}


def task_dates(week, planned):
    return set(planned) & effective_dates(week) if week and week.docstatus == 1 else set(planned)


class CalendarWeek:
    def meal_service_dates(self):
        return scheduled_dates(self)
