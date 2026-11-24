"""The working days and task deadlines shared by term preview, submission and progress."""

from datetime import timedelta
import json

import frappe
from frappe.utils import getdate

from tongjianyun.canteen_ops.common import TERM, dates, linked, permission

KINDS = ("食谱审核", "准备采购", "逐餐供餐与日结", "周核销")
DAY = timedelta(days=1)


def build_weeks(start, end, holidays):
    start, end = getdate(start), getdate(end)
    groups = {}
    for offset in range((end - start).days + 1):
        day = start + offset * DAY
        if day.weekday() < 5 and day not in holidays:
            monday = day - day.weekday() * DAY
            groups.setdefault(monday, []).append(day)
    weeks = {}
    for monday, days in groups.items():
        prep = days[0] - DAY
        while prep > start and (prep.weekday() >= 5 or prep in holidays):
            prep -= DAY
        prep = max(prep, start)
        if prep.weekday() >= 5 or prep in holidays:
            prep = days[0]
        weeks[monday] = {"days": days, "due": dict(zip(KINDS, (prep, prep, days[-1], days[-1]), strict=True))}
    return weeks


def holidays_for(company, chosen, start, end):
    calendar = chosen or frappe.db.get_value("Company", company, "default_holiday_list")
    if not calendar:
        return []
    if chosen:
        linked("Holiday List", chosen)
    return frappe.get_all("Holiday", filters={"parenttype": "Holiday List", "parent": calendar,
                          "holiday_date": ["between", [start, end]]}, pluck="holiday_date")


def term_weeks(term):
    if term.get("service_holidays_snapshot"):
        holidays = json.loads(term.service_holidays_snapshot)
    else:
        holidays = holidays_for(term.company, term.get("service_holiday_list"), term.from_date, term.to_date)
    return build_weeks(term.from_date, term.to_date, {getdate(day) for day in holidays})


def freeze_calendar(term, method=None):
    holidays = holidays_for(term.company, term.service_holiday_list, term.from_date, term.to_date)
    term.service_holidays_snapshot = json.dumps(sorted(map(str, holidays)))
    if not term_weeks(term):
        frappe.throw("所选学期没有供餐日，请核对学期日期和停餐日历。")


@frappe.whitelist(methods=["GET"])
def preview(company, from_date, to_date, holiday_list=None):
    permission(frappe.has_permission(TERM, "read") or frappe.has_permission(TERM, "create"))
    linked("Company", company)
    dates(from_date, to_date)
    holidays = holidays_for(company, holiday_list, from_date, to_date)
    weeks = build_weeks(from_date, to_date, {getdate(day) for day in holidays})
    return {"weeks": [{"monday": monday, "first": data["days"][0], "last": data["days"][-1],
                       "steps": [{"kind": k, "due": due} for k, due in data["due"].items()]}
                      for monday, data in weeks.items()]}
