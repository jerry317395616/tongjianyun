"""Adversarial v2 blueprint ORM acceptance; fixed synthetic QA site ONLY."""
import copy
import base64
import json
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

SITE = "unified-business-acceptance.localhost"
ROOT = Path("/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925").resolve()
sites = Path(os.environ["UNIFIED_BUSINESS_SITES"]).resolve(strict=True)
source = Path(os.environ["UNIFIED_BUSINESS_SOURCE"]).resolve(strict=True)
assert sites == ROOT / "sites"
config = {**json.loads((sites / "common_site_config.json").read_text()),
          **json.loads((sites / SITE / "site_config.json").read_text())}


def guard(conf):
    assert conf.get("unified_business_acceptance") == 1
    assert conf.get("db_host") == "127.0.0.1" and int(conf.get("db_port", 0)) == 23316
    assert conf.get("db_name") == "tgy_blueprint_qa"
    assert conf.get("db_user", conf.get("db_name")) == "tgy_blueprint_qa"
    assert not conf.get("db_socket") and not conf.get("developer_mode")
    assert conf.get("pause_scheduler") == 1 and conf.get("disable_scheduler") == 1
    for key in ("redis_cache", "redis_queue", "redis_socketio"):
        endpoint = urlparse(conf.get(key) or "")
        assert endpoint.scheme == "redis" and endpoint.hostname == "127.0.0.1" and endpoint.port == 23379


guard(config)
for key in list(os.environ):
    if key.startswith(("FRAPPE_DB_", "FRAPPE_REDIS_")):
        os.environ.pop(key)
os.environ["FRAPPE_BENCH_ROOT"] = str(ROOT)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
sys.path.insert(0, str(source))
os.chdir(sites)

import frappe
from tongjianyun import business_blueprints as bp, business_blueprints_v2 as v2
from tongjianyun.tests.test_business_blueprints_v2 import SPEC
from tongjianyun.meal_view_tool import use_site_os_identity

assert Path(v2.__file__).resolve().is_relative_to(source)
use_site_os_identity(sites / SITE)
os.umask(0o077)
run_id = uuid.uuid4().hex[:10]
checks, findings, retained, observations = [], [], [], []


def connect():
    frappe.init(site=SITE, sites_path=str(sites))
    guard(frappe.conf)
    frappe.connect()
    frappe.set_user("Administrator")


def check(label, condition):
    if condition:
        checks.append(label)
        print(json.dumps({"passed": label}), flush=True)
    else:
        findings.append({"test": label, "problem": "assertion_failed"})
        print(json.dumps({"failed": label}), flush=True)


def rejected(label, operation, exception=frappe.ValidationError, savepoint=True):
    point = "boundary_" + uuid.uuid4().hex[:8] if savepoint else None
    if point:
        frappe.db.savepoint(point)
    try:
        operation()
    except exception:
        check(label, True)
    except Exception as exc:
        findings.append({"test": label, "problem": "wrong_exception", "exception_type": type(exc).__name__})
        print(json.dumps(findings[-1]), flush=True)
    else:
        findings.append({"test": label, "problem": "unexpectedly_accepted"})
        print(json.dumps(findings[-1]), flush=True)
    finally:
        if point:
            frappe.db.rollback(save_point=point)


connect()
try:
    frappe.clear_cache()
    restore_run = os.environ.get("UNIFIED_BOUNDARY_RESTORE_RUN")
    if restore_run:
        assert re.fullmatch(r"[0-9a-f]{10}", restore_run)
        restore_key = "bound_float_" + restore_run
        restore_type = bp.PREFIX + restore_key
        restore_doc = frappe.get_doc("DocType", restore_type)
        restore_spec = bp.validate_spec(json.loads(base64.urlsafe_b64decode(restore_doc.description.split("\n", 1)[1])))
        assert restore_spec["key"] == restore_key and bp.doctype_name(restore_spec) == restore_type
        restore_doc.set("fields", copy.deepcopy(v2.definitions(restore_spec)[-1]["fields"]))
        restore_doc.save()
        frappe.clear_cache(doctype=restore_type)
        assert bp._state(restore_spec) == "active", "Owned test metadata restoration failed"
        frappe.db.commit()
        print(json.dumps({"restored_owned_fixture": restore_type}))
        raise SystemExit(0)
    assert "tongjianyun.business_blueprints_v2.validate_document" in frappe.get_hooks("doc_events")["*"]["before_validate"]
    variants = []
    for key, integer, workflow in (("bound_float_", False, True), ("bound_int_", True, False)):
        raw = copy.deepcopy(SPEC)
        raw["key"] = key + run_id
        if integer:
            raw["tables"][0]["fields"][1]["fieldtype"] = "Int"
        if not workflow:
            raw["workflow"] = None
        spec = bp.validate_spec(raw)
        proposal = bp.propose(spec)
        bp.activate(proposal["proposal_id"], proposal["revision"])
        assert bp._state(spec) == "active"
        variants.append((spec, proposal))
        retained.append({"doctype": bp.doctype_name(spec), "proposal": proposal["proposal_id"], "documents": []})
    (float_spec, float_proposal), (int_spec, int_proposal) = variants
    dt, integer_dt = bp.doctype_name(float_spec), bp.doctype_name(int_spec)

    def new_record(doctype=dt, quantity=2, price=3):
        return frappe.get_doc({"doctype": doctype, "title": "Synthetic boundary " + run_id,
            "estimated_total": 999, "estimate_lines": [
                {"item_label": "Synthetic A", "quantity": quantity, "unit_price": price, "line_amount": 999},
                {"item_label": "Synthetic B", "quantity": 1, "unit_price": 2, "line_amount": 999}]})

    a, b, ints = new_record().insert(), new_record().insert(), new_record(integer_dt).insert()
    retained[0]["documents"] = [a.name, b.name]
    retained[1]["documents"] = [ints.name]
    frappe.db.commit()
    check("native_amounts_recomputed_on_insert", a.estimated_total == 8 and a.estimate_lines[0].line_amount == 6)
    check("table_only_v2_without_workflow_is_active", bp._state(int_spec) == "active"
          and not frappe.get_meta(integer_dt).is_submittable
          and not frappe.db.exists("Workflow", {"document_type": integer_dt}))

    def modify_a(mutator):
        doc = frappe.get_doc(dt, a.name)
        mutator(doc)
        return doc.save()

    def cross_document(doc):
        doc.estimate_lines[0].name = b.estimate_lines[0].name

    rejected("child_from_other_document_cannot_be_adopted", lambda: modify_a(cross_document))
    rejected("duplicate_child_name_rejected", lambda: modify_a(
        lambda doc: setattr(doc.estimate_lines[1], "name", doc.estimate_lines[0].name)))
    def nonexistent_child_name():
        modify_a(lambda doc: setattr(doc.estimate_lines[0], "name", "forged-" + run_id))
        reread = frappe.get_doc(dt, a.name)
        observations.append({"test": "nonexistent_persisted_child_name_cannot_drop_saved_row",
            "persisted_child_count": len(reread.estimate_lines), "persisted_total": reread.estimated_total,
            "persisted_child_amount_sum": sum(row.line_amount for row in reread.estimate_lines)})

    rejected("nonexistent_persisted_child_name_cannot_drop_saved_row", nonexistent_child_name)
    rejected("forged_child_doctype_rejected", lambda: modify_a(
        lambda doc: setattr(doc.estimate_lines[0], "doctype", "User")))
    childtype = v2.row_name(float_spec, float_spec["tables"][0])
    rejected("direct_child_document_save_rejected", lambda: frappe.get_doc(childtype, a.estimate_lines[0].name).save(),
             (frappe.ValidationError, frappe.PermissionError))
    check("rejected_child_attacks_preserve_both_parents", frappe.get_doc(dt, a.name).estimated_total == 8
          and frappe.get_doc(dt, b.name).estimate_lines[0].parent == b.name
          and frappe.db.count(childtype, {"parent": a.name}) == 2)
    for label, value in (("negative", "-1"), ("nan", "NaN"), ("infinity", "Infinity"),
                         ("numeric_limit", "1000000000000"), ("nonnumeric", "not-a-number")):
        rejected(label + "_calculation_source_rejected", lambda value=value: new_record(quantity=value).insert())
    rejected("integer_fraction_rejected", lambda: new_record(integer_dt, quantity="2.25").insert())
    rejected("multiplication_result_limit_rejected", lambda: new_record(quantity=1000000, price=1000000).insert())

    def overflow_sum():
        doc = new_record(quantity=600000000000, price=1)
        doc.estimate_lines[1].quantity = 600000000000
        doc.estimate_lines[1].unit_price = 1
        return doc.insert()

    rejected("sum_result_limit_rejected", overflow_sum)
    rejected("fraction_rounding_cannot_store_source_at_numeric_limit",
             lambda: new_record(quantity="999999999999.9999999995", price="0.000000001").insert())
    rejected("empty_required_table_rejected", lambda: frappe.get_doc({"doctype": dt, "title": "Empty QA", "estimate_lines": []}).insert())
    rejected("missing_required_child_label_rejected", lambda: modify_a(
        lambda doc: setattr(doc.estimate_lines[0], "item_label", "")))

    def too_many(doc):
        for index in range(499):
            doc.append("estimate_lines", {"item_label": "Synthetic " + str(index), "quantity": 1, "unit_price": 1})

    rejected("more_than_500_child_rows_rejected", lambda: modify_a(too_many))

    def tamper_amounts(doc):
        doc.estimated_total = -999
        doc.estimate_lines[0].line_amount = 999999

    modify_a(tamper_amounts)
    current = frappe.get_doc(dt, a.name)
    check("amount_tampering_is_recomputed_on_save", current.estimated_total == 8 and current.estimate_lines[0].line_amount == 6)
    frappe.db.savepoint("valid_native_new_children")
    try:
        current.append("estimate_lines", {"item_label": "Synthetic new ORM row", "quantity": 2, "unit_price": 2})
        current.save()
        reread = frappe.get_doc(dt, a.name)
        check("ordinary_new_child_append_remains_supported", len(reread.estimate_lines) == 3 and reread.estimated_total == 12)
        reread.append("estimate_lines", {"doctype": childtype, "name": "new-synthetic-" + run_id, "__islocal": 1,
            "item_label": "Synthetic new Desk row", "quantity": 2, "unit_price": 3})
        reread.save()
        persisted = frappe.get_doc(dt, a.name)
        check("native_islocal_child_payload_remains_supported", len(persisted.estimate_lines) == 4 and persisted.estimated_total == 18)
    finally:
        frappe.db.rollback(save_point="valid_native_new_children")
    current = frappe.get_doc(dt, a.name)
    current_int = frappe.get_doc(integer_dt, ints.name)
    current_int.estimate_lines[0].quantity = 3
    current_int.save()
    check("table_only_v2_updates_and_calculates_without_workflow", frappe.get_doc(integer_dt, ints.name).estimated_total == 11)
    frappe.db.commit()

    viewer = "v2-bound-viewer-" + run_id + "@example.invalid"
    frappe.get_doc({"doctype": "User", "email": viewer, "first_name": "Synthetic v2 boundary",
        "enabled": 1, "send_welcome_email": 0, "user_type": "System User", "roles": []}).insert()
    frappe.db.commit()
    for user, label in ((viewer, "ungranted_user"), ("Guest", "guest")):
        frappe.set_user(user)
        rejected(label + "_cannot_create", lambda: new_record().insert(), frappe.PermissionError)
        rejected(label + "_cannot_write", lambda: modify_a(lambda doc: setattr(doc, "title", "Unauthorized")), frappe.PermissionError)
        rejected(label + "_cannot_activate", lambda: bp.activate(float_proposal["proposal_id"], float_proposal["revision"]),
                 (frappe.PermissionError, frappe.AuthenticationError), savepoint=False)
        check(label + "_has_no_read_permission", not frappe.has_permission(dt, "read", doc=a.name))
    frappe.set_user("Administrator")

    # Drift only this run's synthetic metadata; restore through ordinary DocType
    # saves in finally, even when the candidate rejects or accepts unexpectedly.
    def metadata_drift(label, mutate, restore):
        doc = frappe.get_doc("DocType", dt)
        try:
            mutate(doc)
            doc.save()
            frappe.clear_cache(doctype=dt)
            check(label + "_state_is_conflict", bp._state(float_spec) == "conflict")
            rejected(label + "_blocks_record_write", lambda: modify_a(lambda row: setattr(row, "title", "Blocked drift")))
        finally:
            doc = frappe.get_doc("DocType", dt)
            restore(doc)
            doc.save()
            frappe.clear_cache(doctype=dt)
            frappe.db.commit()
        check(label + "_restored_exactly_active", bp._state(float_spec) == "active")

    original = frappe.get_doc("DocType", dt).as_dict()
    metadata_drift("missing_manifest", lambda doc: setattr(doc, "description", ""),
                   lambda doc: setattr(doc, "description", original.description))
    metadata_drift("changed_field_label", lambda doc: setattr(doc.fields[1], "label", "Unreviewed QA drift"),
                   lambda doc: setattr(doc.fields[1], "label", original.fields[1].label))
    metadata_drift("permission_expansion", lambda doc: setattr(doc.permissions[0], "delete", 1),
                   lambda doc: setattr(doc.permissions[0], "delete", original.permissions[0].delete))
    metadata_drift("missing_child_table_field", lambda doc: doc.set("fields", [row for row in doc.fields if row.fieldname != "estimate_lines"]),
                   lambda doc: doc.set("fields", copy.deepcopy(v2.definitions(float_spec)[-1]["fields"])))

    # Table-only v2 is already non-submittable. Removing its Table metadata and
    # disguising the manifest as v1 must not disable all runtime validation.
    try:
        downgraded = frappe.get_doc("DocType", integer_dt)
        downgraded.description = "Business blueprint " + "0" * 64
        downgraded.set("fields", [row for row in downgraded.fields if row.fieldtype != "Table"])
        downgraded.save()
        frappe.clear_cache(doctype=integer_dt)
        check("v2_downgrade_state_is_conflict", bp._state(int_spec) == "conflict")

        def write_downgraded():
            record = frappe.get_doc(integer_dt, ints.name)
            record.title = "This unreviewed downgrade must not save"
            return record.save()

        rejected("v2_cannot_downgrade_into_v1_guard_bypass", write_downgraded)
    finally:
        downgraded = frappe.get_doc("DocType", integer_dt)
        expected = v2.definitions(int_spec)[-1]
        downgraded.description = expected["description"]
        downgraded.set("fields", copy.deepcopy(expected["fields"]))
        downgraded.save()
        frappe.clear_cache(doctype=integer_dt)
        frappe.db.commit()
    check("downgraded_metadata_restored_exactly_active", bp._state(int_spec) == "active")

    # A reversible physical-table rename simulates an interrupted DDL install.
    # Targets are locally generated names from this run, never caller SQL/path.
    physical = "tab" + childtype
    holding = physical + "_qa_hold"
    assert childtype.startswith(v2.ROW_PREFIX) and len(holding) < 64 and "`" not in physical + holding
    assert not frappe.db.table_exists(childtype + "_qa_hold")
    renamed = False
    try:
        frappe.db.sql("RENAME TABLE `" + physical + "` TO `" + holding + "`")
        renamed = True
        check("missing_physical_child_table_is_conflict_not_active", bp._state(float_spec) == "conflict")
        observations.append({"test": "physical_table_missing", "table_exists_uncached": frappe.db.table_exists(childtype, cached=False)})
        rejected("partial_ddl_cannot_be_reactivated_or_silently_repaired",
                 lambda: bp.activate(float_proposal["proposal_id"], float_proposal["revision"]), savepoint=False)
        rejected("partial_ddl_runtime_guard_blocks_before_write", lambda: v2.validate_document(current))
    finally:
        if renamed:
            frappe.db.sql("RENAME TABLE `" + holding + "` TO `" + physical + "`")
            frappe.db.table_exists(childtype, cached=False)
            frappe.clear_cache(doctype=childtype)
            frappe.db.commit()
    check("physical_child_table_restored_with_original_rows", bp._state(float_spec) == "active"
          and frappe.db.count(childtype, {"parent": a.name}) == 2)
    column_renamed = False
    try:
        frappe.db.sql("ALTER TABLE `" + physical + "` RENAME COLUMN `quantity` TO `qa_quantity_hold`")
        column_renamed = True
        check("missing_physical_column_is_conflict_despite_cached_meta", bp._state(float_spec) == "conflict")
        rejected("missing_physical_column_blocks_runtime_write", lambda: v2.validate_document(current))
        rejected("missing_physical_column_cannot_be_reactivated", lambda: bp.activate(
            float_proposal["proposal_id"], float_proposal["revision"]), savepoint=False)
    finally:
        if column_renamed:
            frappe.db.sql("ALTER TABLE `" + physical + "` RENAME COLUMN `qa_quantity_hold` TO `quantity`")
            frappe.clear_cache(doctype=childtype)
            frappe.db.commit()
    check("physical_column_restored_with_values", bp._state(float_spec) == "active"
          and frappe.get_doc(dt, a.name).estimate_lines[0].quantity == 2)
    check("negative_tests_did_not_add_records", frappe.db.count(dt) == 2 and frappe.db.count(integer_dt) == 1)
    frappe.db.commit()
    frappe.destroy()
    connect()
    check("new_connection_confirms_restored_schema_and_amounts", bp._state(float_spec) == "active"
          and bp._state(int_spec) == "active" and frappe.get_doc(dt, a.name).estimated_total == 8
          and frappe.get_doc(integer_dt, ints.name).estimated_total == 11)
    report = {"isolated_site": SITE, "run_id": run_id, "passed": len(checks), "checks": checks,
        "critical_findings": findings, "observations": observations, "all_boundaries_passed": not findings,
        "retained_synthetic_types": retained, "production_writes": False, "browser_ui_tested": False}
    (ROOT / ("complex-blueprint-boundaries-" + run_id + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
finally:
    if getattr(frappe.local, "db", None):
        frappe.db.rollback()
    frappe.destroy()
