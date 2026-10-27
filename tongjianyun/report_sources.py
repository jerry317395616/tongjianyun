"""Read the same authorized, current ERP source as the native weekly menu report."""
import frappe


def load_source(filters):
    from ione_core.meal_plan_reports import resolve_report_filters
    from ione_core.meal_planning import ingredient_report_data, weekly_report_data

    filters = resolve_report_filters(filters)
    _columns, weekly = weekly_report_data(filters)
    if not weekly:
        frappe.throw("暂无可查看的周食谱，请选择周开始日期、周计划或批次。")
    first = weekly[0]
    dates = [str(first[f"date_{index}"]) for index in range(5)]
    source = {"week_name": first.get("week_name"), "plan_batch": first.get("plan_batch"), "week_start": dates[0]}
    selected = {key: value for key, value in source.items() if value}
    _columns, details = ingredient_report_data(selected)
    return {"source": source, "dates": dates, "weekly": weekly, "details": details}
