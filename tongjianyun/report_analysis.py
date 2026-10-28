"""Current ERP structure and quantities. Nutrition is generated in a private transient view."""
import frappe
from tongjianyun.analysis_engine import analyze
from tongjianyun.ai_nutrition import source_data
from tongjianyun.nutrition_layout import render_sheet
from tongjianyun.report_sources import load_source


def execute(filters=None):
    if frappe.session.user == "Guest":
        frappe.throw("请先登录。", frappe.AuthenticationError)
    source = load_source(frappe._dict(filters or {}))
    analysis = analyze(source["details"], source["dates"])
    section = (filters or {}).get("section") or "全部"
    # Old bookmarks remain usable; numerical nutrition no longer comes from this report.
    data = []

    def add(part, metric, amount=None, unit="", detail="", **extra):
        if section in ("全部", part):
            data.append({"section": part, "metric": metric, "amount": amount, "unit": unit,
                         "detail": detail, **source["source"], **extra})

    add("食谱结构", "编排天数", analysis["day_count"], "天")
    add("食谱结构", "周食材种类", analysis["food_count"], "种", "按物料编码去重")
    add("食谱结构", "原始食材明细", analysis["line_count"], "条")
    for day, count in analysis["daily_foods"].items():
        add("食谱结构", day + "食材种类", count, "种")
    for food in analysis["foods"]:
        add("食材带量", food["name"], float(food["daily_quantity"]), food["uom"] + "/人日",
            "每名幼儿计划毛重；周人均合计：" + food["quantity"] + " " + food["uom"], ingredient_code=food["code"])
    source_payload = source_data(source["details"], source["dates"], source["source"])
    message = '<div class="tjy-inline-analysis"><p class="tjy-inline-status" role="status">点击“生成AI营养分析”查看本周营养估算并下载Excel。结果临时保留15分钟。</p><div class="tjy-inline-sheet">' + render_sheet(source_payload) + '</div></div>'
    return columns(), data, message, None, [], 1


def columns():
    return [{"fieldname": name, "label": label, "fieldtype": kind, "width": width} for name, label, kind, width in (
        ("section", "分析内容", "Data", 100), ("metric", "指标／食材", "Data", 180),
        ("amount", "计划带量", "Float", 140), ("unit", "单位", "Data", 120),
        ("detail", "用量依据", "Data", 470), ("ingredient_code", "物料编码", "Data", 180))]
