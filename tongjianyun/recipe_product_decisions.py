"""Persist explicit product decisions using existing audited trace documents."""
import json
import frappe
from tongjianyun.recipe_procurement import TRACE, _read, _permission, digest, conversion
from tongjianyun.ingredient_resolution import FILTERS, requires_product_confirmation

KIND = "erp_recipe_product_decision"

def record_key(recipe, key):
    return KIND + "::" + digest([recipe, key])[:32]

def read_decision(recipe, row):
    _permission(TRACE, "read")
    key = record_key(recipe, row["key"])
    if not frappe.db.exists(TRACE, key):
        return None
    return json.loads(_read(TRACE, key).record_json)

def external_mapping(decision, row):
    item = _read("Item", decision["item_code"])
    if any(item.get(k) != v for k, v in FILTERS.items()):
        frappe.throw("外购物料已停用或不可采购，请重新确认。")
    unit = _read("UOM", item.stock_uom)
    factor = conversion(row["unit"], item.stock_uom)
    if not unit.enabled or factor is None:
        frappe.throw("外购物料单位不可直接换算，请重新确认。")
    return {"item_code": item.name, "uom": item.stock_uom, "factor": factor}

@frappe.whitelist()
def get_pending(recipe):
    from tongjianyun.recipe_item_sync import source_snapshot
    snapshot = source_snapshot(recipe)
    rows = []
    for row in snapshot["ingredients"]:
        if requires_product_confirmation(row["ingredient"]):
            decision = read_decision(recipe, row)
            rows.append({**row, "decision": decision or {}})
    return {"recipe": recipe, "revision": snapshot["revision"], "rows": rows}

@frappe.whitelist(methods=["POST"])
def confirm(recipe, revision, decisions):
    from tongjianyun.recipe_item_sync import source_snapshot, schedule_after_save
    _read("Tongjianyun Recipe", recipe).check_permission("write")
    locked_modified = frappe.db.get_value("Tongjianyun Recipe", recipe, "modified", for_update=True)
    if str(_read("Tongjianyun Recipe", recipe).modified) != str(locked_modified):
        frappe.throw("食谱已并发更新，请重新打开确认窗口。")
    snapshot = source_snapshot(recipe)
    if snapshot["revision"] != revision:
        frappe.throw("食材已变化，请重新打开待确认窗口。")
    _permission(TRACE, "read")
    _permission(TRACE, "create")
    source = {r["key"]: r for r in snapshot["ingredients"]}
    decisions = frappe.parse_json(decisions)
    if not isinstance(decisions, list) or not 0 < len(decisions) <= 200:
        frappe.throw("确认内容无效。")
    seen = set()
    for choice in decisions:
        key = choice.get("key") if isinstance(choice, dict) else None
        if key not in source or key in seen or not requires_product_confirmation(source[key]["ingredient"]):
            frappe.throw("确认食材无效或重复。")
        seen.add(key)
        row = source[key]
        mode = choice.get("mode")
        if mode not in ("外购", "自制", "暂时跳过"):
            frappe.throw("请选择自制、外购或暂时跳过。")
        data = {"key": key, "ingredient": row["ingredient"], "unit": row["unit"],
            "mode": mode, "actor": frappe.session.user, "item_code": ""}
        if mode == "外购":
            _permission("Item", "read")
            code = str(choice.get("item_code") or "").strip()
            if not code:
                _permission("Item", "create")
                if frappe.db.exists("Item", {"item_name": row["ingredient"]}):
                    frappe.throw("已有同名物料，请选择已有物料，避免重复建档。")
                group = _read("Item Group", choice.get("item_group") or "")
                unit = _read("UOM", choice.get("uom") or "")
                if group.is_group or not unit.enabled or conversion(row["unit"], unit.name) is None:
                    frappe.throw("请选择明细分类和可换算的有效库存单位。")
                code = "TJY-PRODUCT-" + digest([row["ingredient"], unit.name])[:20].upper()
                frappe.get_doc({"doctype": "Item", "item_code": code, "item_name": row["ingredient"],
                    "item_group": group.name, "stock_uom": unit.name, "is_stock_item": 1,
                    "is_purchase_item": 1, "is_sales_item": 0}).insert()
            data["item_code"] = code
            external_mapping(data, row)
        name = record_key(recipe, key)
        doc = _read(TRACE, name) if frappe.db.exists(TRACE, name) else frappe.get_doc({"doctype": TRACE, "data_key": name})
        doc.update({"record_type": KIND, "record_id": key, "parent_id": recipe,
            "title": "食材用途确认 · " + row["ingredient"], "status": mode,
            "source": "用户明确确认", "record_json": json.dumps(data, ensure_ascii=False)})
        doc.save() if not doc.is_new() else doc.insert()
    return {"saved": len(seen), "sync": schedule_after_save(recipe)}
