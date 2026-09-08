"""Internal confirmed-write adapter using existing Frappe audit documents.

No HTTP method or AI tool exposes this module. The transport must supply the
verified session hash and accept confirmation separately from model execution.
Each function owns an otherwise empty database transaction in a dedicated worker.
"""
import hashlib
import hmac
import json
import re
import time

import frappe
from tongjianyun import harness_administrator as business

AUDIT = "I-ONE MCP Audit Log"
WRITE_ENABLE_KEY = "tongjianyun_harness_administrator_writes_enabled"
PREVIEW_TOOL = "tongjianyun.admin.preview.v1"
CLAIM_PREFIX = "tongjianyun.admin.claim:"
RESULT_PREFIX = "tongjianyun.admin.result:"
HASH = re.compile(r"[a-f0-9]{64}\Z")
MAX_JSON_BYTES = 32768
TTL_SECONDS = 600
AUDIT_FIELDS = {
    "user": "Link", "tool_name": "Data", "operation": "Select", "status": "Select",
    "target_doctype": "Data", "target_name": "Data", "request_summary": "Code",
    "result_summary": "Code", "error_message": "Small Text",
}


def _json(value):
    result = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(result.encode()) > MAX_JSON_BYTES:
        raise ValueError("Approval details exceed the size limit")
    return result


def _require(session_hash):
    business._administrator()
    enabled = frappe.conf.get(WRITE_ENABLE_KEY)
    if type(enabled) not in {int, bool} or enabled != 1:
        raise PermissionError("Administrator writes are not enabled")
    if not isinstance(session_hash, str) or not HASH.fullmatch(session_hash):
        raise PermissionError("Verified session binding required")
    meta = frappe.get_meta(AUDIT)
    for name, fieldtype in AUDIT_FIELDS.items():
        field = meta.get_field(name)
        if not field or field.fieldtype != fieldtype:
            raise RuntimeError("Audit schema unavailable; no schema changes are permitted")


def _log(tool_name, operation, status, plan, request, result):
    # Unlike the upstream best-effort logger, a failed insert must abort the
    # business transaction. This uses the existing document's normal ORM path.
    return frappe.get_doc({
        "doctype": AUDIT, "user": "Administrator", "tool_name": tool_name,
        "operation": operation, "status": status, "target_doctype": plan["doctype"],
        "target_name": plan.get("name") or "", "request_summary": _json(request),
        "result_summary": _json(result),
    }).insert()


def create_preview(session_hash, operation, doctype, *, name=None, changes=None):
    """Commit a bounded, session-bound preview audit; do not change target records."""
    _require(session_hash)
    preview = business.preview_change(operation, doctype, name=name, changes=changes)
    plan = preview.as_dict()
    envelope = {"version": 1, "session_hash": session_hash, "expires_at": time.time() + TTL_SECONDS,
                "payload": preview.payload, "digest": preview.digest}
    try:
        audit = _log(PREVIEW_TOOL, "读取", "成功", plan, envelope, {"state": "awaiting_confirmation"})
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise
    return {"preview_id": audit.name, "digest": preview.digest,
            "expires_at": envelope["expires_at"], "plan": plan, "state": "awaiting_confirmation"}


def _load(preview_id, session_hash, displayed_digest):
    business._name(preview_id)
    if not isinstance(displayed_digest, str) or not HASH.fullmatch(displayed_digest):
        raise PermissionError("Displayed preview digest required")
    doc = frappe.get_doc(AUDIT, preview_id, for_update=True)
    doc.check_permission("read")
    if doc.user != "Administrator" or doc.tool_name != PREVIEW_TOOL or doc.status != "成功":
        raise PermissionError("Not an Administrator preview")
    envelope = json.loads(doc.request_summary)
    if (set(envelope) != {"version", "session_hash", "expires_at", "payload", "digest"}
            or envelope["version"] != 1 or not isinstance(envelope["session_hash"], str)
            or not hmac.compare_digest(envelope["session_hash"], session_hash)
            or not hmac.compare_digest(envelope["digest"], displayed_digest)
            or hashlib.sha256(envelope["payload"].encode()).hexdigest() != displayed_digest):
        raise PermissionError("Preview identity or content mismatch")
    return envelope


def _receipt(tool_name):
    rows = frappe.get_list(AUDIT, filters={"user": "Administrator", "tool_name": tool_name},
                           fields=["name", "result_summary"], limit_page_length=2)
    if len(rows) > 1:
        raise RuntimeError("Duplicate approval receipts; operator review required")
    return json.loads(rows[0]["result_summary"]) if rows else None


def confirm_preview(session_hash, preview_id, displayed_digest):
    """Execute one accepted confirmation at most once, with a durable audit result.

    A claim commits before execution. Replays return its final receipt, or an
    unknown outcome if interrupted; they NEVER rerun the business action. The
    business save and successful result audit commit in one transaction. Caller
    disconnect after acceptance does not imply rollback. External hook side
    effects require reconciliation on failure; this is not distributed atomicity.
    """
    _require(session_hash)
    try:
        envelope = _load(preview_id, session_hash, displayed_digest)
        previous = _receipt(CLAIM_PREFIX + preview_id)
        if previous is not None:
            result = _receipt(RESULT_PREFIX + preview_id)
            frappe.db.rollback()  # Release the preview lock; this path never writes.
            return {**(result or {"state": "outcome_unknown", "preview_id": preview_id}), "replayed": True}
        if envelope["expires_at"] <= time.time():
            raise ValueError("Preview expired; create a new preview")
        preview = business.Preview(envelope["payload"], envelope["digest"])
        plan = preview.as_dict()
        claim = {"preview_id": preview_id, "state": "accepted", "business_executed": False}
        # Success here means the confirmation was recorded, NOT business success.
        _log(CLAIM_PREFIX + preview_id, "写入", "成功", plan, {"digest": displayed_digest}, claim)
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        raise

    try:
        execution = business.apply_preview(preview)
        execution.pop("transaction", None)
        result = {"state": "succeeded", "preview_id": preview_id, "result": execution}
        _log(RESULT_PREFIX + preview_id, "写入", "成功", plan,
             {"digest": displayed_digest, "confirmed_by": "Administrator"}, result)
    except Exception as error:
        frappe.db.rollback()
        # Do not store raw exception messages: validators may interpolate private
        # values. A failed action is terminal for this confirmation, never retried.
        result = {"state": "failed", "preview_id": preview_id, "error_type": type(error).__name__,
                  "review_required": True}
        try:
            _log(RESULT_PREFIX + preview_id, "写入", "失败", plan, {"digest": displayed_digest}, result)
            frappe.db.commit()
        except Exception:
            frappe.db.rollback()
            return {"state": "outcome_unknown", "preview_id": preview_id, "replayed": False}
        return {**result, "replayed": False}
    # Commit acknowledgement failures are uncertain, not confirmed business
    # failures. The durable claim prevents another execution after reconnect.
    try:
        frappe.db.commit()
    except Exception:
        frappe.db.rollback()
        return {"state": "outcome_unknown", "preview_id": preview_id, "replayed": False}
    return {**result, "replayed": False}
