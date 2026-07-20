from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _

GENERIC_DOCTYPE = "Tongjianyun Data Record"

RECORD_DOCTYPES = {
    "meal_generation_config": "Tongjianyun Meal Nutrition",
    "meal_draft": "Tongjianyun Meal Nutrition",
    "meal_review_history": "Tongjianyun Meal Nutrition",
    "dish_catalog": "Tongjianyun Dish Catalog",
    "ingredient_spec": "Tongjianyun Ingredient Spec",
    "food_category": "Tongjianyun Food Category",
    "ingredient_food_category_mapping": "Tongjianyun Food Category Mapping",
    "nutrition_standard": "Tongjianyun Nutrition Standard",
    "food_purchase": "Tongjianyun Food Purchase",
    "food_supplier": "Tongjianyun Food Supplier",
    "food_sample": "Tongjianyun Food Sample",
    "food_trace_event": "Tongjianyun Food Trace Event",
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
        return json.loads(value) if value.strip() else {}
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


def _doctype_for(record_type: str) -> str:
    return RECORD_DOCTYPES.get(_clean(record_type), GENERIC_DOCTYPE)


def _record_key(record_type: str, record_id: str) -> str:
    record_type = _clean(record_type)
    record_id = _clean(record_id)
    if not record_type or not record_id:
        frappe.throw(_("record_type and record_id are required."))
    return f"{record_type}::{record_id}"


def _json_default(value: Any) -> str:
    return str(value)


def _record_from_doc(doc) -> Any:
    try:
        return json.loads(doc.record_json or "null")
    except Exception:
        return None


def _apply_meta(doc, record_type: str, record_id: str, record: Any, meta: Any = None) -> None:
    meta_dict = _as_dict(meta)
    doc.data_key = _record_key(record_type, record_id)
    doc.record_type = _clean(record_type)
    doc.record_id = _clean(record_id)
    title = meta_dict.get("title")
    if title is None and isinstance(record, dict):
        title = record.get("name") or record.get("title") or record.get("standardName") or record.get("ingredient") or record_id
    doc.title = str(title or record_id)[:140]
    doc.status = str(meta_dict.get("status") or "")[:140]
    doc.risk = str(meta_dict.get("risk") or "")[:140]
    doc.category = str(meta_dict.get("category") or "")[:140]
    doc.parent_id = str(meta_dict.get("parent_id") or "")[:140]
    doc.source = str(meta_dict.get("source") or "")[:140]
    try:
        doc.sort_order = int(meta_dict.get("sort_order") or 100)
    except Exception:
        doc.sort_order = 100
    doc.record_json = json.dumps(record, ensure_ascii=False, default=_json_default)


def _save_doc(doc) -> None:
    doc.flags.ignore_permissions = True
    if doc.name:
        doc.save(ignore_permissions=True)
    else:
        doc.insert(ignore_permissions=True)


def _copy_doc_fields(source, target) -> None:
    for fieldname in [
        "data_key", "record_type", "record_id", "title", "status", "risk",
        "category", "parent_id", "source", "sort_order", "record_json",
    ]:
        setattr(target, fieldname, getattr(source, fieldname, None))


def migrate_generic_records() -> dict[str, int]:
    """Copy existing generic records into the dedicated DocTypes.

    Kept callable from bench execute; storage reads dedicated DocTypes after this change.
    """
    copied = 0
    skipped = 0
    if not frappe.db.table_exists(GENERIC_DOCTYPE):
        return {"copied": 0, "skipped": 0}
    for row in frappe.get_all(GENERIC_DOCTYPE, fields=["name", "record_type"], limit_page_length=0):
        target_doctype = _doctype_for(row.record_type)
        if target_doctype == GENERIC_DOCTYPE or not frappe.db.table_exists(target_doctype):
            skipped += 1
            continue
        source = frappe.get_doc(GENERIC_DOCTYPE, row.name)
        existing = frappe.db.exists(target_doctype, {"data_key": source.data_key})
        target = frappe.get_doc(target_doctype, existing) if existing else frappe.new_doc(target_doctype)
        _copy_doc_fields(source, target)
        _save_doc(target)
        copied += 1
    frappe.db.commit()
    return {"copied": copied, "skipped": skipped}


@frappe.whitelist()
def list_records(record_type: str) -> list[Any]:
    _require_login()
    record_type = _clean(record_type)
    doctype = _doctype_for(record_type)
    rows = frappe.get_all(
        doctype,
        filters={"record_type": record_type},
        fields=["name"],
        order_by="sort_order asc, modified desc",
        limit_page_length=0,
    )
    return [_record_from_doc(frappe.get_doc(doctype, row.name)) for row in rows]


@frappe.whitelist()
def get_record(record_type: str, record_id: str) -> Any | None:
    _require_login()
    doctype = _doctype_for(record_type)
    name = frappe.db.exists(doctype, {"data_key": _record_key(record_type, record_id)})
    return _record_from_doc(frappe.get_doc(doctype, name)) if name else None


@frappe.whitelist()
def upsert_record(record_type: str, record_id: str, record: Any = None, meta: Any = None) -> Any:
    _require_login()
    record_value = record if not isinstance(record, str) else json.loads(record) if record.strip() else None
    doctype = _doctype_for(record_type)
    key = _record_key(record_type, record_id)
    existing = frappe.db.exists(doctype, {"data_key": key})
    doc = frappe.get_doc(doctype, existing) if existing else frappe.new_doc(doctype)
    _apply_meta(doc, record_type, record_id, record_value, meta)
    _save_doc(doc)
    frappe.db.commit()
    return _record_from_doc(doc)


@frappe.whitelist()
def delete_record(record_type: str, record_id: str) -> Any | None:
    _require_login()
    doctype = _doctype_for(record_type)
    name = frappe.db.exists(doctype, {"data_key": _record_key(record_type, record_id)})
    if not name:
        return None
    doc = frappe.get_doc(doctype, name)
    record = _record_from_doc(doc)
    frappe.delete_doc(doctype, name, ignore_permissions=True)
    frappe.db.commit()
    return record


@frappe.whitelist()
def delete_records(record_type: str, record_ids: Any = None) -> dict[str, int]:
    _require_login()
    doctype = _doctype_for(record_type)
    ids = [_clean(item) for item in _as_list(record_ids) if _clean(item)]
    deleted = 0
    for record_id in ids:
        name = frappe.db.exists(doctype, {"data_key": _record_key(record_type, record_id)})
        if name:
            frappe.delete_doc(doctype, name, ignore_permissions=True)
            deleted += 1
    frappe.db.commit()
    return {"deleted": deleted}


@frappe.whitelist()
def replace_records(record_type: str, records: Any = None) -> dict[str, int]:
    _require_login()
    record_type = _clean(record_type)
    if not record_type:
        frappe.throw(_("record_type is required."))
    doctype = _doctype_for(record_type)
    for row in frappe.get_all(doctype, filters={"record_type": record_type}, fields=["name"], limit_page_length=0):
        frappe.delete_doc(doctype, row.name, ignore_permissions=True)
    imported = 0
    for item in _as_list(records):
        item_dict = _as_dict(item)
        record_id = _clean(item_dict.get("record_id") or item_dict.get("recordId"))
        record = item_dict.get("record")
        if isinstance(record, str):
            record = json.loads(record) if record.strip() else None
        if not record_id:
            frappe.throw(_("record_id is required."))
        doc = frappe.new_doc(doctype)
        _apply_meta(doc, record_type, record_id, record, item_dict.get("meta"))
        _save_doc(doc)
        imported += 1
    frappe.db.commit()
    total = frappe.db.count(doctype, {"record_type": record_type})
    return {"imported": imported, "total": int(total or 0)}
