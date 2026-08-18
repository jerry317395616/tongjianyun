from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt

from tongjianyun.recipe_analysis import (
    DEFAULT_STANDARD,
    _person_days,
    analyze_recipe_payload,
    create_and_attach_recipe_analysis,
)
from tongjianyun.recipe_storage import get_recipe_detail
from tongjianyun.tongjianyun.report.weekly_recipe_nutrition_analysis.weekly_recipe_nutrition_analysis import (
    _standard_profile,
)


RECIPE_DOCTYPE = "Tongjianyun Recipe"


def _require_login() -> None:
    if frappe.session.user == "Guest":
        frappe.throw("请先登录。", frappe.AuthenticationError)


def _latest_recipe() -> str | None:
    return frappe.db.get_value(
        RECIPE_DOCTYPE,
        {"is_deleted": 0},
        "name",
        order_by="week_start desc, modified desc",
    )


def _analysis_standard(age_group: str, gender: str, ratio_percent: float) -> dict[str, Any]:
    core_standard, profile = _standard_profile(age_group, gender)
    return {
        **DEFAULT_STANDARD,
        **core_standard,
        "profile": profile,
        "garden_ratio": ratio_percent / 100,
        "source": "DB4403/T 489—2024《0岁～6岁儿童营养配餐指南》",
    }


def _validated_ratio(value: Any) -> float:
    ratio_percent = flt(value or 80)
    if ratio_percent < 30 or ratio_percent > 100:
        frappe.throw("园内供给目标应设置在30%–100%之间。")
    return ratio_percent


@frappe.whitelist()
def get_nutrition_sheet(
    recipe: str | None = None,
    age_group: str = "4–5岁平均",
    gender: str = "男女平均",
    garden_ratio: float = 80,
) -> dict[str, Any]:
    _require_login()
    recipe_name = recipe or _latest_recipe()
    if not recipe_name:
        frappe.throw("暂无可分析的食谱，请先创建或导入食谱。")

    recipe_doc = frappe.get_doc(RECIPE_DOCTYPE, recipe_name)
    recipe_doc.check_permission("read")
    if recipe_doc.is_deleted:
        frappe.throw("回收站中的食谱不能生成营养分析表。")

    ratio_percent = _validated_ratio(garden_ratio)
    standard = _analysis_standard(age_group, gender, ratio_percent)
    payload = get_recipe_detail(recipe_doc.name)
    analysis = analyze_recipe_payload(
        payload,
        standard=standard,
        person_days=_person_days(recipe_doc),
    )

    return {
        "recipe": {
            "name": recipe_doc.name,
            "recipe_id": recipe_doc.recipe_id,
            "title": recipe_doc.title,
            "week_start": str(recipe_doc.week_start or ""),
            "week_end": str(recipe_doc.week_end or ""),
        },
        "analysis": analysis,
        "filters": {
            "age_group": age_group,
            "gender": gender,
            "garden_ratio": ratio_percent,
        },
    }


@frappe.whitelist()
def export_nutrition_sheet(
    recipe: str,
    age_group: str = "4–5岁平均",
    gender: str = "男女平均",
    garden_ratio: float = 80,
) -> dict[str, Any]:
    _require_login()
    recipe_doc = frappe.get_doc(RECIPE_DOCTYPE, recipe)
    recipe_doc.check_permission("read")
    ratio_percent = _validated_ratio(garden_ratio)
    standard = _analysis_standard(age_group, gender, ratio_percent)
    return create_and_attach_recipe_analysis(recipe_doc.name, standard=standard)
