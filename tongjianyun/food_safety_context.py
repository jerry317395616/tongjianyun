"""Read-only, least-privilege context for the Dify food-safety inspector.

This module intentionally exposes a fixed, de-identified snapshot instead of
Frappe's generic REST API.  The Dify workflow can therefore use current
Tongjianyun records without gaining the ability to enumerate arbitrary
DocTypes, students, guardians, or class-level attendance details.
"""

from __future__ import annotations

import hmac
from collections.abc import Iterable
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, now_datetime


DAILY_MEAL_CONFIRMATION_DOCTYPE = "Tongjianyun Daily Meal Confirmation"
RECIPE_DOCTYPE = "Tongjianyun Recipe"
RECIPE_DISH_DOCTYPE = "Tongjianyun Recipe Dish"
RECIPE_INGREDIENT_DOCTYPE = "Tongjianyun Recipe Ingredient"
FOOD_PURCHASE_DOCTYPE = "Tongjianyun Food Purchase"

SERVICE_TOKEN_CONFIG_KEY = "tongjianyun_dify_food_safety_token"
SCHOOL_NAME_CONFIG_KEY = "tongjianyun_food_safety_school_name"
DEFAULT_SCHOOL_NAME = "临潼区幼儿园"

MAX_DISHES = 80
MAX_INGREDIENTS = 120
MAX_PURCHASE_SUMMARIES = 12


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _config_value(key: str) -> str:
    return _as_text(frappe.conf.get(key))


def _require_dify_service_token() -> None:
    """Authenticate the Dify-only service call without creating a Frappe session."""

    expected = _config_value(SERVICE_TOKEN_CONFIG_KEY)
    provided = _as_text(frappe.get_request_header("X-Tongjianyun-Dify-Token"))
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        frappe.throw(_("Not permitted."), frappe.PermissionError)


def _latest(
    doctype: str, *, filters: dict[str, Any], fields: Iterable[str], order_by: str
):
    return frappe.get_all(
        doctype,
        filters=filters,
        fields=list(fields),
        order_by=order_by,
        limit_page_length=1,
    )


def _daily_meal_confirmation() -> dict[str, Any] | None:
    rows = _latest(
        DAILY_MEAL_CONFIRMATION_DOCTYPE,
        filters={},
        fields=(
            "meal_date",
            "status",
            "source",
            "total_enrolled_count",
            "total_absent_count",
            "total_leave_count",
            "total_breakfast_count",
            "total_morning_snack_count",
            "total_lunch_count",
            "total_afternoon_snack_count",
            "total_dinner_count",
            "modified",
        ),
        order_by="meal_date desc, modified desc",
    )
    if not rows:
        return None

    row = rows[0]
    return {
        "meal_date": str(row.meal_date),
        "status": _as_text(row.status),
        "source": _as_text(row.source),
        "enrolled_count": int(row.total_enrolled_count or 0),
        "absent_count": int(row.total_absent_count or 0),
        "leave_count": int(row.total_leave_count or 0),
        "meal_counts": {
            "breakfast": int(row.total_breakfast_count or 0),
            "morning_snack": int(row.total_morning_snack_count or 0),
            "lunch": int(row.total_lunch_count or 0),
            "afternoon_snack": int(row.total_afternoon_snack_count or 0),
            "dinner": int(row.total_dinner_count or 0),
        },
        "last_updated_at": str(row.modified),
    }


def _latest_recipe() -> dict[str, Any] | None:
    base_fields = (
        "name",
        "recipe_id",
        "title",
        "workflow_status",
        "week_start",
        "week_end",
        "source_file_name",
        "imported_at",
        "modified",
    )
    rows = _latest(
        RECIPE_DOCTYPE,
        filters={"is_deleted": 0, "workflow_status": "已发布"},
        fields=base_fields,
        order_by="week_start desc, modified desc",
    )
    if not rows:
        rows = _latest(
            RECIPE_DOCTYPE,
            filters={"is_deleted": 0},
            fields=base_fields,
            order_by="week_start desc, modified desc",
        )
    if not rows:
        return None

    recipe = rows[0]
    dishes = frappe.get_all(
        RECIPE_DISH_DOCTYPE,
        filters={"recipe": recipe.name},
        fields=(
            "name",
            "meal_date",
            "day_label",
            "meal_label",
            "dish_name",
            "amount_per_child_text",
            "total_amount_text",
            "day_risk",
            "sort_order",
        ),
        order_by="sort_order asc, meal_date asc",
        limit_page_length=MAX_DISHES,
    )
    ingredients = frappe.get_all(
        RECIPE_INGREDIENT_DOCTYPE,
        filters={"recipe": recipe.name},
        fields=(
            "recipe_dish",
            "ingredient_name",
            "amount",
            "unit",
            "grams_per_child",
            "sort_order",
        ),
        order_by="sort_order asc",
        limit_page_length=MAX_INGREDIENTS,
    )
    ingredients_by_dish: dict[str, list[dict[str, Any]]] = {}
    for ingredient in ingredients:
        ingredients_by_dish.setdefault(ingredient.recipe_dish, []).append(
            {
                "name": _as_text(ingredient.ingredient_name),
                "amount": flt(ingredient.amount),
                "unit": _as_text(ingredient.unit) or "g",
                "grams_per_child": flt(ingredient.grams_per_child),
            }
        )

    return {
        "recipe_id": _as_text(recipe.recipe_id),
        "title": _as_text(recipe.title),
        "status": _as_text(recipe.workflow_status),
        "week_start": str(recipe.week_start or ""),
        "week_end": str(recipe.week_end or ""),
        "source_file_name": _as_text(recipe.source_file_name),
        "imported_at": str(recipe.imported_at or ""),
        "last_updated_at": str(recipe.modified),
        "dishes": [
            {
                "meal_date": str(dish.meal_date or ""),
                "day_label": _as_text(dish.day_label),
                "meal_label": _as_text(dish.meal_label),
                "name": _as_text(dish.dish_name),
                "amount_per_child": _as_text(dish.amount_per_child_text),
                "total_amount": _as_text(dish.total_amount_text),
                "risk": _as_text(dish.day_risk),
                "ingredients": ingredients_by_dish.get(dish.name, []),
            }
            for dish in dishes
        ],
    }


def _recent_procurement_summaries() -> list[dict[str, Any]]:
    if not frappe.db.table_exists(FOOD_PURCHASE_DOCTYPE):
        return []
    rows = frappe.get_all(
        FOOD_PURCHASE_DOCTYPE,
        fields=("title", "status", "risk", "category", "source", "modified"),
        order_by="modified desc",
        limit_page_length=MAX_PURCHASE_SUMMARIES,
    )
    return [
        {
            "title": _as_text(row.title),
            "status": _as_text(row.status),
            "risk": _as_text(row.risk),
            "category": _as_text(row.category),
            "source": _as_text(row.source),
            "last_updated_at": str(row.modified),
        }
        for row in rows
    ]


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_dify_food_safety_context() -> dict[str, Any]:
    """Return current, de-identified food-safety data for the Dify inspector.

    Authentication is a service token in a request header.  The response is
    deliberately bounded and contains no child, guardian, or class detail.
    """

    _require_dify_service_token()
    school_name = _config_value(SCHOOL_NAME_CONFIG_KEY) or DEFAULT_SCHOOL_NAME
    return {
        "school": school_name,
        "source_site": "child.myyr.top",
        "generated_at": str(now_datetime()),
        "data_scope": {
            "included": ["每日就餐汇总", "最新食谱及食材", "近期采购台账摘要"],
            "excluded": ["儿童姓名", "监护人信息", "班级明细", "任意DocType查询"],
        },
        "daily_meal_confirmation": _daily_meal_confirmation(),
        "latest_recipe": _latest_recipe(),
        "recent_procurement_summaries": _recent_procurement_summaries(),
        "usage_note": "该数据用于辅助检查。请结合现场实物、台账原件和正式制度作出最终判断。",
    }
