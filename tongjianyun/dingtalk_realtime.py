"""Read-only, permission-checked information for the native check-in list.

No employee identifiers, source event bodies, filesystem paths or exception text
are included in the service status response. Check-in enrichment always starts
with Frappe's permission-aware list query, including User Permission conditions.
"""
from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import frappe

HEALTH_PATH = Path("/var/lib/dingtalk-attendance-stream/health.json")
MAX_HEALTH_BYTES = 65536
HEALTH_STALE_SECONDS = 90
STATUS_ROLES = frozenset(("System Manager", "HR Manager", "HR User"))
MAX_CONTEXT_NAMES = 100


def _require_checkin_read():
    if frappe.session.user == "Guest":
        frappe.throw("请先登录。", frappe.PermissionError)
    frappe.has_permission("Employee Checkin", ptype="read", throw=True)


def _count(value):
    if isinstance(value, bool):
        return 0
    try:
        return max(0, min(int(value), 1000000000))
    except (TypeError, ValueError, OverflowError):
        return 0


def _timestamp(value):
    """Allow only genuine timestamps, never arbitrary cached/error strings."""
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and math.isfinite(value):
            date = datetime.fromtimestamp(value, timezone.utc)
        elif isinstance(value, datetime):
            date = value
        elif isinstance(value, str) and len(value) <= 48:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            return None
        # Backend runtime timestamps without an offset use the site's timezone.
        if date.tzinfo is None:
            from zoneinfo import ZoneInfo

            date = date.replace(tzinfo=ZoneInfo(frappe.utils.get_system_timezone()))
        return date.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def _read_health():
    try:
        with HEALTH_PATH.open("rb") as handle:
            payload = handle.read(MAX_HEALTH_BYTES + 1)
        if len(payload) > MAX_HEALTH_BYTES:
            return {}
        health = json.loads(payload)
        return health if isinstance(health, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


@frappe.whitelist()
def get_sync_status():
    """Return safe service aggregates only to HR-authorized readers."""
    _require_checkin_read()
    if not STATUS_ROLES.intersection(frappe.get_roles()):
        frappe.throw("仅人事管理员可以查看同步状态。", frappe.PermissionError)

    health = _read_health()
    updated_at = _timestamp(health.get("updated_at"))
    age = None
    if updated_at:
        age = time.time() - datetime.fromisoformat(updated_at).timestamp()
    fresh = age is not None and -30 <= age <= HEALTH_STALE_SECONDS
    control = health.get("import_control")
    control = control if isinstance(control, dict) else {}
    paused = control.get("paused") is True
    invalid_control = control.get("valid") is False
    connected = fresh and health.get("connected") is True

    runtime = frappe.cache.get_value(f"dingtalk-attendance-runtime:{frappe.local.site}")
    runtime = runtime if isinstance(runtime, dict) else {}
    result = {
        "connected": connected,
        "health_fresh": fresh,
        "import_paused": paused,
        "import_control_valid": not invalid_control,
        "state": (
            "unavailable" if not fresh else "paused" if paused or invalid_control
            else "connected" if connected else "reconnecting"
        ),
        "pending": _count(health.get("pending")),
        "pending_employee_days": _count(health.get("pending_employee_days")),
        "failed_pending": _count(health.get("failed_pending")),
        "attention_pending": _count(health.get("attention_pending")),
        "oldest_pending_received_at": _timestamp(health.get("oldest_pending_received_at")),
        "last_event_received": _timestamp(health.get("last_event_received")),
        "last_import_success": _timestamp(health.get("last_import_success")),
        "last_import_attempt": _timestamp(health.get("last_import_attempt")),
        "last_import_failure": _timestamp(health.get("last_import_failure")),
        "health_updated_at": updated_at,
        "business_timezone": "Asia/Shanghai",
        "reconcile_failed": bool(runtime.get("last_reconcile_error")),
        "settlement_failed": bool(runtime.get("last_settlement_error")),
        "last_reconcile_created": _count(runtime.get("last_reconcile_created")),
        # This is the latest run's findings, not a durable unresolved queue.
        "last_reconcile_review_count": _count(runtime.get("last_reconcile_review_count")),
        "last_settlement_deferred_count": _count(runtime.get("last_settlement_deferred_count")),
    }
    for key in ("last_reconcile_success", "last_settlement_success"):
        result[key] = _timestamp(runtime.get(key))
    return result


@frappe.whitelist()
def get_checkin_context(names):
    """Enrich only authorized visible records; never bypass row permissions."""
    _require_checkin_read()
    if isinstance(names, str):
        try:
            names = json.loads(names)
        except ValueError:
            frappe.throw("签到记录列表格式不正确。", frappe.ValidationError)
    if not isinstance(names, list) or len(names) > MAX_CONTEXT_NAMES:
        frappe.throw("每次最多查询 100 条签到记录。", frappe.ValidationError)
    if any(not isinstance(name, str) or not name or len(name) > 140 for name in names):
        frappe.throw("签到记录编号不正确。", frappe.ValidationError)
    names = list(dict.fromkeys(names))
    if not names:
        return {}

    checkins = frappe.get_list(
        "Employee Checkin", filters={"name": ["in", names]},
        fields=["name", "employee", "shift"], limit_page_length=MAX_CONTEXT_NAMES,
    )
    departments = {}
    employee_names = list({row.employee for row in checkins if row.employee})
    if employee_names and frappe.has_permission("Employee", ptype="read"):
        # A user's right to see a check-in does not grant access to its Employee.
        employees = frappe.get_list(
            "Employee", filters={"name": ["in", employee_names]},
            fields=["name", "department"], limit_page_length=MAX_CONTEXT_NAMES,
        )
        departments = {row.name: row.department for row in employees}
    return {
        row.name: {"department": departments.get(row.employee), "shift": row.shift}
        for row in checkins
    }
