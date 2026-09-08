"""Internal Administrator business executor; not a public or model-callable API.

The authenticated adapter must retain previews and obtain human confirmation
before calling apply_preview. No transport or automatic write tool is exposed.
"""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import math
import re

import frappe


SITE = "child.myyr.top"
ENABLE_KEY = "tongjianyun_harness_administrator_enabled"
OPERATIONS = frozenset({"create", "update", "submit", "cancel", "delete"})
PROTECTED_MODULES = frozenset({
    "Core", "Custom", "Desk", "Integrations", "Printing", "Email", "Website",
    "Workflow", "Automation", "Social", "I ONE AI", "Flow",
})
PROTECTED_TYPES = frozenset({
    "DocType", "DocField", "DocPerm", "Custom DocPerm", "Custom Field",
    "Property Setter", "Client Script", "Server Script", "Workflow",
    "Workflow State", "Workflow Action Master", "Workflow Action", "User",
    "Role", "Role Profile", "User Permission", "Module Def", "Module Profile",
    "Page", "Report", "Workspace", "Print Format", "Notification", "File",
    "Version", "Deleted Document", "Scheduled Job Type", "Data Import",
    "Data Export", "System Settings", "Integration Request",
})
SAFE_TYPES = frozenset({
    "Data", "Small Text", "Text", "Long Text", "Text Editor", "Select",
    "Link", "Dynamic Link", "Date", "Datetime", "Time", "Duration",
    "Int", "Float", "Currency", "Percent", "Check", "Rating", "Color",
})
SYSTEM_FIELDS = frozenset({"name", "owner", "creation", "modified", "modified_by", "docstatus"})
IMMUTABLE = SYSTEM_FIELDS | {"doctype", "flags", "parent", "parenttype", "parentfield", "idx"}
SENSITIVE = re.compile(r"password|secret|token|api_?key|credential|authorization|private_?key", re.I)
FIELD = re.compile(r"[A-Za-z][A-Za-z0-9_]*\Z")


@dataclass(frozen=True)
class Preview:
    """Server-retained preview; this object is never reconstructed from a request."""

    payload: str
    digest: str

    def as_dict(self):
        return json.loads(self.payload)


def _administrator():
    if frappe.local.site != SITE or frappe.session.user != "Administrator":
        raise PermissionError("Administrator business access required")
    enabled = frappe.conf.get(ENABLE_KEY)
    if type(enabled) not in {int, bool} or enabled != 1:
        raise PermissionError("Administrator business executor is not enabled")
    user = frappe.db.get_value("User", "Administrator", ["enabled", "user_type"], as_dict=True)
    if not user or not user.enabled or user.user_type != "System User":
        raise PermissionError("Administrator account is unavailable")


def _name(value):
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 140:
        raise ValueError("Expected an exact document name")
    if any(ord(char) < 32 for char in value):
        raise ValueError("Control characters are not allowed")
    return value


def _meta(doctype):
    _name(doctype)
    if doctype.casefold() in {value.casefold() for value in PROTECTED_TYPES} or doctype.startswith("__"):
        raise PermissionError("Configuration and document structure are frozen")
    meta = frappe.get_meta(doctype)
    if meta.module in PROTECTED_MODULES or meta.issingle or meta.istable or getattr(meta, "is_virtual", False):
        raise PermissionError("Only stored, non-single business documents are supported")
    return meta


def _field(meta, field, *, writing=False):
    if not isinstance(field, str) or not FIELD.fullmatch(field) or SENSITIVE.search(field):
        raise ValueError("Unsafe field")
    if not writing and field in SYSTEM_FIELDS:
        return
    df = meta.get_field(field)
    if field in IMMUTABLE or not df or df.fieldtype not in SAFE_TYPES:
        raise ValueError("Unsupported field; child tables require an application service")
    if writing and (df.read_only or df.get("fetch_from")):
        raise ValueError("Computed or read-only field cannot be written")


def _scalar(value):
    if value is None or type(value) in {bool, int}:
        return value
    if isinstance(value, (date, datetime, Decimal)):
        return str(value)
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, str) and len(value) <= 20000:
        return value
    raise ValueError("Expected a bounded scalar value")


def read_documents(doctype, *, fields=None, filters=None, name=None, start=0, limit=20):
    """Read explicit safe fields using the current Administrator's Frappe permissions."""
    _administrator()
    meta = _meta(doctype)
    fields = ["name"] if fields is None else fields
    if not isinstance(fields, list) or not 1 <= len(fields) <= 64:
        raise ValueError("Select between 1 and 64 fields")
    for field in fields:
        _field(meta, field)
    if type(start) is not int or not 0 <= start <= 100000 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid pagination")
    # Equality filters only: no SQL, expressions, cross-DocType joins or operators.
    filters = {} if filters is None else filters
    if not isinstance(filters, dict) or len(filters) > 20:
        raise ValueError("Expected at most 20 equality filters")
    clean_filters = {}
    for field, value in filters.items():
        _field(meta, field)
        clean_filters[field] = _scalar(value)
    if name is not None:
        clean_filters["name"] = _name(name)
    rows = frappe.get_list(doctype, fields=fields, filters=clean_filters,
                           limit_start=start, limit_page_length=limit, order_by="name asc")
    return [{field: _scalar(row.get(field)) for field in fields} for row in rows]


def preview_change(operation, doctype, *, name=None, changes=None):
    """Preview one record without running mutating hooks or saving business data."""
    _administrator()
    if operation not in OPERATIONS:
        raise ValueError("Unsupported business operation")
    meta = _meta(doctype)
    changes = {} if changes is None else changes
    if not isinstance(changes, dict) or len(changes) > 32:
        raise ValueError("Expected at most 32 changed fields")
    if operation == "update" and not changes:
        raise ValueError("An update needs changes")
    if operation not in {"create", "update"} and changes:
        raise ValueError("This operation does not accept field changes")
    clean = {}
    for field, value in changes.items():
        _field(meta, field, writing=True)
        clean[field] = _scalar(value)
    if operation == "create":
        if name is not None:
            raise ValueError("New document names are assigned by Frappe")
        if not frappe.has_permission(doctype, ptype="create"):
            raise PermissionError("Create permission required")
        before, modified = {}, None
    else:
        _name(name)
        doc = frappe.get_doc(doctype, name)
        doc.check_permission({"update": "write"}.get(operation, operation))
        before = {field: _scalar(doc.get(field)) for field in clean}
        before["docstatus"] = int(doc.docstatus)
        modified = str(doc.modified)
    payload = json.dumps({"site": SITE, "user": "Administrator", "operation": operation,
                          "doctype": doctype, "name": name, "count": 1, "changes": clean,
                          "before": before, "modified": modified}, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False)
    return Preview(payload, hashlib.sha256(payload.encode()).hexdigest())


def apply_preview(preview):
    """Apply a trusted, human-approved server-retained preview in the caller transaction.

    The adapter must enforce expiry, one-use confirmation, session ownership and
    durable audit. This internal function is not whitelisted and does not commit.
    Failure must roll back the caller's transaction. No ignore/force flags exist.
    """
    _administrator()
    if not isinstance(preview, Preview) or hashlib.sha256(preview.payload.encode()).hexdigest() != preview.digest:
        raise ValueError("Invalid server preview")
    plan = preview.as_dict()
    if plan["site"] != frappe.local.site or plan["user"] != frappe.session.user:
        raise PermissionError("Preview identity changed")
    operation, doctype, name = plan["operation"], plan["doctype"], plan["name"]
    # The row lock spans revalidation, the ORM action and the adapter's commit.
    doc = None if operation == "create" else frappe.get_doc(doctype, name, for_update=True)
    current = preview_change(operation, doctype, name=name, changes=plan["changes"])
    if current.payload != preview.payload:
        raise ValueError("Document or permissions changed; request a new preview")
    if operation == "create":
        doc = frappe.get_doc({"doctype": doctype, **plan["changes"]})
        doc.insert()
    elif operation == "update":
        for field, value in plan["changes"].items():
            doc.set(field, value)
        doc.save(ignore_version=False)
    elif operation == "submit":
        doc.submit()
    elif operation == "cancel":
        doc.cancel()
    elif operation == "delete":
        doc.delete()
    else:
        raise ValueError("Unsupported operation")
    if operation == "delete":
        if frappe.db.exists(doctype, name):
            raise RuntimeError("Delete verification failed")
        after = None
    else:
        doc.reload()
        after = {field: _scalar(doc.get(field)) for field in plan["changes"]}
        after["docstatus"] = int(doc.docstatus)
    return {"operation": operation, "doctype": doctype, "name": doc.name,
            "count": 1, "after": after, "preview_digest": preview.digest,
            "transaction": "pending_adapter_commit"}
