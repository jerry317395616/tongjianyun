from __future__ import annotations

import hashlib
import json
from typing import Any

import frappe
from frappe import _
from frappe.query_builder.functions import Count
from frappe.utils import cint, flt, now_datetime, nowdate

RECIPE_DOCTYPE = "Tongjianyun Recipe"
DISH_DOCTYPE = "Tongjianyun Recipe Dish"
INGREDIENT_DOCTYPE = "Tongjianyun Recipe Ingredient"
LEGACY_DOCTYPE = "Tongjianyun Meal Nutrition"

MEAL_SLOTS = ("breakfast", "morningSnack", "lunch", "snack", "dinner")
MEAL_LABELS = {
    "breakfast": "\u65e9\u9910",
    "morningSnack": "\u65e9\u70b9",
    "lunch": "\u5348\u9910",
    "snack": "\u5348\u70b9",
    "dinner": "\u665a\u9910",
}


def _require_login() -> None:
    if frappe.session.user == "Guest":
        frappe.throw(_("Not logged in."), frappe.AuthenticationError)


def _as_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        parsed = json.loads(value) if value.strip() else {}
        return parsed if isinstance(parsed, dict) else {}
    return dict(value)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        parsed = json.loads(value) if value.strip() else []
        return parsed if isinstance(parsed, list) else []
    return list(value)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _row_id(prefix: str, *parts: Any) -> str:
    raw = "|".join(_clean(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _grams(amount: float, unit: str) -> float:
    normalized = _clean(unit).lower()
    if normalized in {"g", "gram", "grams", "\u514b"}:
        return amount
    if normalized in {"kg", "kilogram", "kilograms", "\u5343\u514b", "\u516c\u65a4"}:
        return amount * 1000
    if normalized in {"mg", "milligram", "milligrams", "\u6beb\u514b"}:
        return amount / 1000
    return 0


def _save_doc(doc) -> None:
    doc.flags.ignore_permissions = True
    if doc.name:
        doc.save(ignore_permissions=True)
    else:
        doc.insert(ignore_permissions=True)


def _delete_recipe_rows(recipe_name: str) -> None:
    frappe.db.delete(INGREDIENT_DOCTYPE, {"recipe": recipe_name})
    frappe.db.delete(DISH_DOCTYPE, {"recipe": recipe_name})


def _recipe_payload(doc) -> dict[str, Any]:
    student_groups = [row.student_group for row in (doc.applicable_student_groups or []) if row.student_group]
    return {
        "recipeId": doc.recipe_id,
        "title": doc.title or "",
        "weekStart": str(doc.week_start or ""),
        "weekEnd": str(doc.week_end or ""),
        "sourceFileName": doc.source_file_name or "",
        "parser": doc.parser or "",
        "relationSource": doc.relation_source or "",
        "importedAt": str(doc.imported_at or ""),
        "workflowStatus": doc.workflow_status or "草稿",
        "allStudentGroups": bool(doc.all_student_groups),
        "studentGroups": student_groups,
    }


def _save_current_recipe(payload: Any, *, commit: bool) -> dict[str, Any]:
    root = _as_dict(payload)
    recipe_data = _as_dict(root.get("recipe"))
    days = [_as_dict(day) for day in _as_list(root.get("days"))]
    recipe_id = _clean(recipe_data.get("recipeId")) or "current"

    existing = frappe.db.exists(RECIPE_DOCTYPE, {"recipe_id": recipe_id})
    recipe = frappe.get_doc(RECIPE_DOCTYPE, existing) if existing else frappe.new_doc(RECIPE_DOCTYPE)
    recipe.recipe_id = recipe_id
    recipe.title = (_clean(recipe_data.get("title")) or "\u5f53\u524d\u5468\u98df\u8c31")[:140]
    recipe.week_start = recipe_data.get("weekStart") or None
    recipe.week_end = recipe_data.get("weekEnd") or None
    recipe.source_file_name = _clean(recipe_data.get("sourceFileName"))[:140]
    recipe.parser = _clean(recipe_data.get("parser"))[:140]
    recipe.relation_source = _clean(recipe_data.get("relationSource"))[:140]
    recipe.imported_at = recipe_data.get("importedAt") or now_datetime()
    recipe.workflow_status = _clean(recipe_data.get("workflowStatus")) or "草稿"
    all_student_groups = recipe_data.get("allStudentGroups")
    recipe.all_student_groups = 1 if all_student_groups is None else cint(all_student_groups)
    recipe.set("applicable_student_groups", [])
    if not recipe.all_student_groups:
        for student_group in dict.fromkeys(_clean(value) for value in _as_list(recipe_data.get("studentGroups"))):
            if student_group:
                recipe.append("applicable_student_groups", {"student_group": student_group})
    _save_doc(recipe)

    _delete_recipe_rows(recipe.name)

    for day_index, day in enumerate(days):
        day_id = _clean(day.get("id")) or f"DAY-{day_index + 1}"
        meal_date = day.get("date") or None
        day_label = _clean(day.get("day"))
        portions = [_as_dict(portion) for portion in _as_list(day.get("portions"))]
        for portion_index, portion in enumerate(portions):
            slot = _clean(portion.get("slot"))
            if slot not in MEAL_SLOTS:
                continue
            ingredient_rows = [_as_dict(row) for row in _as_list(portion.get("dishIngredientRows"))]
            dish_names: list[str] = []
            for value in _as_list(portion.get("dishes")):
                name = _clean(value)
                if name and name not in dish_names:
                    dish_names.append(name)
            for row in ingredient_rows:
                name = _clean(row.get("dishName"))
                if name and name not in dish_names:
                    dish_names.append(name)
            if not dish_names:
                fallback_name = _clean(day.get(slot))
                if fallback_name:
                    dish_names.append(fallback_name)

            unassigned = [row for row in ingredient_rows if not _clean(row.get("dishName"))]
            if unassigned and len(dish_names) != 1:
                ingredient_names = "\u3001".join(_clean(row.get("ingredient")) for row in unassigned[:5])
                frappe.throw(_("Ingredients must be linked to a dish: {0}").format(ingredient_names))

            for dish_order, dish_name in enumerate(dish_names):
                dish_row_id = _row_id(
                    "DISH",
                    recipe.name,
                    day_id,
                    slot,
                    dish_order,
                    dish_name,
                )
                dish = frappe.new_doc(DISH_DOCTYPE)
                dish.dish_row_id = dish_row_id
                dish.recipe = recipe.name
                dish.day_id = day_id
                dish.meal_date = meal_date
                dish.day_label = day_label
                dish.meal_slot = slot
                dish.meal_label = _clean(portion.get("label")) or MEAL_LABELS[slot]
                dish.dish_name = dish_name
                dish.dish_order = dish_order
                dish.amount_per_child_text = _clean(portion.get("amountPerChild"))
                dish.total_amount_text = _clean(portion.get("totalAmount"))
                dish.day_score = flt(day.get("score"))
                dish.day_risk = _clean(day.get("risk"))
                dish.day_locked = cint(day.get("locked"))
                dish.day_updated_at = day.get("updatedAt") or None
                dish.day_updated_by = _clean(day.get("updatedBy"))[:140]
                dish.day_edit_reason = _clean(day.get("editReason"))
                dish.day_version = max(1, cint(day.get("version")))
                dish.sort_order = day_index * 1000 + portion_index * 100 + dish_order
                _save_doc(dish)

                linked_rows = [
                    row
                    for row in ingredient_rows
                    if _clean(row.get("dishName")) == dish_name
                    or (not _clean(row.get("dishName")) and len(dish_names) == 1)
                ]
                for ingredient_order, row in enumerate(linked_rows):
                    ingredient_name = _clean(row.get("ingredient"))
                    if not ingredient_name:
                        continue
                    amount = flt(row.get("amount"))
                    unit = _clean(row.get("unit")) or "g"
                    ingredient = frappe.new_doc(INGREDIENT_DOCTYPE)
                    ingredient.ingredient_row_id = _row_id(
                        "ING",
                        dish_row_id,
                        ingredient_order,
                        ingredient_name,
                        amount,
                        unit,
                    )
                    ingredient.recipe = recipe.name
                    ingredient.recipe_dish = dish.name
                    ingredient.ingredient_name = ingredient_name
                    ingredient.amount = amount
                    ingredient.unit = unit
                    ingredient.grams_per_child = _grams(amount, unit)
                    ingredient.sort_order = ingredient_order
                    _save_doc(ingredient)

    if commit:
        frappe.db.commit()
    return _current_recipe_payload(recipe)


def _current_recipe_payload(recipe) -> dict[str, Any]:
    dish_rows = frappe.get_all(
        DISH_DOCTYPE,
        filters={"recipe": recipe.name},
        fields=[
            "name",
            "day_id",
            "meal_date",
            "day_label",
            "meal_slot",
            "meal_label",
            "dish_name",
            "dish_order",
            "amount_per_child_text",
            "total_amount_text",
            "day_score",
            "day_risk",
            "day_locked",
            "day_updated_at",
            "day_updated_by",
            "day_edit_reason",
            "day_version",
            "sort_order",
        ],
        order_by="sort_order asc, dish_order asc",
        limit_page_length=0,
    )
    ingredient_rows = frappe.get_all(
        INGREDIENT_DOCTYPE,
        filters={"recipe": recipe.name},
        fields=["recipe_dish", "ingredient_name", "amount", "unit", "grams_per_child", "sort_order"],
        order_by="sort_order asc",
        limit_page_length=0,
    )
    ingredients_by_dish: dict[str, list[dict[str, Any]]] = {}
    for row in ingredient_rows:
        ingredients_by_dish.setdefault(row.recipe_dish, []).append(
            {
                "ingredient": row.ingredient_name,
                "amount": flt(row.amount),
                "unit": row.unit or "g",
                "gramsPerChild": flt(row.grams_per_child),
            }
        )

    days: dict[str, dict[str, Any]] = {}
    day_order: list[str] = []
    portions_by_day: dict[str, dict[str, dict[str, Any]]] = {}
    for row in dish_rows:
        day_key = row.day_id or str(row.meal_date or "")
        if day_key not in days:
            day_order.append(day_key)
            days[day_key] = {
                "id": day_key,
                "date": str(row.meal_date or ""),
                "day": row.day_label or "",
                "breakfast": "",
                "morningSnack": "",
                "lunch": "",
                "snack": "",
                "dinner": "",
                "portions": [],
                "score": flt(row.day_score),
                "risk": row.day_risk or "normal",
                "locked": bool(row.day_locked),
                "updatedAt": str(row.day_updated_at or ""),
                "updatedBy": row.day_updated_by or "",
                "editReason": row.day_edit_reason or "",
                "version": max(1, cint(row.day_version)),
            }
            portions_by_day[day_key] = {}
        portions = portions_by_day[day_key]
        if row.meal_slot not in portions:
            portions[row.meal_slot] = {
                "slot": row.meal_slot,
                "label": row.meal_label or MEAL_LABELS.get(row.meal_slot, row.meal_slot),
                "dishes": [],
                "amountPerChild": row.amount_per_child_text or "",
                "totalAmount": row.total_amount_text or "",
                "energyKcal": 0,
                "proteinG": 0,
                "dishIngredientRows": [],
            }
        portion = portions[row.meal_slot]
        portion["dishes"].append(row.dish_name)
        for ingredient in ingredients_by_dish.get(row.name, []):
            portion["dishIngredientRows"].append(
                {
                    "dishName": row.dish_name,
                    "ingredient": ingredient["ingredient"],
                    "amount": ingredient["amount"],
                    "unit": ingredient["unit"],
                    "gramsPerChild": ingredient["gramsPerChild"],
                }
            )

    result_days: list[dict[str, Any]] = []
    for day_key in day_order:
        day = days[day_key]
        portions = portions_by_day[day_key]
        day["portions"] = [portions[slot] for slot in MEAL_SLOTS if slot in portions]
        for slot in MEAL_SLOTS:
            day[slot] = " / ".join(portions.get(slot, {}).get("dishes", []))
        result_days.append(day)

    return {"recipe": _recipe_payload(recipe), "days": result_days}


@frappe.whitelist()
def get_current_recipe() -> dict[str, Any] | None:
    _require_login()
    name = frappe.db.get_value(RECIPE_DOCTYPE, {"recipe_id": "current"}, "name")
    if not name:
        name = frappe.db.get_value(
            RECIPE_DOCTYPE,
            {"week_start": ["<=", nowdate()], "week_end": [">=", nowdate()]},
            "name",
            order_by="modified desc",
        )
    if not name:
        name = frappe.db.get_value(RECIPE_DOCTYPE, {}, "name", order_by="week_start desc, modified desc")
    if not name:
        return None
    return _current_recipe_payload(frappe.get_doc(RECIPE_DOCTYPE, name))


@frappe.whitelist()
def get_recipe_detail(recipe: str) -> dict[str, Any]:
    _require_login()
    recipe_name = frappe.db.exists(RECIPE_DOCTYPE, recipe) or frappe.db.exists(
        RECIPE_DOCTYPE,
        {"recipe_id": recipe},
    )
    if not recipe_name:
        frappe.throw(_("Recipe not found."), frappe.DoesNotExistError)
    return _current_recipe_payload(frappe.get_doc(RECIPE_DOCTYPE, recipe_name))


@frappe.whitelist()
def get_recipe_library(
    search: str | None = None,
    status: str | None = None,
    include_test: int = 0,
    start: int = 0,
    page_length: int = 50,
) -> dict[str, Any]:
    """Return the lightweight recipe-library projection used by the desk page."""

    _require_login()
    start = max(0, cint(start))
    page_length = min(100, max(1, cint(page_length) or 50))
    filters: list[list[Any]] = []
    or_filters: list[list[Any]] = []
    search_text = _clean(search)
    if search_text:
        or_filters.extend(
            [
                [RECIPE_DOCTYPE, "title", "like", f"%{search_text}%"],
                [RECIPE_DOCTYPE, "recipe_id", "like", f"%{search_text}%"],
            ]
        )
    status_text = _clean(status)
    if status_text and status_text != "全部":
        filters.append([RECIPE_DOCTYPE, "workflow_status", "=", status_text])
    if not cint(include_test):
        filters.extend(
            [
                [RECIPE_DOCTYPE, "title", "not like", "%测试%"],
                [RECIPE_DOCTYPE, "title", "not like", "%【演示】%"],
            ]
        )

    recipes = frappe.get_list(
        RECIPE_DOCTYPE,
        filters=filters,
        or_filters=or_filters,
        fields=[
            "name",
            "recipe_id",
            "title",
            "week_start",
            "week_end",
            "source_file_name",
            "parser",
            "relation_source",
            "imported_at",
            "modified",
            "modified_by",
            "workflow_status",
            "all_student_groups",
        ],
        order_by="week_start desc, modified desc",
        start=start,
        page_length=page_length,
    )
    recipe_names = [row.name for row in recipes]
    counts: dict[str, dict[str, int]] = {
        name: {"dish_count": 0, "ingredient_count": 0} for name in recipe_names
    }
    if recipe_names:
        dish = frappe.qb.DocType(DISH_DOCTYPE)
        dish_counts = (
            frappe.qb.from_(dish)
            .select(dish.recipe, Count(dish.name).as_("dish_count"))
            .where(dish.recipe.isin(recipe_names))
            .groupby(dish.recipe)
        ).run(as_dict=True)
        ingredient = frappe.qb.DocType(INGREDIENT_DOCTYPE)
        ingredient_counts = (
            frappe.qb.from_(ingredient)
            .select(ingredient.recipe, Count(ingredient.name).as_("ingredient_count"))
            .where(ingredient.recipe.isin(recipe_names))
            .groupby(ingredient.recipe)
        ).run(as_dict=True)
        for row in dish_counts:
            counts[row.recipe]["dish_count"] = cint(row.dish_count)
        for row in ingredient_counts:
            counts[row.recipe]["ingredient_count"] = cint(row.ingredient_count)

    items = []
    for row in recipes:
        item = dict(row)
        item.update(counts[row.name])
        item["workflow_status"] = item.get("workflow_status") or ("已发布" if item["dish_count"] else "草稿")
        item["status"] = {
            "草稿": "draft",
            "待审核": "review",
            "已发布": "published",
            "已归档": "archived",
        }.get(item["workflow_status"], "draft")
        item["student_groups"] = (
            ["全部班级"]
            if item.get("all_student_groups")
            else frappe.get_all(
                "Tongjianyun Recipe Student Group",
                filters={"parent": row.name, "parenttype": RECIPE_DOCTYPE},
                pluck="student_group",
                order_by="idx asc",
            )
        )
        items.append(item)

    return {
        "items": items,
        "start": start,
        "page_length": page_length,
        "has_more": len(items) == page_length,
    }


@frappe.whitelist()
def save_current_recipe(payload: Any = None) -> dict[str, Any]:
    _require_login()
    return _save_current_recipe(payload, commit=True)


def save_recipe_payload(payload: Any, *, commit: bool = False) -> dict[str, Any]:
    """Persist one complete recipe payload for trusted in-process integrations.

    Row identifiers remain server-managed: dishes and ingredients are rebuilt
    atomically by ``_save_current_recipe`` and receive deterministic IDs from
    their recipe, day, meal and row content.
    """

    return _save_current_recipe(payload, commit=commit)


@frappe.whitelist()
def delete_current_recipe() -> dict[str, int]:
    _require_login()
    names = frappe.get_all(RECIPE_DOCTYPE, filters={"recipe_id": "current"}, pluck="name", limit_page_length=0)
    for name in names:
        _delete_recipe_rows(name)
        frappe.delete_doc(RECIPE_DOCTYPE, name, ignore_permissions=True)
    frappe.db.commit()
    return {"deleted": len(names)}


def migrate_legacy_current_recipe() -> dict[str, int]:
    if frappe.db.exists(RECIPE_DOCTYPE, {"recipe_id": "current"}):
        return {"migrated": 0}
    if not frappe.db.table_exists(LEGACY_DOCTYPE):
        return {"migrated": 0}
    legacy_name = frappe.db.exists(LEGACY_DOCTYPE, {"data_key": "meal_draft::current"})
    if not legacy_name:
        return {"migrated": 0}
    legacy = frappe.get_doc(LEGACY_DOCTYPE, legacy_name)
    try:
        result = json.loads(legacy.record_json or "{}")
    except Exception:
        return {"migrated": 0}
    config = _as_dict(result.get("config"))
    summary = _as_dict(result.get("summary"))
    days = _as_list(result.get("mealPlan"))
    if not days:
        return {"migrated": 0}
    _save_current_recipe(
        {
            "recipe": {
                "recipeId": "current",
                "title": summary.get("cycle") or "\u5f53\u524d\u5468\u98df\u8c31",
                "weekStart": config.get("weekStart"),
                "weekEnd": config.get("weekEnd"),
                "relationSource": "legacy-migration",
            },
            "days": days,
        },
        commit=False,
    )
    frappe.delete_doc(LEGACY_DOCTYPE, legacy_name, ignore_permissions=True)
    return {"migrated": 1}


def install() -> None:
    migrate_legacy_current_recipe()
    table_columns = set(frappe.db.get_table_columns(RECIPE_DOCTYPE))
    for fieldname in (
        "is_current",
        "status",
        "age_group",
        "estimated_children",
        "source",
        "version",
    ):
        if fieldname in table_columns:
            frappe.db.sql_ddl(f"ALTER TABLE `tab{RECIPE_DOCTYPE}` DROP COLUMN `{fieldname}`")
