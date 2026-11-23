"""Reviewed food-composition profiles linked to standard ingredient Items."""

import frappe

from tongjianyun.ingredient_library import MARKER
from tongjianyun.nutrition_math import NUTRIENTS, number

PROFILE = "Tongjianyun Food Nutrition Profile"
STATUS = "custom_tjy_nutrition_status"
MISSING, REVIEW, MATCHED = "缺少数据", "待审核", "已匹配"
EDITOR_FIELDS = tuple(NUTRIENTS)
SOURCE_REFERENCE = "source_reference"


def validate_profile(doc):
    item = frappe.get_doc("Item", doc.item_code, for_update=True)
    item.check_permission("read")
    if not item.get(MARKER) or item.disabled:
        frappe.throw("请选择启用的标准食材。")
    previous = doc.get_doc_before_save()
    if previous and previous.item_code != doc.item_code:
        frappe.throw("请为其他食材新建档案。")
    doc.source_reference = (doc.source_reference or "").strip()
    for field in NUTRIENTS:
        raw = doc.get(field)
        if raw is None or not str(raw).strip():
            doc.set(field, None)
            continue
        value = number(str(raw).strip())
        if value is None or not 0 <= value <= 100000000 or value.as_tuple().exponent < -12:
            frappe.throw(f"请核对「{doc.meta.get_label(field)}」的数值和单位。")
        doc.set(field, format(value, "f"))
    if doc.docstatus == 1:
        if not doc.source_reference:
            frappe.throw("审核前请填写来源依据。")
        if not any(doc.get(key) is not None for key in NUTRIENTS):
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
        fields=["name", "item_code", SOURCE_REFERENCE, *NUTRIENTS],
        order_by="approved_at desc, name desc",
    )
    profiles = {}
    for row in rows:
        profiles.setdefault(row.item_code, row)
    return profiles


def nutrient_values(profile):
    return {key: value for key in NUTRIENTS if (value := number(profile.get(key))) is not None}


def _standard_item(item_code, *, lock=False):
    item = frappe.get_doc("Item", item_code, for_update=lock)
    item.check_permission("read")
    if not item.get(MARKER):
        frappe.throw("请选择标准食材。")
    return item


@frappe.whitelist(methods=["GET"])
def ingredient_profile(item_code: str):
    item = _standard_item(item_code)
    result = {"status": item.get(STATUS) or MISSING, "labels": NUTRIENTS}
    profile = approved_profiles([item_code]).get(item_code)
    if profile:
        frappe.get_doc(PROFILE, profile.name).check_permission("read")
        result.update(profile=profile, nutrients={key: float(value)
                      for key, value in nutrient_values(profile).items()}, stock_uom=item.stock_uom)
    return result


def _latest_draft(item_code):
    drafts = frappe.get_list(PROFILE, filters={"item_code": item_code, "docstatus": 0}, pluck="name",
                             order_by="modified desc, name desc", limit_page_length=1)
    return drafts[0] if drafts else None


def _editor_record(name):
    if not name:
        return None
    profile = frappe.get_doc(PROFILE, name)
    profile.check_permission("read")
    profile.apply_fieldlevel_read_permissions()
    return {"name": profile.name, "modified": str(profile.modified),
            "writable": profile.docstatus == 0 and profile.has_permission("write"),
            "values": {fieldname: profile.get(fieldname) for fieldname in EDITOR_FIELDS}}


def _ingredient_editor(item):
    frappe.has_permission(PROFILE, "read", throw=True)
    approved = approved_profiles([item.name]).get(item.name)
    return {
        "status": frappe.db.get_value("Item", item.name, STATUS) or MISSING,
        "draft": _editor_record(_latest_draft(item.name)),
        "approved": _editor_record(approved.name) if approved else None,
        "can_create": not item.disabled and frappe.has_permission(PROFILE, "create"),
        "disabled": bool(item.disabled),
        "editable_fields": EDITOR_FIELDS,
    }


@frappe.whitelist(methods=["GET"])
def ingredient_editor(item_code: str):
    return _ingredient_editor(_standard_item(item_code))


@frappe.whitelist(methods=["POST"])
def save_ingredient_profile(item_code: str, values, name: str | None = None, modified: str | None = None):
    item = _standard_item(item_code, lock=not name)
    if item.disabled:
        frappe.throw("请选择启用的标准食材。")
    values = frappe.parse_json(values)
    if not isinstance(values, dict) or any(fieldname not in EDITOR_FIELDS or
            (value is not None and not isinstance(value, str)) for fieldname, value in values.items()):
        frappe.throw("营养档案表单数据无效。")
    if name:
        profile = frappe.get_doc(PROFILE, name, for_update=True)
        profile.check_permission("write")
        if profile.item_code != item.name or profile.docstatus != 0:
            frappe.throw("请选择当前食材的草稿营养档案。")
        if str(profile.modified) != modified:
            frappe.throw("营养档案已变更，请刷新页面后再编辑。", frappe.TimestampMismatchError)
    else:
        frappe.has_permission(PROFILE, "create", throw=True)
        if frappe.db.exists(PROFILE, {"item_code": item.name, "docstatus": 0}):
            frappe.throw("此食材已有草稿，请刷新页面后编辑现有档案。")
        profile = frappe.new_doc(PROFILE, item_code=item.name)
    profile.update(values)
    profile.save()
    return _ingredient_editor(item)
