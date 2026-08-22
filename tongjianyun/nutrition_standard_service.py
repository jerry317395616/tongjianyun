from __future__ import annotations

from typing import Any, Mapping

from tongjianyun.nutrition_rules import NUTRIENT_UNITS, REFERENCE_NUTRIENT_KEYS


OFFICIAL_SOURCE = "DB4403/T 489—2024《0岁～6岁儿童营养配餐指南》"
OFFICIAL_URL = "https://amr.sz.gov.cn/attachment/1/1478/1478779/11504298.pdf"
NUTRIENT_LABELS = {
    "energy": "热量",
    "protein": "蛋白质",
    "calcium": "钙",
    "iron": "铁",
    "zinc": "锌",
    "vitamin_a": "维生素A",
    "vitamin_b1": "维生素B1",
    "vitamin_b2": "维生素B2",
    "vitamin_c": "维生素C",
}


def standard_profile(
    age_group: str,
    gender: str,
    rule_set: Mapping[str, Any] | None = None,
) -> tuple[dict[str, float], str]:
    config = dict(rule_set or _get_active_rule_set())
    reference = config["reference_standards"]
    ages = (
        ["4", "5"]
        if age_group == "4–5岁平均"
        else ["4" if str(age_group).startswith("4") else "5"]
    )
    genders = (
        ["男", "女"]
        if gender == "男女平均"
        else [gender if gender in {"男", "女"} else "男"]
    )
    selected = [reference[age][selected_gender] for age in ages for selected_gender in genders]
    standard = {
        key: sum(float(item[key]) for item in selected) / len(selected)
        for key in REFERENCE_NUTRIENT_KEYS
    }
    return standard, f"{age_group}·{gender}"


def explain_nutrition_standard(
    metric: str = "energy",
    age_group: str = "4–5岁平均",
    gender: str = "男女平均",
    garden_ratio: float = 80,
) -> dict[str, Any]:
    if metric not in REFERENCE_NUTRIENT_KEYS:
        raise ValueError(f"不支持的全天营养标准指标：{metric}")
    ratio_percent = float(garden_ratio or 80)
    if ratio_percent < 30 or ratio_percent > 100:
        raise ValueError("园内供给目标应设置在 30%–100% 之间")

    config = _get_active_rule_set()
    ages = (
        ["4", "5"]
        if age_group == "4–5岁平均"
        else ["4" if str(age_group).startswith("4") else "5"]
    )
    genders = (
        ["男", "女"]
        if gender == "男女平均"
        else [gender if gender in {"男", "女"} else "男"]
    )
    components = [
        {
            "age_years": int(age),
            "gender": selected_gender,
            "value": float(config["reference_standards"][age][selected_gender][metric]),
        }
        for age in ages
        for selected_gender in genders
    ]
    full_day = sum(item["value"] for item in components) / len(components)
    garden_target = full_day * ratio_percent / 100
    values = " + ".join(_display_number(item["value"]) for item in components)
    full_expression = (
        _display_number(full_day)
        if len(components) == 1
        else f"({values}) ÷ {len(components)}"
    )
    return {
        "metric": metric,
        "metric_label": NUTRIENT_LABELS[metric],
        "unit": NUTRIENT_UNITS[metric],
        "profile": f"{age_group}·{gender}",
        "components": components,
        "calculation": {
            "method": "所选年龄和性别参考值的算术平均",
            "full_day_expression": full_expression,
            "full_day_standard": full_day,
            "garden_ratio_percent": ratio_percent,
            "garden_expression": (
                f"{_display_number(full_day)} × {_display_number(ratio_percent)}%"
            ),
            "garden_standard": garden_target,
        },
        "source": {"title": OFFICIAL_SOURCE, "url": OFFICIAL_URL},
        "active_rule": {
            "rule_code": config["rule_code"],
            "title": config["title"],
            "version": config["version"],
            "rule_hash": config["rule_hash"],
        },
        "answer_summary": (
            f"{age_group}、{gender}的{NUTRIENT_LABELS[metric]}全日标准为"
            f"{_display_number(full_day)} {NUTRIENT_UNITS[metric]}；"
            f"按园内供给比例{_display_number(ratio_percent)}%，园内目标为"
            f"{_display_number(garden_target)} {NUTRIENT_UNITS[metric]}。"
        ),
    }


def get_weekly_nutrition_analysis_context(
    recipe: str | None = None,
    age_group: str = "4–5岁平均",
    gender: str = "男女平均",
    garden_ratio: float = 80,
) -> dict[str, Any]:
    from tongjianyun.nutrition_sheet import get_nutrition_sheet

    sheet = get_nutrition_sheet(recipe, age_group, gender, garden_ratio)
    analysis = sheet["analysis"]
    return {
        "recipe": sheet["recipe"],
        "filters": sheet["filters"],
        "day_count": analysis["day_count"],
        "nutrients": analysis["nutrients"],
        "nutrient_evaluations": analysis["nutrient_evaluations"],
        "macro_energy_ratio": analysis["macro_energy_ratio"],
        "meal_ratio": analysis["meal_ratio"],
        "ingredient_count": len(analysis.get("ingredients") or []),
        "ingredients": (analysis.get("ingredients") or [])[:30],
        "calculation_rule": analysis["calculation_rule"],
        "conclusion": analysis["conclusion"],
        "calculation_method": (
            "按食谱日期汇总每种食材带量；各营养值按每100克代表值×克数÷100÷天数"
            "×可食部比例×烹调保留率计算，再按当前规则阈值评价。"
        ),
    }


def _display_number(value: float) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _get_active_rule_set() -> dict[str, Any]:
    from tongjianyun.nutrition_rule_service import get_active_rule_set

    return get_active_rule_set()
