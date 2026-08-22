from __future__ import annotations

import re
from typing import Any

from tongjianyun.nutrition_standards import (
    FULL_DAY_REFERENCE,
    OFFICIAL_SOURCE,
    REFERENCE_NUTRIENTS,
)


OFFICIAL_URL = "https://amr.sz.gov.cn/attachment/1/1478/1478779/11504294.pdf"
AUTO_MODE = "自动（按学生档案）"
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
NUTRIENT_UNITS = {
    "energy": "kcal",
    "protein": "g",
    "calcium": "mg",
    "iron": "mg",
    "zinc": "mg",
    "vitamin_a": "μg RAE",
    "vitamin_b1": "mg",
    "vitamin_b2": "mg",
    "vitamin_c": "mg",
}


def explain_nutrition_standard(
    metric: str = "energy",
    recipe: str | None = None,
    standard_mode: str = AUTO_MODE,
    student_groups: list[str] | None = None,
    age_group: str = "4–6岁平均",
    gender: str = "男女平均",
    garden_ratio: float = 80,
) -> dict[str, Any]:
    if metric not in REFERENCE_NUTRIENTS:
        raise ValueError(f"不支持的全天营养标准指标：{metric}")

    requested_standard_mode = standard_mode
    fallback_reason = None
    try:
        sheet = _get_nutrition_sheet(
            recipe,
            standard_mode,
            student_groups,
            age_group,
            gender,
            garden_ratio,
        )
    except Exception as exc:
        if standard_mode != AUTO_MODE or not _is_population_data_error(exc):
            raise
        fallback_reason = str(exc)
        sheet = _get_nutrition_sheet(
            recipe,
            "手动估算",
            None,
            age_group,
            gender,
            garden_ratio,
        )
    standard = sheet["analysis"]["standard"]
    ratio_percent = float(sheet["filters"]["garden_ratio"])
    full_day = float(standard[metric])
    population = standard.get("population") or {}
    components = (
        _population_components(population, metric)
        if population
        else _manual_components(age_group, gender, metric)
    )
    divisor = sum(int(item["count"]) for item in components)
    terms = " + ".join(
        f"{_display_number(item['reference_value'])} × {item['count']}"
        for item in components
    )
    full_expression = (
        _display_number(full_day)
        if divisor == 1
        else f"({terms}) ÷ {divisor}"
    )
    garden_target = full_day * ratio_percent / 100
    calculation_rule = sheet["analysis"].get("calculation_rule") or {}
    return {
        "metric": metric,
        "metric_label": NUTRIENT_LABELS[metric],
        "unit": NUTRIENT_UNITS[metric],
        "recipe": sheet["recipe"],
        "profile": standard.get("profile"),
        "requested_standard_mode": requested_standard_mode,
        "standard_mode": sheet["filters"].get("standard_mode"),
        "fallback": (
            {
                "used": True,
                "reason": fallback_reason,
                "guidance": "请补全并启用学生档案后重新使用自动模式。",
            }
            if fallback_reason
            else {"used": False}
        ),
        "population": population or None,
        "components": components,
        "calculation": {
            "method": (
                "逐名按食谱开始日的周岁和性别取官方参考值后加权平均"
                if population
                else "所选年龄和性别官方参考值的算术平均"
            ),
            "full_day_expression": full_expression,
            "full_day_standard": full_day,
            "garden_ratio_percent": ratio_percent,
            "garden_expression": (
                f"{_display_number(full_day)} × {_display_number(ratio_percent)}%"
            ),
            "garden_standard": garden_target,
        },
        "source": {"title": standard.get("source") or OFFICIAL_SOURCE, "url": OFFICIAL_URL},
        "nutrient_calculation_rule": {
            "rule_code": calculation_rule.get("rule_code"),
            "title": calculation_rule.get("title"),
            "version": calculation_rule.get("version"),
            "rule_hash": calculation_rule.get("rule_hash"),
        },
        "answer_summary": (
            (f"自动模式暂不可用（{fallback_reason}），以下为手动估算：" if fallback_reason else "")
            + f"{standard.get('profile')}的{NUTRIENT_LABELS[metric]}全日标准为"
            f"{_display_number(full_day)} {NUTRIENT_UNITS[metric]}；"
            f"按园内供给比例{_display_number(ratio_percent)}%，园内目标为"
            f"{_display_number(garden_target)} {NUTRIENT_UNITS[metric]}。"
        ),
    }


def get_weekly_nutrition_analysis_context(
    recipe: str | None = None,
    standard_mode: str = AUTO_MODE,
    student_groups: list[str] | None = None,
    age_group: str = "4–6岁平均",
    gender: str = "男女平均",
    garden_ratio: float = 80,
) -> dict[str, Any]:
    sheet = _get_nutrition_sheet(
        recipe,
        standard_mode,
        student_groups,
        age_group,
        gender,
        garden_ratio,
    )
    analysis = sheet["analysis"]
    return {
        "recipe": sheet["recipe"],
        "filters": sheet["filters"],
        "standard": analysis["standard"],
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
            "食材营养值按当前营养规则公式计算；全日标准在自动模式下按食谱开始日"
            "逐名解析学生周岁和性别后加权平均，手动模式下按所选年龄和性别平均。"
        ),
    }


def _population_components(population: dict[str, Any], metric: str) -> list[dict[str, Any]]:
    result = []
    for item in population.get("composition") or []:
        label = str(item.get("label") or "")
        match = re.fullmatch(r"([2-6])岁(男|女)", label)
        if not match:
            raise ValueError(f"无法识别学生构成：{label}")
        age, gender = match.groups()
        result.append(
            {
                "label": label,
                "age_years": int(age),
                "gender": gender,
                "count": int(item.get("count") or 0),
                "reference_value": float(FULL_DAY_REFERENCE[age][gender][metric]),
            }
        )
    if not result:
        raise ValueError("学生构成为空，无法解释全日标准")
    return result


def _manual_components(age_group: str, gender: str, metric: str) -> list[dict[str, Any]]:
    age_groups = {
        "4–6岁平均": ["4", "5", "6"],
        "4–5岁平均": ["4", "5"],
        "4岁": ["4"],
        "5岁": ["5"],
        "6岁": ["6"],
    }
    ages = age_groups.get(age_group, age_groups["4–6岁平均"])
    genders = ["男", "女"] if gender == "男女平均" else [gender]
    return [
        {
            "label": f"{age}岁{selected_gender}",
            "age_years": int(age),
            "gender": selected_gender,
            "count": 1,
            "reference_value": float(FULL_DAY_REFERENCE[age][selected_gender][metric]),
        }
        for age in ages
        for selected_gender in genders
    ]


def _get_nutrition_sheet(*args: Any) -> dict[str, Any]:
    from tongjianyun.nutrition_sheet import get_nutrition_sheet

    return get_nutrition_sheet(*args)


def _is_population_data_error(exc: Exception) -> bool:
    message = str(exc)
    return any(
        marker in message
        for marker in (
            "没有启用学生",
            "暂无启用学生",
            "未找到可统计的启用班级",
            "自动营养标准需要完整的学生档案",
        )
    )


def _display_number(value: float) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")
