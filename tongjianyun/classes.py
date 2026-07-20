from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import now_datetime

DOCTYPE = "Tongjianyun Class"
CHILD_DOCTYPE = "Tongjianyun Child"
DEFAULT_STATUS = "\u0061\u0063\u0074\u0069\u0076\u0065"
DEFAULT_GRADE = "\u6df7\u9f84\u73ed"


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


def _require_login() -> None:
    if frappe.session.user == "Guest":
        frappe.throw(_("Not logged in."), frappe.AuthenticationError)


def _now_text() -> str:
    return now_datetime().strftime("%Y-%m-%d %H:%M:%S")


def _grade_by_name(name: str) -> str:
    if name.startswith("\u6258"):
        return "\u6258\u73ed"
    if name.startswith("\u5c0f"):
        return "\u5c0f\u73ed"
    if name.startswith("\u4e2d"):
        return "\u4e2d\u73ed"
    if name.startswith("\u5927"):
        return "\u5927\u73ed"
    return DEFAULT_GRADE


def _meal_age_group(grade: str) -> str:
    if grade in ["\u6258\u73ed", "\u5c0f\u73ed", "\u4e2d\u73ed", "\u5927\u73ed"]:
        return grade
    return "3-6 \u5c81\u5e7c\u513f"


def _class_child_count(class_name: str) -> int:
    if not frappe.db.table_exists(CHILD_DOCTYPE):
        return 0
    return frappe.db.count(CHILD_DOCTYPE, {"class_name": class_name})


def _record_from_doc(doc) -> dict[str, Any]:
    child_count = _class_child_count(doc.class_name)
    return {
        "id": doc.class_id,
        "name": doc.class_name,
        "grade": doc.grade or _grade_by_name(doc.class_name or ""),
        "headTeacher": doc.head_teacher or "",
        "assistantTeacher": doc.assistant_teacher or "",
        "roomName": doc.room_name or "",
        "capacity": int(doc.capacity or 30),
        "childCount": child_count,
        "mealAgeGroup": doc.meal_age_group or _meal_age_group(doc.grade or ""),
        "status": doc.status or DEFAULT_STATUS,
        "remark": doc.remark or "",
        "sortOrder": int(doc.sort_order or 10),
        "createdAt": doc.created_at or "",
        "updatedAt": doc.updated_at or "",
    }


def _next_sort_order() -> int:
    value = frappe.db.sql(f"select coalesce(max(sort_order), 0) + 10 from `tab{DOCTYPE}`")[0][0]
    return int(value or 10)


def _new_class_id() -> str:
    while True:
        class_id = f"CLASS-{frappe.generate_hash(length=8).upper()}"
        if not frappe.db.exists(DOCTYPE, {"class_id": class_id}):
            return class_id


def _save_doc(doc) -> None:
    doc.flags.ignore_permissions = True
    if doc.name:
        doc.save(ignore_permissions=True)
    else:
        doc.insert(ignore_permissions=True)


def _upsert_class(record: dict[str, Any]) -> dict[str, Any]:
    class_name = str(record.get("name") or record.get("className") or "").strip()
    if not class_name:
        frappe.throw(_("Class name is required."))
    class_id = str(record.get("id") or "").strip()
    existing = frappe.db.exists(DOCTYPE, {"class_id": class_id}) if class_id else None
    if not existing:
        existing = frappe.db.exists(DOCTYPE, {"class_name": class_name})
    doc = frappe.get_doc(DOCTYPE, existing) if existing else frappe.new_doc(DOCTYPE)
    if not class_id:
        class_id = doc.class_id or _new_class_id()
    grade = str(record.get("grade") or doc.grade or _grade_by_name(class_name)).strip()
    now_text = _now_text()
    doc.class_id = class_id
    doc.class_name = class_name
    doc.grade = grade
    doc.head_teacher = str(record.get("headTeacher") if record.get("headTeacher") is not None else doc.head_teacher or "").strip()
    doc.assistant_teacher = str(record.get("assistantTeacher") if record.get("assistantTeacher") is not None else doc.assistant_teacher or "").strip()
    doc.room_name = str(record.get("roomName") if record.get("roomName") is not None else doc.room_name or "").strip()
    doc.capacity = int(record.get("capacity") or doc.capacity or 30)
    doc.child_count = _class_child_count(class_name)
    doc.meal_age_group = str(record.get("mealAgeGroup") or doc.meal_age_group or _meal_age_group(grade)).strip()
    doc.status = str(record.get("status") or doc.status or DEFAULT_STATUS).strip()
    doc.remark = str(record.get("remark") if record.get("remark") is not None else doc.remark or "").strip()
    doc.sort_order = int(record.get("sortOrder") or doc.sort_order or _next_sort_order())
    doc.created_at = str(record.get("createdAt") or doc.created_at or now_text)
    doc.updated_at = str(record.get("updatedAt") or now_text)
    _save_doc(doc)
    return _record_from_doc(doc)


def _move_children_to_class(old_name: str, new_name: str) -> None:
    if old_name == new_name or not frappe.db.table_exists(CHILD_DOCTYPE):
        return
    for row in frappe.get_all(CHILD_DOCTYPE, filters={"class_name": old_name}, fields=["name"]):
        child = frappe.get_doc(CHILD_DOCTYPE, row.name)
        child.class_name = new_name
        try:
            record = json.loads(child.record_json or "{}")
            record["className"] = new_name
            child.record_json = json.dumps(record, ensure_ascii=False, default=str)
        except Exception:
            pass
        child.flags.ignore_permissions = True
        child.save(ignore_permissions=True)


@frappe.whitelist()
def list_classes(q: str | None = None, grade: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    _require_login()
    filters = []
    if grade:
        filters.append([DOCTYPE, "grade", "=", grade])
    if status:
        filters.append([DOCTYPE, "status", "=", status])
    rows = frappe.get_all(DOCTYPE, filters=filters, fields=["name"], order_by="sort_order asc, class_name asc")
    records = [_record_from_doc(frappe.get_doc(DOCTYPE, row.name)) for row in rows]
    keyword = str(q or "").strip()
    if keyword:
        records = [
            item for item in records
            if keyword in item["name"] or keyword in item["headTeacher"] or keyword in item["assistantTeacher"] or keyword in item["roomName"]
        ]
    return records


@frappe.whitelist()
def get_class(class_id: str) -> dict[str, Any] | None:
    _require_login()
    name = frappe.db.exists(DOCTYPE, {"class_id": class_id})
    return _record_from_doc(frappe.get_doc(DOCTYPE, name)) if name else None


@frappe.whitelist()
def get_class_by_name(class_name: str) -> dict[str, Any] | None:
    _require_login()
    name = frappe.db.exists(DOCTYPE, {"class_name": class_name})
    return _record_from_doc(frappe.get_doc(DOCTYPE, name)) if name else None


@frappe.whitelist()
def create_class(record: Any = None) -> dict[str, Any]:
    _require_login()
    record_dict = _as_dict(record)
    class_name = str(record_dict.get("name") or "").strip()
    if class_name and frappe.db.exists(DOCTYPE, {"class_name": class_name}):
        frappe.throw(_("Class name already exists."), frappe.DuplicateEntryError)
    return _upsert_class(record_dict)


@frappe.whitelist()
def update_class(class_id: str, record: Any = None) -> dict[str, Any]:
    _require_login()
    name = frappe.db.exists(DOCTYPE, {"class_id": class_id})
    if not name:
        frappe.throw(_("Class record not found."), frappe.DoesNotExistError)
    doc = frappe.get_doc(DOCTYPE, name)
    old_name = doc.class_name
    record_dict = _as_dict(record)
    new_name = str(record_dict.get("name") or old_name).strip()
    if new_name != old_name:
        duplicate = frappe.db.exists(DOCTYPE, {"class_name": new_name})
        if duplicate and duplicate != name:
            frappe.throw(_("Class name already exists."), frappe.DuplicateEntryError)
    record_dict["id"] = class_id
    updated = _upsert_class(record_dict)
    if new_name != old_name:
        _move_children_to_class(old_name, new_name)
        doc = frappe.get_doc(DOCTYPE, frappe.db.exists(DOCTYPE, {"class_id": class_id}))
        doc.child_count = _class_child_count(new_name)
        doc.updated_at = _now_text()
        _save_doc(doc)
        updated = _record_from_doc(doc)
    frappe.db.commit()
    return updated


@frappe.whitelist()
def delete_class(class_id: str) -> dict[str, Any]:
    _require_login()
    name = frappe.db.exists(DOCTYPE, {"class_id": class_id})
    if not name:
        frappe.throw(_("Class record not found."), frappe.DoesNotExistError)
    doc = frappe.get_doc(DOCTYPE, name)
    record = _record_from_doc(doc)
    if record["childCount"] > 0:
        frappe.throw(_("Class has children and cannot be deleted."))
    frappe.delete_doc(DOCTYPE, name, ignore_permissions=True)
    frappe.db.commit()
    return record


@frappe.whitelist()
def import_classes(classes: Any = None, records: Any = None, mode: str = "append") -> dict[str, Any]:
    _require_login()
    rows = _as_list(classes) or _as_list(records)
    if mode == "replace":
        for row in frappe.get_all(DOCTYPE, fields=["name"]):
            frappe.delete_doc(DOCTYPE, row.name, ignore_permissions=True)
    imported = 0
    for row in rows:
        _upsert_class(_as_dict(row))
        imported += 1
    frappe.db.commit()
    all_classes = list_classes()
    return {"imported": imported, "total": len(all_classes), "classes": all_classes}
