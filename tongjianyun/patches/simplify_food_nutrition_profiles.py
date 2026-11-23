"""Preserve legacy provenance and normalize profiles after the DocType sync."""

from decimal import Decimal

import frappe

from tongjianyun.food_nutrition import PROFILE, SOURCE_REFERENCE
from tongjianyun.ingredient_library import conversion_rows
from tongjianyun.nutrition_math import NUTRIENTS, mass_in_grams, number, positive, stock_mass_in_grams

LEGACY_SOURCE_FIELDS = (
    ("food_name", "原资料食物名称"), ("food_state", "原资料食材状态"), ("source_name", "原数据来源"),
    ("source_code", "条目编号或商品规格"), ("source_version", "来源版本或标签日期"),
    ("source_url", "来源链接"), ("evidence", "原资料凭证"), ("basis", "原计量口径"),
    ("basis_grams", "原口径对应克数"), ("edible_pct", "原参考可食率（仅供追溯）"),
    ("grams_per_stock_unit", "原库存单位对应克数"), ("basis_note", "原资料说明"),
)
VOLUME_UNITS = {
    "ml": 1, "milliliter": 1, "milliliters": 1, "毫升": 1,
    "l": 1000, "liter": 1000, "litre": 1000, "升": 1000,
}


def execute():
    if not frappe.db.table_exists(PROFILE):
        return
    columns = set(frappe.db.get_table_columns(PROFILE))
    if "basis" not in columns:
        return
    selected = ["name", "item_code", "docstatus", SOURCE_REFERENCE, *NUTRIENTS]
    selected.extend(key for key, _ in LEGACY_SOURCE_FIELDS if key in columns)
    rows = frappe.db.sql(
        f"SELECT {', '.join(f'`{key}`' for key in selected)} FROM `tab{PROFILE}` "
        "ORDER BY approved_at DESC, name DESC",
        as_dict=True,
    )
    checked_items = set()
    for row in rows:
        if not row.get(SOURCE_REFERENCE):
            values = _normalized_nutrients(row)
            values[SOURCE_REFERENCE] = "\n".join(f"{label}：{row[key]}" for key, label in LEGACY_SOURCE_FIELDS
                                                if row.get(key) not in (None, ""))
            if values[SOURCE_REFERENCE]:
                frappe.db.set_value(PROFILE, row.name, values, update_modified=False)
        if row.docstatus == 1 and row.item_code not in checked_items:
            _migrate_stock_weight(row)
            checked_items.add(row.item_code)


def _normalized_nutrients(row):
    source_values = {key: row.get(key) for key in NUTRIENTS if row.get(key) not in (None, "")}
    if row.basis == "每100克" or not source_values:
        return {}
    grams = positive(row.get("basis_grams"))
    if row.basis not in ("每100毫升", "每份") or not grams:
        frappe.throw(f"营养档案 {row.name} 缺少可核实的原口径重量，无法换算成每 100 克。")
    normalized = {}
    for key, raw in source_values.items():
        amount = number(raw)
        if amount is None or amount < 0:
            frappe.throw(f"营养档案 {row.name} 有无法换算的营养值。")
        value = amount * 100 / grams
        if value > 100000000:
            frappe.throw(f"营养档案 {row.name} 的换算值超出可录入范围，请核对原始数据。")
        value = value.quantize(Decimal("0.000000000001"))
        if not value and amount:
            frappe.throw(f"营养档案 {row.name} 的换算值超出可录入精度，请核对原始数据。")
        normalized[key] = format(value.normalize(), "f")
    return normalized


def _same_weight(first, second):
    return abs(first / second - 1) <= Decimal("0.000001")


def _migrate_stock_weight(row):
    grams = positive(row.get("grams_per_stock_unit"))
    if not grams and row.basis != "每100毫升":
        return
    item = frappe.get_doc("Item", row.item_code, for_update=True)
    if item.disabled or mass_in_grams(item.stock_uom):
        return
    if not grams:
        density_grams = positive(row.get("basis_grams"))
        stock_volume = VOLUME_UNITS.get((item.stock_uom or "").strip().casefold())
        if not density_grams or not stock_volume:
            return
        grams = density_grams * stock_volume / 100

    conversions = conversion_rows([item])
    inherited = {unit: factor for (code, unit), factor in conversions.items() if code == item.variant_of}
    own = {unit: factor for (code, unit), factor in conversions.items() if code == item.name}
    factors = {**inherited, **own}
    if any(mass_in_grams(unit) for unit in factors):
        existing = stock_mass_in_grams(item.stock_uom, factors)
        if not existing or not _same_weight(existing, grams):
            frappe.throw(f"食材 {item.name} 的计量单位与营养档案 {row.name} 记录的重量不一致。")
        return
    units = frappe.get_all("UOM", filters={"enabled": 1}, pluck="name")
    # Prefer the site's gram unit. A larger mass unit can represent very small
    # conversion factors more accurately within ERPNext's nine-decimal precision.
    weights = sorted((mass != 1, -mass, unit) for unit in units if (mass := mass_in_grams(unit)))
    for _, neg_mass, unit in weights:
        mass = -neg_mass
        factor = (mass / grams).quantize(Decimal("0.000000001"))
        if factor and _same_weight(mass / factor, grams):
            item.append("uoms", {"uom": unit, "conversion_factor": float(factor)})
            item.save(ignore_permissions=True)
            return
    frappe.throw(f"食材 {item.name} 的旧重量无法用当前计量单位精确换算，请核对单位。")
