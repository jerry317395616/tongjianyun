"""Authenticated report downloads and shared data for the signed assistant bridge."""

from datetime import date
from urllib.parse import urlencode

import frappe
from frappe.desk.query_report import get_report_doc

from tongjianyun.report_sources import load_source
from tongjianyun.weekly_nutrition_sheet import build_sheet_data, workbook_bytes


def report_data(week_start, week_name=None, plan_batch=None):
    if frappe.session.user == "Guest":
        frappe.throw("请先登录。", frappe.AuthenticationError)
    get_report_doc("Weekly Recipe Nutrition Analysis")
    try:
        start = date.fromisoformat(week_start)
        if start.isoformat() != week_start or start.weekday() != 0:
            raise ValueError
    except (ValueError, TypeError):
        frappe.throw("请选择有效的星期一作为周开始日期。")
    if week_name and plan_batch:
        frappe.throw("请选择周食谱或生产计划批次中的一种。")
    for value in (week_name, plan_batch):
        if value is not None and (
            not isinstance(value, str)
            or len(value) > 140
            or not value.strip()
            or any(ord(c) < 32 for c in value)
        ):
            frappe.throw("食谱选择无效。")
    source = load_source(
        {"week_start": week_start, "week_name": week_name, "plan_batch": plan_batch}
    )
    if source["dates"][0] != week_start:
        frappe.throw("食谱与所选周开始日期不一致。")
    return build_sheet_data(source["details"], source["dates"], source["source"])


def download_url(data):
    args = {
        key: data["source"][key]
        for key in ("week_start", "week_name", "plan_batch")
        if data["source"].get(key)
    }
    return "/api/method/tongjianyun.weekly_nutrition_api.download?" + urlencode(args)


@frappe.whitelist(methods=["GET"])
def download(week_start, week_name=None, plan_batch=None):
    data = report_data(week_start, week_name, plan_batch)
    frappe.local.response.filename = "meal-analysis-" + week_start + ".xlsx"
    frappe.local.response.filecontent = workbook_bytes(data)
    frappe.local.response.type = "download"
    frappe.local.response_headers = {
        **(getattr(frappe.local, "response_headers", {}) or {}),
        "Cache-Control": "private, no-store, max-age=0",
        "X-Content-Type-Options": "nosniff",
    }
