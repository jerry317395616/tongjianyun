"""Standard food ingredients are ERPNext Items shared by recipes and purchases."""

from math import isfinite
from unicodedata import normalize
from uuid import uuid4

import frappe
from erpnext.stock.doctype.item.item import get_uom_conv_factor

from tongjianyun.standard_recipes import DISH, MARKER as RECIPE

MARKER = "custom_tjy_standard_ingredient"
ALIASES = "custom_tjy_ingredient_aliases"
LAYOUT = "标准食材档案"
LIBRARY = "标准食材库"
INGREDIENT_GROUPS = (
    "粮油及主食", "蔬菜", "水果", "肉禽水产", "蛋奶及豆制品", "干货", "调味品", "食谱样例食材",
)
CLASSIFIED_GROUPS = frozenset(INGREDIENT_GROUPS[:-1])
PACKAGING_UNITS = {
    "box", "carton", "case", "bag", "pack", "packet", "bottle", "can", "jar", "nos", "piece",
    "箱", "盒", "袋", "包", "瓶", "罐", "桶", "件", "个", "只", "支", "片", "条", "份",
}


def name_key(value):
    return "".join(normalize("NFKC", value or "").casefold().split())


def aliases_for(value):
    aliases = {}
    for line in (value or "").splitlines():
        if key := name_key(line):
            aliases.setdefault(key, line.strip())
    return aliases


def _new_item_code():
    return f"TJY-AUTO-{uuid4().hex[:20].upper()}"


@frappe.whitelist(methods=["GET"])
def new_ingredient_code():
    frappe.has_permission("Item", "create", throw=True)
    return _new_item_code()


def set_ingredient_code(doc, method=None):
    if doc.get(MARKER) and not (doc.item_code or "").strip():
        doc.item_code = _new_item_code()


def validate_ingredient(doc, method=None):
    if not doc.get(MARKER):
        return
    if doc.get(DISH) or doc.is_fixed_asset:
        frappe.throw("标准食材须使用独立的食材物料。")
    if doc.is_new():
        name = (doc.item_name or "").strip()
        if not name or name == (doc.item_code or "").strip():
            frappe.throw("请填写标准食材名称。")
        doc.item_name = name
        if doc.item_group not in CLASSIFIED_GROUPS:
            frappe.throw("请选择粮油及主食、蔬菜、水果、肉禽水产、蛋奶及豆制品、干货或调味品物料组。")
    aliases = aliases_for(doc.get(ALIASES))
    aliases.pop(name_key(doc.item_name), None)
    doc.set(ALIASES, "\n".join(aliases.values()))


def enroll_items(codes):
    if not codes:
        return 0
    names = frappe.get_all("Item", filters={
        "name": ["in", sorted(set(codes))], "disabled": 0, DISH: 0, "is_fixed_asset": 0,
        "include_item_in_manufacturing": 1, "item_group": ["in", INGREDIENT_GROUPS], MARKER: 0,
    }, pluck="name")
    if names:
        frappe.db.set_value("Item", {"name": ["in", names], MARKER: 0}, MARKER, 1, update_modified=False)
    return len(names)


def enroll_from_recipe(doc, method=None):
    if doc.get(RECIPE) and doc.is_active:
        enroll_items([row.item_code for row in doc.items])


def recipe_ingredient_rows(boms):
    if not boms:
        return []
    return frappe.get_all("BOM Item", filters={
        "parent": ["in", boms], "parenttype": "BOM", "parentfield": "items",
    }, fields=["item_code", "uom"], distinct=True)


def enroll_existing():
    frappe.only_for("System Manager")
    names = frappe.get_all("BOM", filters={RECIPE: 1, "docstatus": 1, "is_active": 1}, pluck="name")
    return enroll_items([row.item_code for row in recipe_ingredient_rows(names)])


def _positive(value):
    number = float(value or 0)
    return number if number > 0 and isfinite(number) else 0


def configured_conversion(item, unit, factors, generic=get_uom_conv_factor):
    """Resolve a real conversion even when ERPNext's UI falls back to a value of one."""
    stock_unit = item.get("stock_uom")
    if not unit or not stock_unit:
        return 0
    if unit == stock_unit:
        return 1
    for code in (item.get("name"), item.get("variant_of")):
        if code and (code, unit) in factors:
            return _positive(factors[code, unit])
    if {name_key(unit), name_key(stock_unit)} & PACKAGING_UNITS:
        return 0
    return _positive(generic(unit, stock_unit))


def conversion_rows(items):
    codes = {row.name for row in items} | {row.variant_of for row in items if row.variant_of}
    if not codes:
        return {}
    return {(row.parent, row.uom): row.conversion_factor for row in frappe.get_all(
        "UOM Conversion Detail", filters={
            "parent": ["in", sorted(codes)], "parenttype": "Item", "parentfield": "uoms",
        }, fields=["parent", "uom", "conversion_factor"],
    )}
