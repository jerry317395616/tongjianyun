"""Human-confirmed ingredient resolution using existing ERP masters only."""
from difflib import SequenceMatcher
import json

import frappe

from tongjianyun.recipe_procurement import (
    TRACE, _payload, _permission, _read, _source, conversion, digest, number,
)

MAPPING_KIND = "erp_recipe_mapping"
ALIASES = ({"豆腐干", "豆干"}, {"西红柿", "番茄"})
FILTERS = {"disabled": 0, "is_purchase_item": 1, "is_stock_item": 1, "has_variants": 0}


def requires_product_confirmation(name):
    return any(word in name for word in ("汤", "炖", "炒", "焖", "煲", "粥"))


def candidate_score(source, target):
    if source == target:
        return 1.0, "同名候选"
    if any(source in group and target in group for group in ALIASES):
        return .99, "常见别名，需确认规格"
    if any((word in source) != (word in target) for word in ("芽", "酱", "糁", "棒", "汤", "粥", "粒")):
        return 0.0, "加工形态不同，不推荐合并"
    score = SequenceMatcher(None, source, target).ratio()
    return score, "名称相近，不代表规格相同"


def suggestions(ingredients):
    items = frappe.get_list("Item", filters=FILTERS, fields=["name", "item_name", "stock_uom"], limit_page_length=0)
    units = set(frappe.get_list("UOM", filters={"enabled": 1}, pluck="name", limit_page_length=0))
    for row in ingredients:
        ranked = []
        if not row["item_code"]:
            for item in items:
                score, reason = candidate_score(row["ingredient"], item.item_name)
                if score >= .55:
                    ranked.append({"item_code": item.name, "uom": item.stock_uom,
                                   "reason": reason, "score": score})
        row["candidates"] = sorted(ranked, key=lambda x: (-x["score"], x["item_code"]))[:3]
        row["needs_product_confirmation"] = requires_product_confirmation(row["ingredient"])
        row["suggested_uom"] = next((u for u in (row["source_uom"], "Gram", "Kg", "Millilitre", "Litre")
            if u in units and conversion(row["source_uom"], u) == 1), "")
    return ingredients


def _build(recipe, company, decisions, default_group):
    _permission(TRACE, "read")
    _permission(TRACE, "create")
    _permission("Item", "read")
    _read("Company", company)
    doc, source = _source(recipe)
    source_by_key = {row["key"]: row for row in source}
    decisions = _payload(decisions)
    if not isinstance(decisions, list) or not 0 < len(decisions) <= 200:
        frappe.throw("请选择 1 至 200 项食材进行确认。")
    rows, seen, new_names = [], set(), set()
    for decision in decisions:
        if not isinstance(decision, dict):
            frappe.throw("食材处理参数无效。")
        key = decision.get("key")
        if key not in source_by_key or key in seen:
            frappe.throw("食材已变化或重复，请重新加载。")
        seen.add(key)
        source_row = source_by_key[key]
        action = decision.get("action")
        if action == "暂不处理":
            continue
        if action not in ("关联已有", "新建物料"):
            frappe.throw("不支持的食材处理方式。")
        if requires_product_confirmation(source_row["ingredient_name"]) and str(decision.get("external_product")) != "1":
            frappe.throw("汤、粥或烹饪菜品需先确认确实外购成品；自制菜品应拆分配方，不能直接建立采购物料。")
        if action == "关联已有":
            item = _read("Item", decision.get("item_code") or "")
            if any(item.get(k) != v for k, v in FILTERS.items()):
                frappe.throw("关联物料必须启用、可采购且维护库存，不能是变体模板。")
            code, unit, group = item.name, item.stock_uom, item.item_group
        else:
            _permission("Item", "create")
            if source_row["ingredient_name"] in new_names:
                frappe.throw("同批出现同名、不同单位的食材，请分批确认并复用同一个物料。")
            new_names.add(source_row["ingredient_name"])
            unit = decision.get("uom") or ""
            group = decision.get("item_group") or default_group
            group_doc = _read("Item Group", group or "")
            if group_doc.is_group:
                frappe.throw("新物料请选择明细物料组。")
            code = "TJY-FOOD-" + digest([source_row["ingredient_name"], unit, group])[:20].upper()
            # Do not reveal inaccessible matches, or create duplicates of existing masters.
            if frappe.db.exists("Item", {"item_name": source_row["ingredient_name"]}):
                frappe.throw("该食材已有同名物料，请改为关联已有物料；无权读取时请联系管理员。")
        uom = _read("UOM", unit)
        if not uom.enabled:
            frappe.throw("库存单位已停用。")
        try:
            factor = number(decision.get("factor"))
        except (TypeError, ValueError, OverflowError):
            frappe.throw("请填写正数的采购毛料换算系数。")
        rows.append({"key": key, "ingredient": source_row["ingredient_name"], "source_uom": source_row["unit"],
            "action": action, "item_code": code, "uom": unit, "item_group": group,
            "factor": factor, "external_product": bool(requires_product_confirmation(source_row["ingredient_name"]))})
    if not rows:
        frappe.throw("没有选择需要确认的项目；未处理项目会继续阻止生成完整采购需求。")
    plan = {"recipe": doc.name, "company": company, "revision": digest(source), "rows": rows}
    plan["token"] = digest(plan)
    return plan


@frappe.whitelist()
def preview_resolution(recipe, company, decisions, default_group=""):
    return _build(recipe, company, decisions, default_group)


@frappe.whitelist(methods=["POST"])
def apply_resolution(recipe, company, decisions, token, default_group="", confirmed=0):
    if str(confirmed) != "1":
        frappe.throw("请先核对批量处理预览，再明确确认。")
    _permission(TRACE, "read")
    _permission(TRACE, "create")
    _read("Company", company)
    _read("Tongjianyun Recipe", recipe)
    # Immutable batch receipt gives safe retries even after new Items now exist.
    key = MAPPING_KIND + "::" + digest([recipe, company, token])[:32]
    if frappe.db.exists(TRACE, key):
        receipt = _read(TRACE, key)
        saved = json.loads(receipt.record_json)
        for mapping in saved["mappings"].values():
            _read("Item", mapping["item_code"])
        return {"created": [], "mappings": saved["mappings"], "existing": True}
    plan = _build(recipe, company, decisions, default_group)
    if plan["token"] != token:
        frappe.throw("食谱或物料已变化，请重新预览。")
    mappings = {row["key"]: {"item_code": row["item_code"], "uom": row["uom"], "factor": row["factor"]} for row in plan["rows"]}
    receipt = frappe.get_doc({"doctype": TRACE, "data_key": key, "record_type": MAPPING_KIND,
        "record_id": token, "parent_id": recipe, "title": "食材匹配确认 · " + recipe,
        "status": "已确认", "source": "ERPNext Item mapping",
        "record_json": json.dumps({**plan, "mappings": mappings}, ensure_ascii=False)})
    receipt.insert()
    created = []
    for row in plan["rows"]:
        if row["action"] == "新建物料":
            item = frappe.get_doc({"doctype": "Item", "item_code": row["item_code"],
                "item_name": row["ingredient"], "item_group": row["item_group"], "stock_uom": row["uom"],
                "is_stock_item": 1, "is_purchase_item": 1, "is_sales_item": 0})
            item.insert()
            created.append(item.name)
    return {"created": created, "mappings": mappings, "existing": False}
