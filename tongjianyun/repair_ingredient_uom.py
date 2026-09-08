"""Opt-in missing gram UOM repair; no Item rewrites or schema changes."""
import argparse
import json

import frappe


def inspect():
    rows = frappe.get_list("Item", filters={"stock_uom": "g"},
        fields=["name", "modified", "purchase_uom", "sales_uom"], order_by="name", limit_page_length=0)
    details = []
    for row in rows:
        item = frappe.get_doc("Item", row.name)
        item.check_permission("read")
        details.append({**dict(row), "uoms": [{"uom": u.uom, "factor": u.conversion_factor} for u in item.uoms]})
    codes = [r.name for r in rows]
    return {"site": frappe.local.site, "item_count": len(rows),
        "g_exists": bool(frappe.db.exists("UOM", "g")),
        "stock_ledger_count": frappe.db.count("Stock Ledger Entry", {"item_code": ["in", codes]}) if codes else 0,
        "bin_count": frappe.db.count("Bin", {"item_code": ["in", codes]}) if codes else 0,
        "items": details}


def verify():
    from frappe.utils import add_days, nowdate
    before = inspect()
    assert before["g_exists"] and before["item_count"] == 68
    uom = frappe.get_doc("UOM", "g")
    assert uom.enabled and not uom.must_be_whole_number
    company = frappe.get_list("Company", pluck="name", limit_page_length=1)[0]
    warehouse = frappe.get_list("Warehouse", filters={"company": company, "is_group": 0, "disabled": 0},
                                pluck="name", limit_page_length=1)[0]
    request = frappe.get_doc({"doctype": "Material Request", "company": company,
        "material_request_type": "Purchase", "transaction_date": nowdate(), "set_warehouse": warehouse,
        "items": [{"item_code": row["name"], "qty": 1, "uom": "g", "warehouse": warehouse,
                   "schedule_date": add_days(nowdate(), 7)} for row in before["items"]]})
    request.insert()
    assert request.docstatus == 0 and len(request.items) == 68
    assert all(row.stock_uom == "g" and row.conversion_factor == 1 for row in request.items)
    name = request.name
    frappe.db.rollback()
    assert not frappe.db.exists("Material Request", name)
    after = inspect()
    assert before == after
    print(json.dumps({"uom_persisted": True, "erp_draft_lines_validated": 68,
        "conversion_factor": 1, "verification_draft_rolled_back": True, "items_unchanged": True}))


def run(apply=False, check=False):
    frappe.init(site="child.myyr.top", sites_path="/home/zyd/frappe/native-bench/sites")
    frappe.connect()
    frappe.set_user("Administrator")
    try:
        if check:
            verify()
            return
        before = inspect()
        if not apply:
            print(json.dumps(before, ensure_ascii=False, default=str))
            return
        if before["item_count"] != 68 or before["g_exists"]:
            raise RuntimeError("Expected 68 dangling gram references and missing g; rerun preview before changing scope")
        gram = frappe.get_doc("UOM", "Gram")
        gram.check_permission("read")
        if not gram.enabled or gram.must_be_whole_number:
            raise RuntimeError("Standard Gram master must be enabled and allow fractions")
        uom = frappe.get_doc({"doctype": "UOM", "uom_name": "g", "symbol": "g", "enabled": 1,
            "must_be_whole_number": 0, "category": gram.category,
            "description": "克（gram）。兼容童健云既有食材的 g 库存单位；1 g = 1 Gram。"})
        uom.insert()
        after = inspect()
        assert after["g_exists"] and after["items"] == before["items"]
        assert after["stock_ledger_count"] == before["stock_ledger_count"]
        assert after["bin_count"] == before["bin_count"]
        frappe.db.commit()
        print(json.dumps({"created": {"doctype": "UOM", "name": uom.name, "enabled": uom.enabled,
            "must_be_whole_number": uom.must_be_whole_number}, "resolved_item_references": 68,
            "items_rewritten": 0, "stock_ledger_changes": 0, "schema_changes": 0}))
    except Exception:
        frappe.db.rollback()
        raise
    finally:
        frappe.db.rollback()
        frappe.destroy()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.apply and args.verify:
        parser.error("Choose --apply or --verify, not both")
    run(args.apply, args.verify)
