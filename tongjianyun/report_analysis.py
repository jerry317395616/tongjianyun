"""Read-only analysis of ERP meal plans; category estimates never certify compliance."""
import math

import frappe
from frappe.utils import escape_html

from tongjianyun.analysis_engine import analyze
from tongjianyun.nutrition_reference import FULL_DAY_REFERENCE, NUTRIENT_UNITS, OFFICIAL_SOURCE, REFERENCE_NUTRIENTS
from tongjianyun.report_sources import load_source

REFERENCE_URL = "https://amr.sz.gov.cn/attachment/1/1478/1478779/11504298.pdf"
LABELS = {"energy": "能量", "protein": "蛋白质", "fat": "脂肪", "carbohydrate": "碳水化合物", "calcium": "钙", "iron": "铁", "zinc": "锌", "vitamin_a": "维生素A", "vitamin_b1": "维生素B1", "vitamin_b2": "维生素B2", "vitamin_c": "维生素C", "vitamin_e": "维生素E", "niacin": "烟酸", "potassium": "钾", "magnesium": "镁", "phosphorus": "磷", "selenium": "硒", "carotene": "胡萝卜素", "fiber": "膳食纤维", "cholesterol": "胆固醇"}
AGE_GROUPS = {"4–5岁平均": ("4", "5"), **{f"{age}岁": (age,) for age in FULL_DAY_REFERENCE}}


def parameters(filters):
    age, gender = filters.get("age_group") or "4–5岁平均", filters.get("gender") or "男女平均"
    if age not in AGE_GROUPS or gender not in ("男女平均", "男", "女"):
        raise ValueError("请选择有效的手动年龄及性别参考参数")
    raw = filters.get("garden_ratio")
    ratio = float(80 if raw is None or raw == "" else raw)
    if not math.isfinite(ratio) or not 30 <= ratio <= 100:
        raise ValueError("园内参考比例应在30%至100%之间")
    genders = ("男", "女") if gender == "男女平均" else (gender,)
    selected = [FULL_DAY_REFERENCE[a][g] for a in AGE_GROUPS[age] for g in genders]
    reference = {key: sum(row[key] for row in selected) / len(selected) for key in REFERENCE_NUTRIENTS}
    return age, gender, ratio, reference


def execute(filters=None):
    filters = frappe._dict(filters or {})
    if frappe.session.user == "Guest":
        frappe.throw("请先登录。", frappe.AuthenticationError)
    try:
        age, gender, ratio, reference = parameters(filters)
        section = filters.get("section") or "全部"
        if section not in ("全部", "食谱结构", "营养估算", "食材带量", "待补资料"):
            raise ValueError("请选择有效的报表内容")
        source = load_source(filters)
        analysis = analyze(source["details"], source["dates"])
    except (TypeError, ValueError) as error:
        frappe.throw(str(error))
    data = []

    def add(section_name, metric, amount=None, unit="", basis="", detail="", **extra):
        if section in ("全部", section_name):
            data.append({"section": section_name, "metric": metric, "amount": amount, "unit": unit, "basis": basis, "detail": detail, **source["source"], **extra})

    plan_names = {row.get(f"plan_{i}") for row in source["weekly"] for i in range(5)} - {None, ""}
    add("食谱结构", "编排天数", analysis["day_count"], "天", "周表保存的日期")
    add("食谱结构", "有效生产计划", len(plan_names), "餐次", "当前有效周表", "已停供餐次不虚构配方需求")
    add("食谱结构", "周食材种类", analysis["food_count"], "种", "按物料编码去重", "同名不同物料保持各自编码")
    for day, count in analysis["daily_foods"].items():
        add("食谱结构", day + "食材种类", count, "种", "人均配方中的不同物料")
    add("食谱结构", "可作分类估算的记录", analysis["used_rows"], "条", f"共{analysis['line_count']}条", "记录覆盖数不是实际营养成分准确率")
    for key, amount in analysis["nutrients"].items():
        covered = analysis["coverage"][key]
        add("营养估算", LABELS[key], amount, NUTRIENT_UNITS[key], "分类代表值·已覆盖部分的每人日均粗估", "配方为毛重；可食部、烹调保留率及成品营养资料未逐食材校核，不作达标判断。", coverage=f"{covered}/{analysis['line_count']}条", reference=reference.get(key), garden_target=reference[key] * ratio / 100 if key in reference else None)
    for food in analysis["foods"]:
        add("食材带量", food["name"], float(food["daily_quantity"]), food["uom"] + "/人日", food["basis"], "周人均合计：" + food["quantity"] + " " + food["uom"], ingredient_code=food["code"])
    for row in analysis["missing"]:
        add("待补资料", row["name"], float(row["quantity"]), row["uom"] + "/人", row["reason"], row["date"] + " " + row["meal_type"], ingredient_code=row["code"])
    first, last = source["dates"][0], source["dates"][-1]
    historical = bool(source["source"].get("plan_batch"))
    message = (
        f"<p><strong>{escape_html(first)}—{escape_html(last)} 食谱分析</strong>：读取ERP当前有效食谱及每名幼儿带量。"
        + ("历史供餐人数待确认。" if historical else "人数属于周计划保存的安排。")
        + "分析不把计划人数作为实际就餐或摄入，也不把配方基准1作为人数。</p>"
        + "<p>营养量仅为分类代表值的部分粗估；缺失营养值不填零，毫升缺少密度时不当克计算。配方毛重未逐食材校核可食部与烹调变化，故不输出达标或偏低结论。</p>"
        + f'<p>手动参考：{escape_html(age)}／{escape_html(gender)}，园内参考比例{ratio:g}%；不代表实际幼儿年龄性别构成。参考列沿用<a href="{REFERENCE_URL}" target="_blank" rel="noopener noreferrer">{OFFICIAL_SOURCE}表5</a>，用于查看所选参考参数，不代表本园适用规范已认定。</p>'
    )
    summary = [
        {"label": "编排天数", "value": analysis["day_count"], "datatype": "Int", "indicator": "Blue"},
        {"label": "周食材种类", "value": analysis["food_count"], "datatype": "Int", "indicator": "Blue"},
        {"label": "分类估算覆盖记录", "value": f"{analysis['used_rows']}/{analysis['line_count']}", "datatype": "Data", "indicator": "Orange"},
        {"label": "待补资料记录", "value": len(analysis["missing"]), "datatype": "Int", "indicator": "Orange"},
    ]
    return columns(), data, message, None, summary, 1


def columns():
    return [{"fieldname": field, "label": label, "fieldtype": kind, "width": width} for field, label, kind, width in (
        ("section", "分析内容", "Data", 100), ("metric", "指标／食材", "Data", 170),
        ("amount", "计划量／部分粗估", "Float", 145), ("unit", "单位", "Data", 100),
        ("reference", "所选全天参考", "Float", 125), ("garden_target", "所选园内参考", "Float", 125),
        ("coverage", "资料覆盖", "Data", 100), ("basis", "计算依据", "Data", 290),
        ("detail", "来源与待补事项", "Data", 410), ("ingredient_code", "物料编码", "Data", 170),
    )]
