from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import escape_html, flt

from tongjianyun.nutrition_population import (
	AUTO_MODE,
	build_population_standard,
	parse_student_groups,
	read_snapshot,
)
from tongjianyun.nutrition_standards import OFFICIAL_SOURCE, standard_profile
from tongjianyun.recipe_analysis import analyze_recipe_payload, classify_ingredient
from tongjianyun.nutrition_rule_service import get_active_rule_set
from tongjianyun.recipe_storage import get_recipe_detail


RECIPE_DOCTYPE = "Tongjianyun Recipe"
OFFICIAL_URL = "https://amr.sz.gov.cn/attachment/1/1478/1478779/11504294.pdf"

NUTRIENT_META = (
    ("energy", "能量", "kcal", "主食、薯类和油脂总量"),
    ("protein", "蛋白质", "g", "奶、蛋、鱼禽肉及大豆制品"),
    ("calcium", "钙", "mg", "奶及奶制品、大豆制品和水产品"),
    ("iron", "铁", "mg", "瘦肉、动物肝脏、鱼类及深色蔬菜"),
    ("zinc", "锌", "mg", "贝壳类、鱼禽肉、奶及动物内脏"),
    ("vitamin_a", "维生素A", "μg RAE", "动物肝脏、蛋类和深色蔬果"),
    ("vitamin_b1", "维生素B1", "mg", "全谷物、豆类、坚果和瘦肉"),
    ("vitamin_b2", "维生素B2", "mg", "奶、蛋、动物性食品和豆类"),
    ("vitamin_c", "维生素C", "mg", "新鲜蔬菜和水果"),
)

EXTENDED_NUTRIENTS = (
    ("fat", "脂肪", "g"),
    ("carbohydrate", "碳水化合物", "g"),
    ("potassium", "钾", "mg"),
    ("magnesium", "镁", "mg"),
    ("phosphorus", "磷", "mg"),
    ("selenium", "硒", "μg"),
    ("vitamin_e", "维生素E", "mg α-TE"),
    ("niacin", "烟酸", "mg NE"),
    ("carotene", "总胡萝卜素", "μg"),
    ("fiber", "膳食纤维", "g"),
    ("cholesterol", "胆固醇", "mg"),
)

FOOD_GROUPS = (
    ("grain", "谷薯及杂豆", ("fine_grain", "coarse_grain", "pastry", "dry_bean"), 100, 150, "增加粗细搭配，避免主食长期单一"),
    ("vegetable", "蔬菜", ("non_green_veg", "green_veg"), 150, 300, "一半以上宜为深色蔬菜，并适量搭配菌藻类"),
    ("fruit", "水果", ("fruit",), 150, 250, "每天提供新鲜水果，不以果汁替代"),
    ("animal", "畜禽肉鱼", ("meat", "liver", "fish"), 50, 75, "优先水产或禽类，每周至少提供两次水产品"),
    ("egg", "蛋类", ("egg",), 50, 50, "可分散到多餐或集中一餐提供"),
    ("dairy", "奶及奶制品", ("dairy",), 350, 500, "每天提供牛奶或相当量奶制品"),
    ("soy", "大豆及制品", ("soy",), 15, 20, "豆腐、豆干、豆浆等可同类互换"),
    ("oil", "烹调油", ("oil",), 20, 25, "少油烹调并轮换油脂种类"),
    ("water", "饮水", ("water",), 700, 800, "饮水常不写入食谱；未记录时请结合饮水安排判断"),
)

def execute(filters: dict[str, Any] | None = None):
    filters = frappe._dict(filters or {})
    recipe_name = filters.get("recipe") or _latest_recipe()
    if not recipe_name:
        frappe.throw("暂无可分析的食谱，请先在食谱计划中创建或导入食谱。")

    recipe = frappe.get_doc(RECIPE_DOCTYPE, recipe_name)
    recipe.check_permission("read")
    if recipe.is_deleted:
        frappe.throw("回收站中的食谱不能生成营养分析报表。")

    ratio_percent = flt(filters.get("garden_ratio") or 80)
    if ratio_percent < 30 or ratio_percent > 100:
        frappe.throw("园内供给目标应设置在 30%–100% 之间。")
    garden_ratio = ratio_percent / 100
    section = filters.get("section") or "全部"
    full_standard, profile_label, source, population = _resolve_standard(recipe, filters)

    payload = get_recipe_detail(recipe.name)
    active_rule_set = get_active_rule_set()
    analysis = analyze_recipe_payload(
        payload,
        standard={
            **full_standard,
            "profile": profile_label,
            "source": source,
            "garden_ratio": garden_ratio,
            "population": population,
        },
        rule_set=active_rule_set,
    )

    data: list[dict[str, Any]] = []
    chart_labels: list[str] = []
    chart_values: list[float] = []
    if section in {"全部", "营养素"}:
        _append_nutrition(data, analysis, full_standard, garden_ratio, chart_labels, chart_values)
    if section in {"全部", "食物结构"}:
        _append_food_structure(data, payload, analysis, garden_ratio)
    if section in {"全部", "餐次结构"}:
        _append_meal_structure(data, analysis)

    evaluated = [row for row in data if row.get("evaluation") in {"达标", "适宜", "接近目标", "偏低", "偏高", "需调整"}]
    compliant = [row for row in evaluated if row.get("evaluation") in {"达标", "适宜", "接近目标"}]
    attention = [row for row in evaluated if row.get("evaluation") in {"偏低", "偏高", "需调整"}]
    diversity = len(analysis.get("ingredients") or [])
    report_summary = [
        {
            "label": "统计学生",
            "value": population.get("student_count") if population else "手动估算",
            "datatype": "Int" if population else "Data",
            "indicator": "Green" if population else "Orange",
        },
        {"label": "分析天数", "value": analysis["day_count"], "datatype": "Int", "indicator": "Blue"},
        {"label": "周食材种类", "value": diversity, "datatype": "Int", "indicator": "Green" if diversity >= 25 else "Orange"},
        {"label": "日均能量(kcal)", "value": round(flt(analysis["nutrients"].get("energy")), 1), "datatype": "Float", "indicator": "Blue"},
        {"label": "达标指标", "value": f"{len(compliant)}/{len(evaluated)}", "datatype": "Data", "indicator": "Green" if len(compliant) == len(evaluated) else "Orange"},
        {"label": "需关注", "value": len(attention), "datatype": "Int", "indicator": "Red" if attention else "Green"},
    ]
    chart = None
    if chart_labels:
        chart = {
            "data": {
                "labels": chart_labels,
                "datasets": [
                    {"name": "实际达标率", "values": chart_values},
                    {"name": "目标基线", "values": [100] * len(chart_values)},
                ],
            },
            "type": "bar",
            "height": 300,
            "colors": ["#5e64ff", "#adb5bd"],
            "axisOptions": {"xAxisMode": "tick", "yAxisMode": "tick"},
        }
    message = _report_message(recipe, profile_label, ratio_percent, data, analysis)
    return _columns(), data, message, chart, report_summary, 1


def _columns() -> list[dict[str, Any]]:
    return [
        {"fieldname": "section", "label": "分析模块", "fieldtype": "Data", "width": 110},
        {"fieldname": "metric", "label": "指标", "fieldtype": "Data", "width": 170},
        {"fieldname": "reference", "label": "全天参考", "fieldtype": "Data", "width": 135},
        {"fieldname": "garden_target", "label": "园内目标", "fieldtype": "Data", "width": 135},
        {"fieldname": "actual", "label": "实际日均", "fieldtype": "Float", "precision": 2, "width": 110},
        {"fieldname": "unit", "label": "单位", "fieldtype": "Data", "width": 82},
        {"fieldname": "achievement_rate", "label": "达标率", "fieldtype": "Percent", "precision": 1, "width": 100},
        {"fieldname": "evaluation", "label": "评价", "fieldtype": "Data", "width": 90},
        {"fieldname": "detail", "label": "构成与改进建议", "fieldtype": "Data", "width": 360},
    ]


def _latest_recipe() -> str | None:
    names = frappe.get_list(
        RECIPE_DOCTYPE,
        filters={"is_deleted": 0},
        fields=["name"],
        order_by="modified desc",
        limit=1,
    )
    return names[0].name if names else None


def _standard_profile(age_group: str, gender: str) -> tuple[dict[str, float], str]:
    """Compatibility wrapper for callers that still use manual estimation."""
    return standard_profile(age_group, gender)


def _resolve_standard(recipe, filters: dict[str, Any]) -> tuple[dict[str, float], str, str, dict[str, Any] | None]:
    mode = filters.get("standard_mode") or AUTO_MODE
    groups = parse_student_groups(filters.get("student_groups"))
    if mode == AUTO_MODE:
        snapshot = read_snapshot(recipe, groups) if recipe.workflow_status in {"已发布", "已归档"} else None
        if snapshot:
            return (
                dict(snapshot["values"]),
                f"{snapshot['profile']}（已冻结）",
                snapshot.get("source") or OFFICIAL_SOURCE,
                dict(snapshot.get("population") or {}),
            )
        calculated = build_population_standard(recipe, groups)
        return (
            dict(calculated["values"]),
            str(calculated["profile"]),
            str(calculated["source"]),
            dict(calculated["population"]),
        )

    age_group = filters.get("age_group") or "4–6岁平均"
    gender = filters.get("gender") or "男女平均"
    values, profile = _standard_profile(age_group, gender)
    return values, profile, OFFICIAL_SOURCE, None


def _section_header(data: list[dict[str, Any]], section: str, title: str) -> None:
    data.append({"section": section, "metric": title, "section_header": 1})


def _append_nutrition(
    data: list[dict[str, Any]],
    analysis: dict[str, Any],
    full_standard: dict[str, float],
    garden_ratio: float,
    chart_labels: list[str],
    chart_values: list[float],
) -> None:
    _section_header(data, "营养素", "核心营养素达标情况")
    nutrients = analysis["nutrients"]
    for key, label, unit, guidance in NUTRIENT_META:
        reference = flt(full_standard[key])
        target = reference * garden_ratio
        actual = flt(nutrients.get(key))
        percent = actual / target * 100 if target else 0
        evaluation = analysis.get("nutrient_evaluations", {}).get(key, {}).get("status") or "偏低"
        if evaluation == "适宜":
            evaluation = "达标"
        detail = "达到参考范围。" if evaluation == "达标" else f"建议关注：{guidance}。"
        data.append(
            {
                "section": "营养素",
                "metric": label,
                "reference": _range_text(reference),
                "garden_target": _range_text(target),
                "actual": actual,
                "unit": unit,
                "achievement_rate": percent,
                "evaluation": evaluation,
                "detail": detail,
            }
        )
        chart_labels.append(label)
        chart_values.append(round(percent, 1))

    _section_header(data, "营养素", "宏量营养素供能结构")
    macro_labels = {
        "carbohydrate": "碳水化合物供能比",
        "fat": "脂肪供能比",
        "protein": "蛋白质供能比",
    }
    for key, (low, high) in analysis["calculation_rule"]["macro_ranges"].items():
        label = macro_labels[key]
        actual = flt(analysis["macro_energy_ratio"].get(key))
        evaluation = "适宜" if low <= actual <= high else ("偏低" if actual < low else "偏高")
        data.append(
            {
                "section": "营养素",
                "metric": label,
                "reference": f"{low}–{high}",
                "garden_target": f"{low}–{high}",
                "actual": actual,
                "unit": "%E",
                "achievement_rate": None,
                "evaluation": evaluation,
                "detail": "能量来源结构合理。" if evaluation == "适宜" else "调整主食、蛋白质食物和烹调油的比例。",
            }
        )

    protein = flt(nutrients.get("protein"))
    for label, actual, target in (
        (
            "动物性蛋白占比",
            flt(analysis.get("animal_protein")) / protein * 100 if protein else 0,
            flt(analysis["calculation_rule"]["animal_protein_target"]),
        ),
        (
            "动物性及豆类蛋白占比",
            flt(analysis.get("animal_soy_protein")) / protein * 100 if protein else 0,
            flt(analysis["calculation_rule"]["animal_soy_protein_target"]),
        ),
    ):
        data.append(
            {
                "section": "营养素",
                "metric": label,
                "reference": f"≥{target}",
                "garden_target": f"≥{target}",
                "actual": actual,
                "unit": "%",
                "achievement_rate": actual / target * 100 if target else 0,
                "evaluation": "达标" if actual >= target else "偏低",
                "detail": "优质蛋白来源充足。" if actual >= target else "增加鱼禽肉、蛋、奶或大豆制品的搭配。",
            }
        )

    _section_header(data, "营养素", "扩展营养估算（无强制目标）")
    for key, label, unit in EXTENDED_NUTRIENTS:
        data.append(
            {
                "section": "营养素",
                "metric": label,
                "reference": "—",
                "garden_target": "—",
                "actual": flt(nutrients.get(key)),
                "unit": unit,
                "achievement_rate": None,
                "evaluation": "仅估算",
                "detail": "用于趋势观察；未在当前报表口径中设置评价阈值。",
            }
        )


def _append_food_structure(
    data: list[dict[str, Any]], payload: dict[str, Any], analysis: dict[str, Any], garden_ratio: float
) -> None:
    _section_header(data, "食物结构", "食物多样性")
    weekly, daily_average, fish_days = _diversity_metrics(payload)
    for metric, actual, target, unit, detail in (
        ("每周食材种类", weekly, 25, "种", "每周食物种类宜不少于25种。"),
        ("日均食材种类", daily_average, 12, "种", "每天食物种类宜不少于12种。"),
        ("水产品供给天数", fish_days, 2, "天/周", "每周宜至少提供两次水产品。"),
    ):
        data.append(
            {
                "section": "食物结构",
                "metric": metric,
                "reference": f"≥{target}",
                "garden_target": f"≥{target}",
                "actual": actual,
                "unit": unit,
                "achievement_rate": actual / target * 100 if target else 0,
                "evaluation": "达标" if actual >= target else "偏低",
                "detail": detail,
            }
        )

    _section_header(data, "食物结构", "主要食物类别日均摄入")
    totals = analysis.get("category_totals") or {}
    ingredients = analysis.get("ingredients") or []
    for _key, label, categories, low, high, guidance in FOOD_GROUPS:
        actual = sum(flt(totals.get(category)) for category in categories)
        target_low = low * garden_ratio
        target_high = high * garden_ratio
        present = [item for item in ingredients if item.get("category") in categories]
        if not present:
            evaluation = "未记录"
            detail = f"食谱未记录该类食材；{guidance}。"
            achievement = None
        else:
            evaluation = _evaluate_range(actual, target_low, target_high)
            detail = _ingredient_detail(present)
            if evaluation != "适宜":
                detail = f"{detail}；建议：{guidance}。"
            achievement = actual / ((target_low + target_high) / 2) * 100
        data.append(
            {
                "section": "食物结构",
                "metric": label,
                "reference": _range_text(low, high),
                "garden_target": _range_text(target_low, target_high),
                "actual": actual,
                "unit": "g/人日" if label != "饮水" else "mL/人日",
                "achievement_rate": achievement,
                "evaluation": evaluation,
                "detail": detail,
            }
        )


def _append_meal_structure(data: list[dict[str, Any]], analysis: dict[str, Any]) -> None:
    _section_header(data, "餐次结构", "一日餐次能量分配")
    ratios = analysis.get("meal_ratio") or {}
    rows = (
        ("早餐＋早点", flt(ratios.get("breakfast")) + flt(ratios.get("morningSnack")), 30),
        ("午餐＋午点", flt(ratios.get("lunch")) + flt(ratios.get("snack")), 40),
        ("晚餐", flt(ratios.get("dinner")), 30),
    )
    for label, actual, target in rows:
        delta = actual - target
        evaluation = "接近目标" if abs(delta) <= 5 else "需调整"
        data.append(
            {
                "section": "餐次结构",
                "metric": label,
                "reference": f"约{target}",
                "garden_target": f"约{target}",
                "actual": actual,
                "unit": "%",
                "achievement_rate": actual / target * 100 if target else 0,
                "evaluation": evaluation,
                "detail": "与3:4:3餐次结构接近。" if evaluation == "接近目标" else f"较目标{'高' if delta > 0 else '低'}{abs(delta):.1f}个百分点，请调整该餐次菜品或带量。",
            }
        )


def _evaluate_range(actual: float, low: float, high: float) -> str:
    if low == high:
        low, high = low * 0.9, high * 1.1
    if actual < low:
        return "偏低"
    if actual > high:
        return "偏高"
    return "适宜"


def _range_text(low: float, high: float | None = None) -> str:
    if high is None or abs(flt(low) - flt(high)) < 0.0001:
        return f"{flt(low):.2f}".rstrip("0").rstrip(".")
    return f"{flt(low):.1f}–{flt(high):.1f}"


def _ingredient_detail(items: list[dict[str, Any]]) -> str:
    sorted_items = sorted(items, key=lambda item: flt(item.get("grams")), reverse=True)
    values = [f"{item.get('name')} {flt(item.get('grams')):.1f}g" for item in sorted_items[:8]]
    if len(sorted_items) > 8:
        values.append(f"等{len(sorted_items)}种")
    return "、".join(values)


def _diversity_metrics(payload: dict[str, Any]) -> tuple[int, float, int]:
    weekly: set[str] = set()
    daily_counts: list[int] = []
    fish_days = 0
    for day in payload.get("days") or []:
        names: set[str] = set()
        has_fish = False
        for portion in day.get("portions") or []:
            for row in portion.get("dishIngredientRows") or []:
                name = " ".join(str(row.get("ingredient") or "").split())
                if not name:
                    continue
                names.add(name)
                category, _display = classify_ingredient(name)
                if category == "fish":
                    has_fish = True
        weekly.update(names)
        daily_counts.append(len(names))
        fish_days += int(has_fish)
    daily_average = sum(daily_counts) / len(daily_counts) if daily_counts else 0
    return len(weekly), daily_average, fish_days


def _report_message(
    recipe: Any,
    profile: str,
    ratio_percent: float,
    data: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> str:
    title = escape_html(recipe.title or recipe.name)
    week_start = escape_html(str(recipe.week_start or "—"))
    week_end = escape_html(str(recipe.week_end or "—"))
    attention = [
        f"{row.get('metric')}（{row.get('evaluation')}）"
        for row in data
        if row.get("evaluation") in {"偏低", "偏高", "需调整"}
    ]
    if attention:
        summary = f"需优先关注：{'、'.join(attention[:8])}{'等' if len(attention) > 8 else ''}。"
    else:
        summary = "当前所选模块未发现需要调整的指标。"
    conclusion = escape_html(summary)
    population = analysis.get("standard", {}).get("population")
    population_line = ""
    if population:
        groups = "、".join(str(group) for group in population.get("groups") or []) or "全部启用班级"
        composition = "、".join(
            f"{item.get('label')} {item.get('count')}人"
            for item in population.get("composition") or []
        ) or "—"
        population_line = (
            f"<br>统计范围：{escape_html(groups)}；共 {flt(population.get('student_count')):.0f} 名学生。"
            f"年龄性别构成：{escape_html(composition)}。"
        )
    rule = analysis.get("calculation_rule") or {}
    rule_label = escape_html(f"{rule.get('title') or '默认营养计算规则'}（{rule.get('version') or '1.0'}）")
    return f"""
        <div style="padding:12px 14px;border:1px solid var(--border-color);border-radius:8px;background:var(--subtle-fg);">
            <div style="font-weight:700;margin-bottom:5px;">{title}｜{week_start} 至 {week_end}</div>
            <div style="color:var(--text-muted);line-height:1.7;">
                评价口径：{escape_html(profile)}，园内供给目标 {ratio_percent:.0f}%。
                参考 <a href="{OFFICIAL_URL}" target="_blank" rel="noopener">{OFFICIAL_SOURCE}</a>。
                {population_line}
                主要食物类别的园内目标按全天建议范围 × 供给比例估算。
                营养含量采用食材分类均值估算，计算规则为 {rule_label}；
                适合食谱编制阶段筛查；正式营养评估应结合准确食物成分、可食部、烹调损耗与实际摄入量。
            </div>
            <div style="margin-top:6px;">系统结论：{conclusion}</div>
        </div>
    """
