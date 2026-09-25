"""New-connection, read-only evidence after the real browser activates/saves QA v2.

This helper never activates a proposal or inserts/saves business documents. Run
only after the browser has entered the documented 2.5*3.8 and 10*1.25 test rows.
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal

import serve_isolated_browser as qa


def main():
    qa.config_guard()
    fixture = qa.blueprint_fixture()
    frappe = qa.connect()
    checks = []
    result = {"site": qa.SITE, "doctype": fixture["doctype"], "proposal_id": fixture["proposal_id"],
              "task_id": fixture["task_id"], "actor": fixture["manager"],
              "new_connection": True, "read_only_transaction": True, "production_writes": False,
              "business_writes": False, "codex_executed_by_this_helper": False,
              "scope": "Only activation and native draft save; browser workflow approval is not covered.",
              "currency_evidence_limit": "The isolated site has no configured global currency and the native browser displayed the fallback rupee symbol. This test verifies numeric calculations and two-decimal fields, not currency correctness."}

    def check(label, condition):
        checks.append({"check": label, "passed": bool(condition)})

    def number(value):
        return Decimal(str(value))

    try:
        frappe.db.sql("START TRANSACTION READ ONLY")
        frappe.set_user(fixture["manager"])
        from tongjianyun import business_blueprints as bp
        from tongjianyun import business_blueprints_v2 as v2
        from tongjianyun.meal_chat import TaskStore
        spec = bp._load(fixture["proposal_id"])
        check("proposal_remains_owned_private_and_exact", bp.revision(spec) == fixture["revision"])
        check("parent_children_and_review_workflow_exactly_active", bp._state(spec) == "active")
        preview = bp.preview(fixture["proposal_id"])
        check("fresh_preview_reports_active_not_proposed", preview["summary"]["state"] == "active")
        check("active_preview_exposes_create_and_list_views", {row["selection"]["view"] for row in preview["actions"]}
              == {"frappe_new", "frappe_doctype"})
        task = TaskStore().read(fixture["task_id"])
        check("synthetic_navigation_task_completed_under_manager", task.get("status") == "completed"
              and task.get("owner") == fixture["manager"] and not task.get("job_id"))
        meta = frappe.get_meta(fixture["doctype"], cached=False)
        check("blueprint_doctype_owned_by_browser_manager", meta.owner == fixture["manager"])
        check("change_history_is_enabled", bool(meta.track_changes))
        check("readonly_total_and_row_calculations_installed", meta.get_field("estimated_total").read_only == 1
              and frappe.get_meta(fixture["children"]["estimate_lines"], cached=False).get_field("line_amount").read_only == 1)
        check("only_original_system_manager_permissions", len(meta.permissions) == 1
              and meta.permissions[0].role == "System Manager" and not meta.permissions[0].delete
              and not meta.permissions[0].share)
        records = frappe.get_list(fixture["doctype"], fields=["name", "owner", "modified_by", "docstatus", "title"], limit_page_length=0)
        check("exactly_one_real_browser_record", len(records) == 1)
        if len(records) == 1:
            doc = frappe.get_doc(fixture["doctype"], records[0].name)
            doc.check_permission("read")
            check("record_actor_is_browser_manager", doc.owner == fixture["manager"] and doc.modified_by == fixture["manager"])
            check("record_stays_draft_before_review", doc.docstatus == 0 and doc.workflow_state == "扩展·草稿")
            check("browser_entered_document_title_persisted", doc.title == "浏览器合成活动估算")
            rows = doc.estimate_lines
            check("exact_two_persisted_children", len(rows) == 2)
            check("child_identity_and_parent_binding_preserved", all(
                row.doctype == fixture["children"]["estimate_lines"] and row.parent == doc.name
                and row.parenttype == doc.doctype and row.parentfield == "estimate_lines"
                and row.name and row.docstatus == 0 for row in rows))
            check("browser_entered_quantity_and_price_persisted", [
                (number(row.quantity), number(row.unit_price)) for row in rows]
                == [(Decimal("2.5"), Decimal("3.8")), (Decimal("10"), Decimal("1.25"))])
            check("server_computed_row_amounts_persisted", [number(row.line_amount) for row in rows]
                  == [Decimal("9.5"), Decimal("12.5")])
            check("server_computed_parent_total_persisted", number(doc.estimated_total) == Decimal("22"))
            # Server runtime guard validates immutable schema + workflow. Do not
            # call validate/save here; the persisted result must stand on its own.
            check("runtime_manifest_is_still_exact", bp.revision(v2._runtime_spec(doc)) == fixture["revision"])
            result["record"] = {"name": doc.name, "title": doc.title, "owner": doc.owner,
                "modified_by": doc.modified_by, "docstatus": doc.docstatus, "workflow_state": doc.workflow_state,
                "estimated_total": doc.estimated_total, "creation": doc.creation, "modified": doc.modified,
                "rows": [{key: row.get(key) for key in ("name", "doctype", "parent", "parenttype", "parentfield",
                          "idx", "item_label", "quantity", "unit_price", "line_amount")} for row in rows]}
        result["preview"] = preview["summary"]
    finally:
        frappe.db.rollback()
        frappe.destroy()
    result.update(checks=checks, passed=sum(row["passed"] for row in checks), total=len(checks),
                  status="passed" if checks and all(row["passed"] for row in checks) else "failed")
    output = qa.ROOT / ("browser-blueprint-readback-" + uuid.uuid4().hex[:10] + ".json")
    qa.private_json(output, json.loads(json.dumps(result, ensure_ascii=False, default=str)))
    print(json.dumps({"evidence_file": str(output), "status": result["status"], "passed": result["passed"],
          "total": result["total"], "checks": checks, "production_writes": False, "business_writes": False}, ensure_ascii=False), flush=True)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
