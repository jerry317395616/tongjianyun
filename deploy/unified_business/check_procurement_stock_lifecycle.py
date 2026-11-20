"""Real native procurement/stock lifecycle on the fixed isolated QA site only.

No copied production fixtures, no bypassed validators/permissions, no SQL state
changes. Successful records and an evidence report are retained for inspection.
"""
import json
import os
import sys
import uuid
from pathlib import Path
from urllib.parse import quote, urlparse

SITE = "unified-business-acceptance.localhost"
ROOT = Path("/home/zyd/frappe/remote-workspace/tgy-blueprint-lifecycle-qa-20260925").resolve()
sites = Path(os.environ["UNIFIED_BUSINESS_SITES"]).resolve(strict=True)
source = Path(os.environ["UNIFIED_BUSINESS_SOURCE"]).resolve(strict=True)
assert sites == ROOT / "sites", "Only the dedicated isolated sites directory is permitted"
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
from frappe.utils import flt, getdate, nowdate
from erpnext.buying.doctype.purchase_order.mapper import make_purchase_receipt
from erpnext.stock.doctype.purchase_receipt.mapper import make_purchase_return
from erpnext.controllers.status_updater import get_allowance_for
from erpnext.stock.doctype.repost_item_valuation.repost_item_valuation import execute_reposting_entry
from tongjianyun import business_views, frappe_project_views, meal_views
from tongjianyun.meal_chat import TaskStore
from tongjianyun.meal_view_tool import use_site_os_identity

for module in (business_views, frappe_project_views, meal_views):
    assert Path(module.__file__).resolve().is_relative_to(source), "Wrong candidate source"
use_site_os_identity(sites / SITE)
os.umask(0o077)
run_id = uuid.uuid4().hex[:10]
checks, states, records, reposts, observed_defects, native_repairs = [], [], {}, [], [], []


def check(label, condition):
    assert condition, label
    checks.append(label)
    print(json.dumps({"passed": label}, ensure_ascii=False), flush=True)


def denied(label, action, exception=frappe.ValidationError):
    point = "reject_" + uuid.uuid4().hex[:8]
    frappe.db.savepoint(point)
    try:
        action()
    except exception:
        frappe.db.rollback(save_point=point)
        check(label, True)
        return
    raise AssertionError(label + ": unexpected success")


def connect():
    frappe.init(site=SITE, sites_path=str(sites))
    guard(frappe.conf)  # Effective configuration verified BEFORE connecting.
    frappe.connect()
    frappe.set_user("Administrator")


connect()
try:
    day = nowdate()
    companies = frappe.get_all("Company", filters={"company_name": ["like", "QA Meal %"]}, pluck="name")
    assert len(companies) == 1, "Expected one retained synthetic Company; do not select real company data"
    company = frappe.get_doc("Company", companies[0])
    assert company.company_name.startswith("QA Meal ")
    if not frappe.db.exists("Fiscal Year", {"year_start_date": ["<=", day], "year_end_date": [">=", day], "disabled": 0}):
        date = getdate(day)
        frappe.get_doc({"doctype": "Fiscal Year", "year": "QA Stock " + run_id,
            "year_start_date": str(date.replace(month=1, day=1)),
            "year_end_date": str(date.replace(month=12, day=31))}).insert()
    uom = frappe.get_doc({"doctype": "UOM", "uom_name": "QA Stock Unit " + run_id,
                         "must_be_whole_number": 1}).insert()
    item_group_root = frappe.db.get_value("Item Group", {"is_group": 1}, "name")
    supplier_group_root = frappe.db.get_value("Supplier Group", {"is_group": 1}, "name")
    if not item_group_root:
        item_group_root = frappe.get_doc({"doctype": "Item Group", "item_group_name": "QA Stock Root " + run_id,
            "is_group": 1, "parent_item_group": ""}).insert().name
    if not supplier_group_root:
        supplier_group_root = frappe.get_doc({"doctype": "Supplier Group", "supplier_group_name": "QA Stock Root " + run_id,
            "is_group": 1, "parent_supplier_group": ""}).insert().name
    supplier_group = frappe.get_doc({"doctype": "Supplier Group", "supplier_group_name": "QA Stock " + run_id,
        "parent_supplier_group": supplier_group_root}).insert()
    item_group = frappe.get_doc({"doctype": "Item Group", "item_group_name": "QA Stock " + run_id,
        "parent_item_group": item_group_root}).insert()
    supplier = frappe.get_doc({"doctype": "Supplier", "supplier_name": "QA Stock " + run_id,
        "supplier_type": "Company", "supplier_group": supplier_group.name}).insert()
    warehouse_parent = frappe.db.get_value("Warehouse", {"company": company.name, "is_group": 1}, "name")
    assert warehouse_parent, "Synthetic Company requires its native warehouse root"
    warehouse = frappe.get_doc({"doctype": "Warehouse", "warehouse_name": "QA Stock " + run_id,
        "company": company.name, "parent_warehouse": warehouse_parent, "is_group": 0}).insert()
    item = frappe.get_doc({"doctype": "Item", "item_code": "QA-STOCK-" + run_id,
        "item_name": "Synthetic stock lifecycle " + run_id, "item_group": item_group.name,
        "stock_uom": uom.name, "is_stock_item": 1, "is_purchase_item": 1,
        "valuation_method": "FIFO", "item_defaults": [{"company": company.name,
            "default_warehouse": warehouse.name, "buying_cost_center": company.cost_center,
            "expense_account": company.default_expense_account}]}).insert()
    records.update(company=company.name, item=item.name, supplier=supplier.name, warehouse=warehouse.name)

    def bin_values():
        row = frappe.db.get_value("Bin", {"item_code": item.name, "warehouse": warehouse.name},
            ["actual_qty", "ordered_qty", "stock_value"], as_dict=True) or {}
        return {field: flt(row.get(field)) for field in ("actual_qty", "ordered_qty", "stock_value")}

    def ledger():
        return frappe.get_all("Stock Ledger Entry", filters={"item_code": item.name, "warehouse": warehouse.name},
            fields=["name", "voucher_type", "voucher_no", "actual_qty", "qty_after_transaction", "is_cancelled"],
            order_by="creation asc")

    def state(label, quantity, received, ordered):
        po.reload()
        values = bin_values()
        states.append({"stage": label, "bin": values, "po_received_qty": flt(po.items[0].received_qty),
                       "po_returned_qty": flt(po.items[0].returned_qty), "po_docstatus": int(po.docstatus)})
        check(label, values["actual_qty"] == quantity and flt(po.items[0].received_qty) == received
              and values["ordered_qty"] == ordered)

    def finish_valuation(vouchers):
        """Run only this synthetic item's native queued jobs, not a global worker.

        ERPNext cancellation updates quantity immediately but values via repost.
        The dedicated site deliberately has no scheduler/worker. Native repost
        commits its own transaction, so completed fixtures remain as evidence.
        """
        filters = {"company": company.name, "docstatus": 1, "status": ["in", ["Queued", "In Progress"]]}
        names = frappe.get_all("Repost Item Valuation", filters={**filters,
            "based_on": "Item and Warehouse", "item_code": item.name, "warehouse": warehouse.name}, pluck="name")
        names += frappe.get_all("Repost Item Valuation", filters={**filters,
            "based_on": "Transaction", "voucher_type": "Purchase Receipt", "voucher_no": ["in", vouchers]}, pluck="name")
        for name in dict.fromkeys(names):
            doc = frappe.get_doc("Repost Item Valuation", name)
            assert doc.company == company.name and (
                doc.based_on == "Item and Warehouse" and doc.item_code == item.name and doc.warehouse == warehouse.name
                or doc.based_on == "Transaction" and doc.voucher_type == "Purchase Receipt" and doc.voucher_no in vouchers)
            original_flag = frappe.flags.through_repost_item_valuation
            original_max_writes = frappe.db.MAX_WRITES_PER_TRANSACTION
            try:
                execute_reposting_entry(name)
            finally:
                frappe.flags.through_repost_item_valuation = original_flag
                frappe.db.MAX_WRITES_PER_TRANSACTION = original_max_writes
            doc.reload()
            assert doc.status in {"Completed", "Skipped"}, "Scoped native valuation job did not complete: " + name
            reposts.append({"name": name, "status": doc.status})

    def verify_or_recalculate_value(label, expected_value):
        """Preserve the native-flow defect, then verify the native repair path.

        This does not disguise a stale Bin as native lifecycle success. A repair
        is reported separately and uses the existing permission-checked method.
        """
        before = bin_values()
        if before["stock_value"] != expected_value:
            observed_defects.append({"stage": label, "defect": "bin_value_stale_after_completed_native_repost",
                "bin_before_repair": before, "expected_stock_value": expected_value,
                "native_reposting_states": list(reposts)})
            bin_name = frappe.db.get_value("Bin", {"item_code": item.name, "warehouse": warehouse.name}, "name")
            doc = frappe.get_doc("Bin", bin_name)
            doc.check_permission("write")
            doc.recalculate_values()
            native_repairs.append({"stage": label, "service": "Bin.recalculate_values",
                                   "bin_after_repair": bin_values()})
        check(label, bin_values()["stock_value"] == expected_value)

    po = frappe.get_doc({"doctype": "Purchase Order", "company": company.name,
        "supplier": supplier.name, "transaction_date": day, "schedule_date": day,
        "currency": company.default_currency, "conversion_rate": 1,
        "items": [{"item_code": item.name, "qty": 10, "rate": 3,
                   "schedule_date": day, "warehouse": warehouse.name}]}).insert()
    records["purchase_order"] = po.name
    check("draft_order_has_no_stock_ledger_or_actual_stock", po.docstatus == 0 and not ledger()
          and bin_values()["actual_qty"] == 0 and bin_values()["ordered_qty"] == 0)
    denied("unsubmitted_order_cannot_map_to_receipt", lambda: make_purchase_receipt(po.name))
    po.submit()
    state("submitted_order_reserves_ordered_not_actual_stock", 0, 0, 10)

    def receipt(qty=None):
        doc = make_purchase_receipt(po.name)
        doc.posting_date = day
        doc.set_warehouse = warehouse.name
        if qty is not None:
            doc.items[0].qty = qty
            doc.items[0].received_qty = qty
        doc.insert()
        return doc

    first = receipt(4)
    check("native_mapper_keeps_exact_order_and_row_links", first.items[0].purchase_order == po.name
          and first.items[0].purchase_order_item == po.items[0].name and first.items[0].item_code == item.name)
    check("draft_receipt_does_not_change_actual_stock", not ledger() and bin_values()["actual_qty"] == 0)
    first.submit()
    state("partial_receipt_updates_stock_and_order_four_of_ten", 4, 4, 6)
    check("partial_receipt_creates_native_stock_ledger", len(ledger()) == 1
          and ledger()[0].voucher_no == first.name and flt(ledger()[0].actual_qty) == 4)
    ledger_before_repeat = len(ledger())
    frappe.get_doc("Purchase Receipt", first.name).submit()
    check("native_repeat_submit_is_idempotent_without_new_ledger", len(ledger()) == ledger_before_repeat)
    state("idempotent_repeat_submit_does_not_double_stock", 4, 4, 6)
    allowance = flt(get_allowance_for(item.name, qty_or_amount="qty")[0])
    bypass_role = frappe.get_single_value("Stock Settings", "role_allowed_to_over_deliver_receive")
    assert not bypass_role, "QA configuration grants an over-receipt override; test must not override it silently"

    def over_receive():
        receipt(10 * (100 + allowance) / 100 + 10).submit()

    denied("receipt_exceeding_configured_allowance_is_rejected", over_receive)
    state("rejected_over_receipt_does_not_change_bin_or_order", 4, 4, 6)
    second = receipt()
    check("second_mapping_contains_remaining_six", flt(second.items[0].qty) == 6)
    second.submit()
    state("complete_receipt_updates_stock_and_order_ten_of_ten", 10, 10, 0)
    check("complete_order_reports_100_percent_received", flt(po.per_received) == 100)
    records.update(partial_receipt=first.name, completion_receipt=second.name)

    # Verify view DATA and native operation selection for these exact records,
    # plus the task-owned SSE selection; this is not a browser-loaded claim.
    store = TaskStore()
    task_id = str(uuid.uuid4())
    store.update(task_id, owner="Administrator", status="running", cancel_requested="0", day=day, meal="lunch")
    for entity, doc in (("purchase_orders", po), ("purchase_receipts", second)):
        choice = {"view": "business_record", "entity": entity, "record": doc.name, "day": day, "meal": "lunch"}
        view = meal_views.get_view(choice)
        check(entity + "_view_contains_exact_document_and_synthetic_item", view["subtitle"] == doc.name
              and view["selection"]["record"] == doc.name and item.name in json.dumps(view["components"]))
        actions = [action.get("selection", {}) for action in view["actions"]]
        check(entity + "_operation_targets_exact_document", any(action.get("doctype") == doc.doctype
              and action.get("document") == doc.name and action.get("view") == "frappe_document" for action in actions))
        native = meal_views.get_view({"view": "frappe_document", "doctype": doc.doctype, "document": doc.name})
        frame = next(row for row in native["components"] if row["type"] == "frappe_frame")
        check(entity + "_native_form_targets_exact_record", frame["route"] == "/desk/" + frappe_project_views.slug(doc.doctype)
              + "/" + quote(doc.name, safe=""))
        meal_views.publish_for_task(task_id, choice)
        check(entity + "_task_event_targets_exact_record", store.events(task_id)[-1]["selection"]["record"] == doc.name)
    stock_view = meal_views.get_view({"view": "stock", "warehouse": warehouse.name})
    stock_rows = [row for block in stock_view["components"] if block["type"] == "table" for row in block["rows"]]
    item_row = next(row for row in stock_rows if item.name in row["cells"])
    check("stock_view_shows_exact_warehouse_item_and_actual_ten", stock_view["selection"]["warehouse"] == warehouse.name
          and item_row["cells"][2] == 10)

    returned = make_purchase_return(second.name)
    returned.items[0].qty = -2
    returned.items[0].received_qty = -2
    returned.posting_date = day
    # Mirror native Desk's mapped JSON -> Document boundary. PurchaseReceipt's
    # constructor installs return-specific status updaters from is_return;
    # the mapper sets that field after constructing its initial Python object.
    returned = frappe.get_doc(returned.as_dict())
    check("return_payload_rehydrates_native_return_status_updaters", any(
        entry.get("target_field") == "returned_qty" for entry in returned.status_updater))
    returned.insert()
    check("draft_return_does_not_reduce_stock", bin_values()["actual_qty"] == 10)
    returned.submit()
    state("native_return_reverses_stock_and_order_by_two", 8, 8, 2)
    check("return_records_original_receipt_and_returned_qty", returned.return_against == second.name
          and flt(po.items[0].returned_qty) == 2 and any(row.voucher_no == returned.name
          and flt(row.actual_qty) == -2 for row in ledger()))
    records["return_receipt"] = returned.name
    returned.cancel()
    finish_valuation([first.name, second.name, returned.name])
    state("cancelling_return_restores_stock_and_order", 10, 10, 0)
    verify_or_recalculate_value("cancelled_return_value_thirty_after_native_recalculation_if_needed", 30)
    second.reload()
    second.cancel()
    finish_valuation([first.name, second.name, returned.name])
    state("cancelling_second_receipt_reverses_six", 4, 4, 6)
    verify_or_recalculate_value("cancelled_second_receipt_value_twelve_after_native_recalculation_if_needed", 12)
    first.reload()
    first.cancel()
    finish_valuation([first.name, second.name, returned.name])
    state("cancelling_first_receipt_reverses_remaining_four", 0, 0, 10)
    verify_or_recalculate_value("cancelled_all_receipts_value_zero_after_native_recalculation_if_needed", 0)
    po.cancel()
    state("cancelling_order_clears_ordered_qty", 0, 0, 0)
    check("cancelled_receipts_have_no_active_stock_or_accounting_ledger", not frappe.db.exists("Stock Ledger Entry",
          {"item_code": item.name, "warehouse": warehouse.name, "is_cancelled": 0}) and not frappe.db.exists("GL Entry",
          {"voucher_type": "Purchase Receipt", "voucher_no": ["in", [first.name, second.name, returned.name]], "is_cancelled": 0}))
    quantity_before_repeat, ledger_before_repeat = bin_values(), len(ledger())
    try:
        frappe.get_doc("Purchase Receipt", first.name).cancel()
        repeat_cancel_outcome = "idempotent"
    except frappe.ValidationError:
        repeat_cancel_outcome = "rejected_by_native_validation"
    check("native_repeat_cancel_does_not_reverse_stock_twice", bin_values() == quantity_before_repeat
          and len(ledger()) == ledger_before_repeat and frappe.get_doc("Purchase Receipt", first.name).docstatus == 2)
    final_stock_view = meal_views.get_view({"view": "stock", "warehouse": warehouse.name})
    final_stock_rows = [row for block in final_stock_view["components"] if block["type"] == "table" for row in block["rows"]]
    check("stock_view_rereads_zero_after_cancellation", next(row for row in final_stock_rows if item.name in row["cells"])["cells"][2] == 0)

    viewer = "stock-qa-viewer-" + run_id + "@example.invalid"
    frappe.get_doc({"doctype": "User", "email": viewer, "first_name": "Synthetic Stock QA",
        "enabled": 1, "user_type": "System User", "send_welcome_email": 0, "roles": []}).insert()
    frappe.set_user(viewer)
    denied("ungranted_user_cannot_read_order_business_view", lambda: business_views.record_view(
        {"view": "business_record", "entity": "purchase_orders", "record": po.name, "offset": 0, "day": day, "meal": "lunch"}), frappe.PermissionError)
    denied("ungranted_user_cannot_open_receipt_native_view", lambda: frappe_project_views.native_view(
        {"view": "frappe_document", "doctype": "Purchase Receipt", "document": first.name, "day": day, "meal": "lunch"}), frappe.PermissionError)
    denied("ungranted_user_cannot_create_native_order", lambda: frappe.copy_doc(po).insert(), frappe.PermissionError)
    frappe.set_user("Administrator")
    store.update(task_id, status="completed")
    frappe.db.commit()
    frappe.destroy()
    connect()
    check("new_connection_reads_reversed_bin_and_cancelled_records", bin_values()["actual_qty"] == 0
          and bin_values()["ordered_qty"] == 0 and bin_values()["stock_value"] == 0 and all(frappe.get_doc(doctype, name).docstatus == 2
          for doctype, name in (("Purchase Order", po.name), ("Purchase Receipt", first.name),
                               ("Purchase Receipt", second.name), ("Purchase Receipt", returned.name))))
    report = {"isolated_site": SITE, "run_id": run_id, "passed": len(checks), "checks": checks,
        "states": states, "retained_synthetic_records": records, "native_valuation_jobs": reposts,
        "native_over_receipt_allowance_percent": allowance,
        "repeat_cancel_outcome": repeat_cancel_outcome, "native_flow_complete_without_repair": not observed_defects,
        "observed_defects": observed_defects, "verified_native_repairs": native_repairs,
        "production_writes": False, "browser_ui_tested": False}
    (ROOT / ("procurement-stock-lifecycle-" + run_id + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))
finally:
    if getattr(frappe.local, "db", None):
        frappe.db.rollback()
    frappe.destroy()
