"""Reviewed food-composition profiles linked to standard ingredient Items."""

from decimal import Decimal

import frappe

from tongjianyun.ingredient_library import MARKER
from tongjianyun.nutrition_math import NUTRIENTS, PER_100_G, PER_100_ML, PER_SERVING, number

PROFILE = "Tongjianyun Food Nutrition Profile"
STATUS = "custom_tjy_nutrition_status"
MISSING, REVIEW, MATCHED = "缺少数据", "待审核", "已匹配"


def validate_profile(doc):
    item = frappe.get_doc("Item", doc.item_code, for_update=True)
    item.check_permission("read")
    if not item.get(MARKER) or item.disabled:
        frappe.throw("请选择启用的标准食材。")
    previous = doc.get_doc_before_save()
    if previous and previous.item_code != doc.item_code:
        frappe.throw("请为其他食材新建档案。")
    if doc.basis not in (PER_100_G, PER_100_ML, PER_SERVING):
        frappe.throw("请选择原始营养值口径。")
    if doc.basis == PER_100_G:
        doc.basis_grams = "100"
    for field in ("food_name", "source_name", "source_code", "source_version"):
        doc.set(field, (doc.get(field) or "").strip())
    for field in (*NUTRIENTS, "basis_grams", "edible_pct", "grams_per_stock_unit"):
        raw = doc.get(field)
        if isinstance(raw, str):
            raw = raw.strip()
        value = number(raw)
        if raw in ("", None) and field != "basis_grams":
            doc.set(field, None)
            continue
        minimum = 0 if field in NUTRIENTS else Decimal("0.000001")
        maximum = 100 if field == "edible_pct" else 100000000
        if value is None or not minimum <= value <= maximum or value.as_tuple().exponent < -12:
            frappe.throw(f"请核对「{doc.meta.get_label(field)}」的数值和单位。")
        doc.set(field, format(value, "f"))
    if doc.docstatus == 1 and not any(doc.get(key) is not None for key in NUTRIENTS):
        frappe.throw("请至少录入一项可核实的营养值。")


def sync_status(item_code, exclude=None):
    if not item_code:
        return
    frappe.db.get_value("Item", item_code, "name", for_update=True)
    filters = {"item_code": item_code, "docstatus": ["<", 2]}
    if exclude:
        filters["name"] = ["!=", exclude]
    state = frappe.db.get_value(PROFILE, filters, "docstatus", order_by="docstatus desc")
    value = MATCHED if state == 1 else REVIEW if state == 0 else MISSING
    frappe.db.set_value("Item", item_code, STATUS, value, update_modified=False)


def approved_profiles(codes):
    if not codes:
        return {}
    rows = frappe.get_all(
        PROFILE, filters={"item_code": ["in", sorted(set(codes))], "docstatus": 1},
        fields=["name", "item_code", "food_name", "food_state", "source_name", "source_code",
                "source_version", "basis", "basis_grams", "edible_pct", "grams_per_stock_unit", *NUTRIENTS],
        order_by="approved_at desc, name desc",
    )
    profiles = {}
    for row in rows:
        profiles.setdefault(row.item_code, row)
    return profiles


def nutrient_values(profile):
    return {key: value for key in NUTRIENTS if (value := number(profile.get(key))) is not None}


@frappe.whitelist(methods=["GET"])
def ingredient_profile(item_code: str):
    item = frappe.get_doc("Item", item_code)
    item.check_permission("read")
    if not item.get(MARKER):
        frappe.throw("请选择标准食材。")
    result = {"status": item.get(STATUS) or MISSING, "labels": NUTRIENTS}
    profile = approved_profiles([item_code]).get(item_code)
    if profile:
        frappe.get_doc(PROFILE, profile.name).check_permission("read")
        factor = 100 / number(profile.basis_grams)
        result.update(profile=profile, nutrients={key: float(value * factor)
                      for key, value in nutrient_values(profile).items()}, stock_uom=item.stock_uom)
    return result
