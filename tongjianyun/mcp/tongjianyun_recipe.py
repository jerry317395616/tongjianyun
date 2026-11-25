from __future__ import annotations

from typing import Any

from tongjianyun.mcp.security import ensure_doctype_permission

RECIPE_DOCTYPE = "Tongjianyun Recipe"
DISH_DOCTYPE = "Tongjianyun Recipe Dish"
INGREDIENT_DOCTYPE = "Tongjianyun Recipe Ingredient"
MEAL_SLOTS = {"breakfast", "morningSnack", "lunch", "snack", "dinner"}
MAX_DAYS = 31
MAX_DISHES = 500
MAX_INGREDIENTS = 5000


def _as_mapping(value: Any, label: str) -> dict[str, Any]:
	if not isinstance(value, dict):
		raise ValueError(f"{label} must be an object")
	return value


def _as_rows(value: Any, label: str) -> list[Any]:
	if not isinstance(value, list):
		raise ValueError(f"{label} must be an array")
	return value


def validate_recipe_payload(recipe: dict[str, Any], days: list[dict[str, Any]]) -> dict[str, Any]:
	"""Validate one bounded weekly-recipe payload before changing site data."""

	recipe = _as_mapping(recipe, "recipe")
	days = _as_rows(days, "days")
	recipe_id = str(recipe.get("recipeId") or "").strip()
	title = str(recipe.get("title") or "").strip()
	if not recipe_id:
		raise ValueError("recipe.recipeId is required")
	if not title:
		raise ValueError("recipe.title is required")
	if not days:
		raise ValueError("days must contain at least one recipe day")
	if len(days) > MAX_DAYS:
		raise ValueError(f"days cannot contain more than {MAX_DAYS} entries")

	dish_count = 0
	ingredient_count = 0
	seen_day_ids: set[str] = set()
	for day_index, raw_day in enumerate(days):
		day = _as_mapping(raw_day, f"days[{day_index}]")
		day_id = str(day.get("id") or f"DAY-{day_index + 1}").strip()
		if day_id in seen_day_ids:
			raise ValueError(f"days contains duplicate day id: {day_id}")
		seen_day_ids.add(day_id)
		portions = _as_rows(day.get("portions") or [], f"days[{day_index}].portions")
		seen_slots: set[str] = set()
		day_dish_count = 0
		for portion_index, raw_portion in enumerate(portions):
			portion = _as_mapping(
				raw_portion,
				f"days[{day_index}].portions[{portion_index}]",
			)
			slot = str(portion.get("slot") or "").strip()
			if slot not in MEAL_SLOTS:
				raise ValueError(f"days[{day_index}].portions[{portion_index}].slot is invalid")
			if slot in seen_slots:
				raise ValueError(f"days[{day_index}] contains duplicate meal slot: {slot}")
			seen_slots.add(slot)

			dish_names = {
				str(value or "").strip()
				for value in _as_rows(
					portion.get("dishes") or [],
					f"days[{day_index}].portions[{portion_index}].dishes",
				)
				if str(value or "").strip()
			}
			ingredients = _as_rows(
				portion.get("dishIngredientRows") or [],
				f"days[{day_index}].portions[{portion_index}].dishIngredientRows",
			)
			for ingredient_index, raw_ingredient in enumerate(ingredients):
				ingredient = _as_mapping(
					raw_ingredient,
					f"days[{day_index}].portions[{portion_index}].dishIngredientRows[{ingredient_index}]",
				)
				dish_name = str(ingredient.get("dishName") or "").strip()
				ingredient_name = str(ingredient.get("ingredient") or "").strip()
				if dish_name:
					dish_names.add(dish_name)
				if not ingredient_name:
					raise ValueError(
						f"days[{day_index}].portions[{portion_index}]."
						f"dishIngredientRows[{ingredient_index}].ingredient is required"
					)
			fallback = str(day.get(slot) or "").strip()
			if fallback and not dish_names:
				dish_names.add(fallback)
			dish_count += len(dish_names)
			day_dish_count += len(dish_names)
			ingredient_count += len(ingredients)
		if not day_dish_count:
			raise ValueError(f"days[{day_index}] must contain at least one dish")

	if not dish_count:
		raise ValueError("The recipe must contain at least one dish")
	if dish_count > MAX_DISHES:
		raise ValueError(f"The recipe cannot contain more than {MAX_DISHES} dishes")
	if ingredient_count > MAX_INGREDIENTS:
		raise ValueError(f"The recipe cannot contain more than {MAX_INGREDIENTS} ingredient rows")
	return {
		"recipe": recipe,
		"days": days,
		"day_count": len(days),
		"dish_count": dish_count,
		"ingredient_count": ingredient_count,
	}


def upsert_tongjianyun_recipe(
	recipe: dict[str, Any],
	days: list[dict[str, Any]],
) -> dict[str, Any]:
	"""Create or replace one complete recipe and verify its generated detail rows."""

	import frappe

	if "tongjianyun" not in frappe.get_installed_apps():
		raise ValueError("Tongjianyun is not installed on this site")
	import tongjianyun

	if getattr(tongjianyun, "REPORTS_ONLY", False):
		raise ValueError("童健云旧食谱编辑已停用。请使用 ERP 原生生产计划编排食谱。")
	validated = validate_recipe_payload(recipe, days)
	recipe_id = str(validated["recipe"]["recipeId"]).strip()
	existing = frappe.db.exists(RECIPE_DOCTYPE, {"recipe_id": recipe_id})
	ensure_doctype_permission(RECIPE_DOCTYPE, "write" if existing else "create")
	for doctype in (DISH_DOCTYPE, INGREDIENT_DOCTYPE):
		ensure_doctype_permission(doctype, "create")
		if existing:
			ensure_doctype_permission(doctype, "delete")

	from tongjianyun.recipe_storage import save_recipe_payload

	savepoint = "ione_mcp_tongjianyun_recipe"
	frappe.db.savepoint(savepoint)
	try:
		result = save_recipe_payload(
			{"recipe": validated["recipe"], "days": validated["days"]},
			commit=False,
		)
		recipe_name = frappe.db.exists(RECIPE_DOCTYPE, {"recipe_id": recipe_id})
		if not recipe_name:
			raise RuntimeError("Recipe save completed without a recipe record")
		dish_count = frappe.db.count(DISH_DOCTYPE, {"recipe": recipe_name})
		ingredient_count = frappe.db.count(INGREDIENT_DOCTYPE, {"recipe": recipe_name})
		day_count = len(result.get("days") or [])
		if day_count != validated["day_count"]:
			raise RuntimeError("Recipe day verification failed")
		if dish_count != validated["dish_count"]:
			raise RuntimeError("Recipe dish verification failed")
		if ingredient_count != validated["ingredient_count"]:
			raise RuntimeError("Recipe ingredient verification failed")
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise

	result_recipe = result.get("recipe") or {}
	return {
		"doctype": RECIPE_DOCTYPE,
		"name": recipe_name,
		"recipe_id": recipe_id,
		"title": result_recipe.get("title") or validated["recipe"]["title"],
		"week_start": result_recipe.get("weekStart") or None,
		"week_end": result_recipe.get("weekEnd") or None,
		"created": not bool(existing),
		"day_count": day_count,
		"dish_count": dish_count,
		"ingredient_count": ingredient_count,
	}
