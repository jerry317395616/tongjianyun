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
from tongjianyun.nutrition_population import (
    AUTO_MODE,
    build_population_standard,
    freeze_snapshot,
    parse_student_groups,
    read_snapshot,
)
from tongjianyun.nutrition_standards import OFFICIAL_SOURCE, standard_profile


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


def _manual_standard(age_group: str, gender: str, ratio_percent: float) -> dict[str, Any]:
    core_standard, profile = standard_profile(age_group, gender)
    return {
        **DEFAULT_STANDARD,
        **core_standard,
        "profile": profile,
        "garden_ratio": ratio_percent / 100,
        "source": OFFICIAL_SOURCE,
    }


def _population_standard(
    recipe_doc: Any,
    student_groups: Any,
    ratio_percent: float,
    *,
    freeze: bool = False,
) -> dict[str, Any]:
    groups = parse_student_groups(student_groups)
    status = recipe_doc.get("workflow_status")
    snapshot = read_snapshot(recipe_doc, groups) if status in {"已发布", "已归档"} else None
    if snapshot:
        calculated = {
            "values": dict(snapshot["values"]),
            "profile": f"{snapshot['profile']}（已冻结）",
            "source": snapshot.get("source") or OFFICIAL_SOURCE,
            "population": dict(snapshot.get("population") or {}),
        }
    else:
        calculated = build_population_standard(recipe_doc, groups)
        if freeze:
            freeze_snapshot(recipe_doc, calculated, groups)

    return {
        **DEFAULT_STANDARD,
        **calculated["values"],
        "profile": calculated["profile"],
        "garden_ratio": ratio_percent / 100,
        "source": calculated["source"],
        "population": calculated["population"],
    }


def _analysis_standard(
    recipe_doc: Any,
    standard_mode: str,
    student_groups: Any,
    age_group: str,
    gender: str,
    ratio_percent: float,
    *,
    freeze: bool = False,
) -> dict[str, Any]:
    if standard_mode == AUTO_MODE:
        return _population_standard(recipe_doc, student_groups, ratio_percent, freeze=freeze)
    return _manual_standard(age_group, gender, ratio_percent)


def _validated_ratio(value: Any) -> float:
    ratio_percent = flt(value or 80)
    if ratio_percent < 30 or ratio_percent > 100:
        frappe.throw("园内供给目标应设置在30%–100%之间。")
    return ratio_percent


@frappe.whitelist()
def get_nutrition_sheet(
    recipe: str | None = None,
    standard_mode: str = AUTO_MODE,
    student_groups: Any = None,
    age_group: str = "4–6岁平均",
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
    standard = _analysis_standard(
        recipe_doc,
        standard_mode,
        student_groups,
        age_group,
        gender,
        ratio_percent,
    )
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
            "standard_mode": standard_mode,
            "student_groups": parse_student_groups(student_groups),
            "age_group": age_group,
            "gender": gender,
            "garden_ratio": ratio_percent,
        },
    }


@frappe.whitelist()
def export_nutrition_sheet(
    recipe: str,
    standard_mode: str = AUTO_MODE,
    student_groups: Any = None,
    age_group: str = "4–6岁平均",
    gender: str = "男女平均",
    garden_ratio: float = 80,
) -> dict[str, Any]:
    _require_login()
    recipe_doc = frappe.get_doc(RECIPE_DOCTYPE, recipe)
    recipe_doc.check_permission("read")
    ratio_percent = _validated_ratio(garden_ratio)
    standard = _analysis_standard(
        recipe_doc,
        standard_mode,
        student_groups,
        age_group,
        gender,
        ratio_percent,
        freeze=True,
    )
    return create_and_attach_recipe_analysis(recipe_doc.name, standard=standard)
