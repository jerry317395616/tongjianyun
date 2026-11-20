"""Native audit ORM compatibility smoke; all temporary audit rows roll back.

The business executor is mocked: this does not certify real business-write
behavior or cross-process crash recovery. No production feature gate is changed.
"""
import json
from unittest.mock import patch
import frappe

frappe.init(site="child.myyr.top", sites_path="/home/zyd/frappe/native-bench/sites")
try:
    frappe.connect(set_admin_as_user=False)
    frappe.set_user("Administrator")
    from tongjianyun import harness_administrator_approvals as approval
    production_gate = frappe.conf.get(approval.WRITE_ENABLE_KEY)
    assert production_gate in (None, 0)
    frappe.conf[approval.WRITE_ENABLE_KEY] = 1  # This process only.
    binding = "d" * 64
    approval._require(binding)
    with patch.object(frappe.db, "commit", lambda: None), patch.object(
        approval.business, "apply_preview", return_value={"doctype": "Student", "name": "SYNTHETIC-NOT-CREATED"}
    ) as execute:
        preview = approval.create_preview(binding, "create", "Student", changes={"first_name": "SYNTHETIC-NOT-CREATED"})
        first = approval.confirm_preview(binding, preview["preview_id"], preview["digest"])
        second = approval.confirm_preview(binding, preview["preview_id"], preview["digest"])
        assert first["state"] == "succeeded" and second["replayed"] is True
        assert execute.call_count == 1
        assert not frappe.db.exists(approval.AUDIT, preview["preview_id"])
    print(json.dumps({"native_audit_schema": "compatible", "orm_smoke": "passed",
        "replay_executor_calls": 1, "business_records_changed": 0, "audit_rows_retained": 0,
        "write_gate_enabled_in_production": False, "business_execution_mocked": True}))
finally:
    frappe.db.rollback()
    frappe.destroy()
