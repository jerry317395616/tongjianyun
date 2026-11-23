"""Calculate dish and weekly nutrition from reviewed food profiles."""

import json
from collections import defaultdict
from decimal import Decimal

import frappe

from tongjianyun.food_nutrition import approved_profiles, nutrient_values
from tongjianyun.ingredient_library import configured_conversion, conversion_rows
from tongjianyun.nutrition_math import (
    NUTRIENTS, ingredient_amounts, number, positive, stock_mass_in_grams, summarize, unit_factor,
)
from tongjianyun.standard_recipes import MARKER, NET_QTY

SNAPSHOT = "custom_tjy_nutrition_snapshot"


def _line(row, serving, item, profile, conversions, stock_masses):
    gross = positive(row.qty)
    result = {
        "code": row.item_code, "food": row.get("item_name") or row.item_code, "unit": row.uom,
        "gross": str(gross / serving if gross else 0), "amounts": {},
    }
    if not gross:
        result["issue"] = "缺少有效的带量"
        return result
    stock_conversion = configured_conversion(item, row.uom, conversions) if item else None
    factor = unit_factor(row.uom, stock_masses.get(row.item_code), stock_conversion)
    amounts, grams, basis = ingredient_amounts(gross, number(row.get(NET_QTY)), factor,
                                               nutrient_values(profile) if profile else {})
    if profile:
        result.update(profile=profile.name, source_reference=profile.source_reference)
    if grams is None:
        result["issue"] = basis
    else:
        result.update(grams=str(grams / serving), weight_basis=basis, grams_per_unit=str(factor),
                      amounts={key: str(value / serving) for key, value in amounts.items()})
        if not profile:
            result["issue"] = "缺少已审核的营养档案"
    return result


def _calculate(recipes):
    codes = {row.item_code for rows in recipes.values() for row in rows}
    if not codes:
        return {}
    items = {item.name: item for item in frappe.get_all("Item", filters={"name": ["in", sorted(codes)]},
                                                       fields=["name", "stock_uom", "variant_of"])}
    conversions = conversion_rows(items.values())
    units_by_item = defaultdict(dict)
    for (code, unit), factor in conversions.items():
        units_by_item[code][unit] = factor
    stock_masses = {
        code: stock_mass_in_grams(item.stock_uom, {**units_by_item[item.variant_of], **units_by_item[code]})
        for code, item in items.items()
    }
    profiles = approved_profiles(codes)
    return {name: [_line(row, row.serving, items.get(row.item_code), profiles.get(row.item_code),
                         conversions, stock_masses)
                   for row in rows] for name, rows in recipes.items()}


def _decode(value):
    return json.loads(value) if value else None


def _encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def recipe_values(names, *, fixed=None):
    names = sorted(set(filter(None, names)))
    if not names:
        return {}
    values = {name: (fixed or {})[name] for name in names if name in (fixed or {})}
    live = [name for name in names if name not in values]
    if not live:
        return values
    recipes = {}
    for bom in frappe.get_all("BOM", filters={"name": ["in", live]},
                              fields=["name", "docstatus", "quantity", SNAPSHOT]):
        saved = _decode(bom.get(SNAPSHOT)) if bom.docstatus == 1 else None
        if saved is not None:
            values[bom.name] = saved
        elif serving := positive(bom.quantity):
            recipes[bom.name] = (serving, [])
    if recipes:
        for row in frappe.get_all("BOM Item", filters={"parent": ["in", sorted(recipes)],
                                  "parentfield": "items", "parenttype": "BOM"},
                                  fields=["parent", "item_code", "item_name", "qty", "uom", NET_QTY],
                                  order_by="parent asc, idx asc"):
            row.serving, rows = recipes[row.parent]
            rows.append(row)
        values.update(_calculate({name: rows for name, (_, rows) in recipes.items()}))
    return values


def freeze_recipe(doc, method=None):
    if doc.get(MARKER) and frappe.get_meta("BOM").has_field(SNAPSHOT):
        serving = positive(doc.quantity)
        rows = [frappe._dict(item_code=row.item_code, item_name=row.item_name, qty=row.qty,
                             uom=row.uom, serving=serving, **{NET_QTY: row.get(NET_QTY)})
                for row in doc.items]
        doc.set(SNAPSHOT, _encode(_calculate({doc.name: rows}).get(doc.name, [])))


def freeze_week(doc, method=None):
    if not frappe.get_meta(doc.doctype).has_field(SNAPSHOT):
        return
    from ione_core.meal_planning import _bound_plan

    names = {dish.bom_no for meal in doc.meals if not meal.get("service_suspended")
             for dish in _bound_plan(doc, meal).po_items}
    doc.set(SNAPSHOT, _encode(recipe_values(names)))


def freeze_adjustment(doc, method=None):
    if not frappe.get_meta(doc.doctype).has_field(SNAPSHOT):
        return
    week = _decode(frappe.db.get_value("Meal Planning Week", doc.meal_week, SNAPSHOT)) or {}
    prior = (_decode(frappe.db.get_value(doc.doctype, doc.source_adjustment, SNAPSHOT))
             if doc.source_adjustment else None)
    names = [] if doc.service_suspended else [dish.bom_no for dish in doc.dishes]
    doc.set(SNAPSHOT, _encode(recipe_values(names, fixed={**week, **(prior or {})})))


def for_week(source):
    details = source["details"]
    week = source["source"].get("week_name")
    fixed, changes = {}, {}
    if week:
        fixed = _decode(frappe.db.get_value("Meal Planning Week", {"name": week, "docstatus": 1}, SNAPSHOT)) or {}
        plans = sorted({row["plan_name"] for row in details if row.get("plan_name")})
        if plans:
            changes = {
                row.replacement_plan: _decode(row.get(SNAPSHOT))
                for row in frappe.get_all("Meal Plan Adjustment", filters={
                    "meal_week": week, "docstatus": 1, "replacement_plan": ["in", plans],
                    SNAPSHOT: ["is", "set"],
                }, fields=["replacement_plan", SNAPSHOT])
            }
    result = weekly_totals(details, source["dates"], recipe_values((row.get("bom_no") for row in details),
                                                                  fixed=fixed), changes)
    result["frozen"] = bool(fixed)
    return result


def _metrics(lines):
    totals = summarize(lines)
    return [
        {"key": key, "label": name, "unit": unit,
         "value": float(totals[key]["value"]) if totals[key]["value"] is not None else None,
         "covered": totals[key]["covered"], "total": totals[key]["total"]}
        for key, (name, unit) in NUTRIENTS.items()
    ]


def _public_lines(lines):
    return [{**line, "amounts": {key: float(value) for key, value in line["amounts"].items()}} for line in lines]


@frappe.whitelist(methods=["GET"])
def for_dish(recipe: str):
    doc = frappe.get_doc("BOM", recipe)
    doc.check_permission("read")
    if not doc.get(MARKER) or doc.docstatus == 2:
        frappe.throw("请选择有效的标准菜品配方。")
    lines = recipe_values([recipe]).get(recipe, [])
    return {"metrics": _metrics(lines), "lines": _public_lines(lines),
            "frozen": bool(doc.docstatus == 1 and doc.get(SNAPSHOT))}


def weekly_totals(details, dates, recipes, by_plan=None):
    """Match recipe lines by ingredient and UOM, preserving repeated ingredients."""
    grouped, used = {}, {}
    for row in details:
        key = (str(row["meal_date"]), row["meal_type"], row.get("plan_name"),
               row.get("bom_no"), row["ingredient_code"], row["uom"])
        grouped[key] = grouped.get(key, Decimal(0)) + (positive(row["per_child_qty"]) or Decimal(0))
        used[key] = row
    day_lines = defaultdict(list)
    meal_lines = defaultdict(list)
    for key, gross in grouped.items():
        day, meal, plan, bom, ingredient, uom = key
        selected = (by_plan or {}).get(plan, {}).get(bom, recipes.get(bom, []))
        lines = [line for line in selected if (line["code"], line["unit"]) == (ingredient, uom)]
        recipe_gross = sum((number(line["gross"]) for line in lines), Decimal(0))
        if recipe_gross and gross:
            basis = gross / recipe_gross
            lines = [{**line, "amounts": {k: number(v) * basis for k, v in line["amounts"].items()}}
                     for line in lines]
        else:
            lines = [{"code": ingredient, "food": used[key]["ingredient_name"], "unit": uom,
                      "issue": "缺少对应的配方带量", "amounts": {}}]
        for line in lines:
            line = {**line, "date": day, "meal": meal, "recipe": bom}
            day_lines[day].append(line)
            meal_lines[day, meal].append(line)
    all_lines = [line for lines in day_lines.values() for line in lines]
    profiles = {}
    for line in all_lines:
        if profile := line.get("profile"):
            reference = line.get("source_reference") or " · ".join(
                line[key] for key in ("source", "source_code", "source_version") if line.get(key))
            profiles.setdefault(profile, {"profile": profile, "food": line["food"], "source_reference": reference})
    return {
        "metrics": _metrics(all_lines),
        "days": [{"date": day, "metrics": _metrics(day_lines[day])} for day in dates],
        "meals": [{"date": day, "meal": meal, "metrics": _metrics(lines)}
                  for (day, meal), lines in meal_lines.items()],
        "issues": [{key: line[key] for key in ("code", "food", "date", "meal", "issue")}
                   for line in all_lines if "issue" in line],
        "profiles": list(profiles.values()),
    }
