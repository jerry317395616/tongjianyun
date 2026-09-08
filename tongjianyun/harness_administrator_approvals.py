"""Internal confirmed-write adapter using existing Frappe audit documents.

No whitelisted Frappe method exposes this module. The transport must supply the
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


def _lock_preview(preview_id):
    """Lock the exact primary key before metadata loading can establish a snapshot."""
    business._name(preview_id)
    audit = frappe.qb.DocType(AUDIT)
    (frappe.qb.from_(audit).select(audit.name).where(audit.name == preview_id).for_update()).run()


def _receipt(tool_name):
    # Confirmation takes the preview row lock before its consistent snapshot.
    # Do not range-lock the non-indexed tool_name field: that locks unrelated
    # audit rows and can deadlock with the winning worker's result insertion.
    rows = frappe.db.get_values(AUDIT, {"user": "Administrator", "tool_name": tool_name},
        ["name", "result_summary"], as_dict=True, limit=2)
    if len(rows) > 1:
        raise RuntimeError("Duplicate approval receipts; operator review required")
    return json.loads(rows[0]["result_summary"]) if rows else None


def review_previews(session_hash):
    """Return at most ten previews belonging to this exact login and chat, with durable outcomes."""
    _require(session_hash)
    rows = frappe.get_list(AUDIT, filters={"user": "Administrator", "tool_name": PREVIEW_TOOL,
        "status": "成功", "request_summary": ["like", '%"session_hash":"' + session_hash + '"%']},
        fields=["name", "request_summary"], order_by="creation desc", limit_page_length=10)
    items = []
    for row in rows:
        envelope = json.loads(row["request_summary"])
        if not hmac.compare_digest(envelope["session_hash"], session_hash):
            raise PermissionError("Preview binding mismatch")
        if hashlib.sha256(envelope["payload"].encode()).hexdigest() != envelope["digest"]:
            raise PermissionError("Preview content mismatch")
        receipt = _receipt(RESULT_PREFIX + row["name"])
        claim = _receipt(CLAIM_PREFIX + row["name"])
        state = (receipt or {}).get("state") or ("outcome_unknown" if claim else
            "expired" if envelope["expires_at"] <= time.time() else "awaiting_confirmation")
        items.append({"preview_id": row["name"], "digest": envelope["digest"],
            "expires_at": envelope["expires_at"], "plan": json.loads(envelope["payload"]),
            "state": state, "receipt": receipt})
    return {"items": items}


def dispatch(value):
    """Validate the private transport protocol; callers cannot supply a site or account."""
    if not isinstance(value, dict) or set(value) != {"session_hash", "action", "arguments"}:
        raise ValueError("Invalid application request")
    business._administrator()
    action, args, binding = value["action"], value["arguments"], value["session_hash"]
    if not isinstance(args, dict):
        raise ValueError("Invalid application arguments")
    if action == "capabilities" and not args:
        enabled = frappe.conf.get(WRITE_ENABLE_KEY)
        return {"previews": type(enabled) in {int, bool} and enabled == 1}
    _require(binding)
    if action == "review" and not args:
        return review_previews(binding)
    if action == "confirm" and set(args) == {"preview_id", "digest"}:
        return confirm_preview(binding, args["preview_id"], args["digest"])
    if action == "preview" and set(args) == {"operation", "arguments"}:
        change = args["arguments"]
        if (not isinstance(change, dict) or "doctype" not in change
                or set(change) - {"doctype", "name", "changes"}):
            raise ValueError("Invalid preview fields")
        return create_preview(binding, args["operation"], **change)
    raise ValueError("Unsupported application action")


def confirm_preview(session_hash, preview_id, displayed_digest):
    """Execute one accepted confirmation at most once, with a durable audit result.

    A claim commits before execution. Replays return its final receipt, or an
    unknown outcome if interrupted; they NEVER rerun the business action. The
    business save and successful result audit commit in one transaction. Caller
    disconnect after acceptance does not imply rollback. External hook side
    effects require reconciliation on failure; this is not distributed atomicity.
    """
    _require(session_hash)
    # This function owns an otherwise empty worker transaction. Discard the
    # identity checks' old repeatable-read snapshot before taking the preview
    # lock. The first consistent receipt read then sees the preceding winner's
    # committed claim, without locking the entire audit table.
    frappe.db.rollback()
    try:
        _lock_preview(preview_id)
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
