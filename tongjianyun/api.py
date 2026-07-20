from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _

DOCTYPE = "Tongjianyun Child"
DEFAULT_STATUS = "\u5728\u56ed"
DEFAULT_VACCINE_STATUS = "\u5f85\u6838\u9a8c"


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


def _json_text(value: Any) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def _require_login() -> None:
    if frappe.session.user == "Guest":
        frappe.throw(_("Not logged in."), frappe.AuthenticationError)


def _record_from_doc(doc) -> dict[str, Any]:
    try:
        record = json.loads(doc.record_json or "{}")
    except Exception:
        record = {}
    record.update({
        "id": doc.child_id,
        "name": doc.child_name,
        "gender": doc.gender,
        "age": doc.age or "",
        "birthday": str(doc.birthday or ""),
        "className": doc.class_name,
        "status": doc.status or DEFAULT_STATUS,
        "guardian": doc.guardian or "",
        "guardianMobile": doc.guardian_mobile or "",
        "allergyTags": json.loads(doc.allergy_tags or "[]"),
        "healthTags": json.loads(doc.health_tags or "[]"),
        "vaccineStatus": doc.vaccine_status or DEFAULT_VACCINE_STATUS,
        "archiveRate": int(doc.archive_rate or 0),
        "lastCheckup": str(doc.last_checkup or ""),
        "heightCm": doc.height_cm,
        "weightKg": doc.weight_kg,
        "measurementDate": str(doc.measurement_date or ""),
        "bmi": doc.bmi,
        "bmiPercentile": doc.bmi_percentile,
        "growthNote": doc.growth_note or "",
        "source": doc.source or "",
        "recentEvent": doc.recent_event or "",
        "risk": doc.risk or "normal",
        "sensitiveFields": json.loads(doc.sensitive_fields or "[]"),
    })
    return {key: value for key, value in record.items() if value is not None}


def _upsert_child(record: dict[str, Any]) -> dict[str, Any]:
    child_id = str(record.get("id") or "").strip()
    if not child_id:
        frappe.throw(_("Child id is required."))
    name = str(record.get("name") or "").strip()
    class_name = str(record.get("className") or "").strip()
    gender = str(record.get("gender") or "").strip()
    if not name or not class_name or not gender:
        frappe.throw(_("Child name, gender and class are required."))

    existing = frappe.db.exists(DOCTYPE, {"child_id": child_id})
    doc = frappe.get_doc(DOCTYPE, existing) if existing else frappe.new_doc(DOCTYPE)
    doc.child_id = child_id
    doc.child_name = name
    doc.gender = gender
    doc.age = record.get("age") or ""
    doc.birthday = record.get("birthday") or None
    doc.class_name = class_name
    doc.status = record.get("status") or DEFAULT_STATUS
    doc.guardian = record.get("guardian") or ""
    doc.guardian_mobile = record.get("guardianMobile") or ""
    doc.allergy_tags = _json_text(record.get("allergyTags"))
    doc.health_tags = _json_text(record.get("healthTags"))
    doc.vaccine_status = record.get("vaccineStatus") or DEFAULT_VACCINE_STATUS
    doc.archive_rate = int(record.get("archiveRate") or 0)
    doc.last_checkup = record.get("lastCheckup") or None
    doc.height_cm = record.get("heightCm")
    doc.weight_kg = record.get("weightKg")
    doc.measurement_date = record.get("measurementDate") or None
    doc.bmi = record.get("bmi")
    doc.bmi_percentile = record.get("bmiPercentile")
    doc.growth_note = record.get("growthNote") or ""
    doc.source = record.get("source") or ""
    doc.recent_event = record.get("recentEvent") or ""
    doc.risk = record.get("risk") or "normal"
    doc.sensitive_fields = _json_text(record.get("sensitiveFields"))
    doc.record_json = json.dumps(record, ensure_ascii=False, default=str)
    doc.flags.ignore_permissions = True
    if existing:
        doc.save(ignore_permissions=True)
    else:
        doc.insert(ignore_permissions=True)
    return _record_from_doc(doc)


@frappe.whitelist()
def list_children(className: str | None = None, risk: str | None = None, age: str | None = None) -> list[dict[str, Any]]:
    _require_login()
    filters = []
    if className:
        filters.append([DOCTYPE, "class_name", "=", className])
    if risk:
        filters.append([DOCTYPE, "risk", "=", risk])
    docs = frappe.get_all(DOCTYPE, filters=filters, fields=["name"], order_by="class_name asc, child_name asc")
    rows = [_record_from_doc(frappe.get_doc(DOCTYPE, row.name)) for row in docs]
    if age:
        rows = [row for row in rows if age in str(row.get("age") or "")]
    return rows


@frappe.whitelist()
def get_child(child_id: str) -> dict[str, Any] | None:
    _require_login()
    name = frappe.db.exists(DOCTYPE, {"child_id": child_id})
    return _record_from_doc(frappe.get_doc(DOCTYPE, name)) if name else None


@frappe.whitelist()
def create_child(record: Any = None) -> dict[str, Any]:
    _require_login()
    record_dict = _as_dict(record)
    child_id = str(record_dict.get("id") or "").strip()
    if child_id and frappe.db.exists(DOCTYPE, {"child_id": child_id}):
        frappe.throw(_("Child id already exists."), frappe.DuplicateEntryError)
    return _upsert_child(record_dict)


@frappe.whitelist()
def update_child(child_id: str, record: Any = None) -> dict[str, Any]:
    _require_login()
    if not frappe.db.exists(DOCTYPE, {"child_id": child_id}):
        frappe.throw(_("Child record not found."), frappe.DoesNotExistError)
    record_dict = _as_dict(record)
    record_dict["id"] = child_id
    return _upsert_child(record_dict)


@frappe.whitelist()
def delete_child(child_id: str) -> dict[str, Any]:
    _require_login()
    name = frappe.db.exists(DOCTYPE, {"child_id": child_id})
    if not name:
        frappe.throw(_("Child record not found."), frappe.DoesNotExistError)
    doc = frappe.get_doc(DOCTYPE, name)
    record = _record_from_doc(doc)
    frappe.delete_doc(DOCTYPE, name, ignore_permissions=True)
    return record


@frappe.whitelist()
def import_children(children: Any = None, records: Any = None, mode: str = "append") -> dict[str, Any]:
    _require_login()
    rows = _as_list(children) or _as_list(records)
    if mode == "replace":
        for row in frappe.get_all(DOCTYPE, fields=["name"]):
            frappe.delete_doc(DOCTYPE, row.name, ignore_permissions=True)
    imported = 0
    for row in rows:
        _upsert_child(_as_dict(row))
        imported += 1
    frappe.db.commit()
    all_children = list_children()
    return {"imported": imported, "total": len(all_children), "children": all_children}
