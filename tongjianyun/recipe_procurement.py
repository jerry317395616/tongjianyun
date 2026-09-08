"""Recipe-to-ERP purchase demand. No schema changes, commits or permission bypasses."""
from __future__ import annotations

import hashlib
import json
import math

import frappe
from frappe.utils import getdate, nowdate

RECIPE = "Tongjianyun Recipe"
TRACE = "Tongjianyun Food Purchase"
KIND = "erp_recipe_request"
SLOTS = {"breakfast": "breakfast", "morningSnack": "morning_snack", "lunch": "lunch",
         "snack": "afternoon_snack", "dinner": "dinner"}
UNITS = {"g": ("mass", 1), "克": ("mass", 1), "kg": ("mass", 1000),
         "千克": ("mass", 1000), "公斤": ("mass", 1000), "gram": ("mass", 1),
         "ml": ("volume", 1), "毫升": ("volume", 1), "l": ("volume", 1000),
         "升": ("volume", 1000), "liter": ("volume", 1000), "litre": ("volume", 1000),
         "millilitre": ("volume", 1)}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def number(value, *, zero=False, integer=False):
    result = float(value)
    if not math.isfinite(result) or result < 0 or (not zero and result == 0):
        raise ValueError("数值必须是有限的正数（人数允许为零）。")
    if integer and not result.is_integer():
        raise ValueError("人数必须是整数。")
    return result


def conversion(source, target):
    source, target = source.strip().lower(), target.strip().lower()
    if source == target and source:
        return 1.0
    a, b = UNITS.get(source), UNITS.get(target)
    return a[1] / b[1] if a and b and a[0] == b[0] else None


def _read(doctype, name):
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")
    return doc


def _permission(doctype, action):
    if frappe.session.user == "Guest" or not frappe.has_permission(doctype, ptype=action):
        frappe.throw(f"没有 {doctype} 的 {action} 权限。", frappe.PermissionError)


def _payload(value):
    return frappe.parse_json(value) if isinstance(value, str) else value


def _source(recipe):
    doc = _read(RECIPE, recipe)
    if doc.is_deleted or doc.workflow_status != "已发布":
        frappe.throw("请先发布食谱，再准备采购需求。")
    dishes = frappe.get_list("Tongjianyun Recipe Dish", filters={"recipe": recipe},
                            fields=["name", "meal_date", "meal_slot"], limit_page_length=0)
    ingredients = frappe.get_list("Tongjianyun Recipe Ingredient", filters={"recipe": recipe},
        fields=["name", "recipe_dish", "ingredient_name", "amount", "unit"], limit_page_length=0)
    # Reject partial row visibility rather than silently producing an incomplete requirement.
    if len(dishes) != frappe.db.count("Tongjianyun Recipe Dish", {"recipe": recipe}) or len(ingredients) != frappe.db.count("Tongjianyun Recipe Ingredient", {"recipe": recipe}):
        frappe.throw("当前账号不能读取完整食谱明细。", frappe.PermissionError)
    by_dish = {d.name: d for d in dishes}
    rows = []
    for ingredient in ingredients:
        dish = by_dish.get(ingredient.recipe_dish)
        if not dish or not dish.meal_date or dish.meal_slot not in SLOTS:
            frappe.throw("食谱存在缺少日期或餐次的食材，需先修正食谱。")
        row = dict(ingredient)
        row.update(date=str(dish.meal_date), slot=dish.meal_slot)
        row["key"] = digest([row["ingredient_name"], row["unit"]])[:24]
        rows.append(row)
    rows.sort(key=lambda r: r["name"])
    if not rows:
        frappe.throw("食谱没有食材明细。")
    return doc, rows


@frappe.whitelist()
def prepare(recipe, company):
    _permission("Item", "read")
    _permission(TRACE, "read")
    _read("Company", company)
    doc, rows = _source(recipe)
    remembered = {}
    for entry in frappe.get_list(TRACE, filters={"record_type": ["in", [KIND, "erp_recipe_mapping"]]}, fields=["name"],
                                order_by="creation desc", limit_page_length=100):
        trace = _read(TRACE, entry.name)
        data = json.loads(trace.record_json)
        if data.get("company") == company:
            for key, mapping in data.get("mappings", {}).items():
                remembered.setdefault(key, mapping)
    # Automatic matches are unit conversions only; explicit human/company mappings win.
    from tongjianyun.recipe_item_sync import KIND as AUTO_KIND
    auto_key = AUTO_KIND + "::" + digest(recipe)[:32]
    if frappe.db.exists(TRACE, auto_key):
        auto_data = json.loads(_read(TRACE, auto_key).record_json)
        for key, mapping in auto_data.get("mappings", {}).items():
            remembered.setdefault(key, {**mapping, "automatic": True})
    ingredients = {}
    meals = {}
    for row in rows:
        key = row["key"]
        if key not in ingredients:
            mapping = remembered.get(key, {})
            candidates = frappe.get_list("Item", filters={"item_name": row["ingredient_name"],
                "disabled": 0, "is_purchase_item": 1, "is_stock_item": 1, "has_variants": 0},
                fields=["name", "stock_uom"], limit_page_length=2)
            item_code = mapping.get("item_code") or (candidates[0].name if len(candidates) == 1 else "")
            unit, factor = "", None
            if item_code and frappe.has_permission("Item", "read", item_code):
                item = _read("Item", item_code)
                if not item.disabled and item.is_purchase_item and not item.has_variants:
                    unit = item.stock_uom
                    factor = mapping.get("factor") if mapping.get("uom") == unit else conversion(row["unit"], unit)
                else:
                    item_code = ""
            else:
                item_code = ""
            ingredients[key] = {"key": key, "ingredient": row["ingredient_name"], "source_uom": row["unit"],
                "item_code": item_code, "uom": unit, "factor": factor,
                "basis": "自动匹配，需核对毛料系数" if mapping.get("automatic") and item_code else "历史确认" if mapping and item_code else "同名候选，需核对" if item_code else "待匹配"}
            if unit and not frappe.db.exists("UOM", unit):
                ingredients[key]["basis"] = "库存单位不存在，需管理员修复"
        meal_key = row["date"] + ":" + row["slot"]
        meals[meal_key] = {"key": meal_key, "date": row["date"], "slot": row["slot"], "count": None, "basis": "请输入预计备餐人数"}
    # Only confirmed, readable daily records are hints; users explicitly review meal scope.
    if frappe.has_permission("Tongjianyun Daily Meal Confirmation", "read"):
        for meal in meals.values():
            found = frappe.get_list("Tongjianyun Daily Meal Confirmation", filters={"meal_date": meal["date"],
                "status": ["in", ["已确认", "已锁定"]]}, fields=["name"], limit_page_length=1)
            if found:
                confirmation = _read("Tongjianyun Daily Meal Confirmation", found[0].name)
                meal["count"] = confirmation.get("total_" + SLOTS[meal["slot"]] + "_count")
                meal["basis"] = "全园已确认人数，请核对本食谱适用范围"
    from tongjianyun.ingredient_resolution import suggestions
    return {"recipe": doc.name, "revision": digest(rows), "ingredients": suggestions(list(ingredients.values())),
            "meals": sorted(meals.values(), key=lambda r: r["key"])}


def _plan(recipe, company, warehouse, mappings, meals):
    _read("Company", company)
    wh = _read("Warehouse", warehouse)
    if wh.company != company or wh.is_group or wh.disabled:
        frappe.throw("请选择所属公司的有效明细仓库。")
    doc, source = _source(recipe)
    mappings, meals = _payload(mappings), _payload(meals)
    if not isinstance(mappings, dict) or not isinstance(meals, dict):
        frappe.throw("食材匹配和分餐人数格式无效，请重新打开采购预览。")
    lines, checked = {}, {}
    for row in source:
        mapping = mappings.get(row["key"], {})
        if not isinstance(mapping, dict) or not mapping.get("item_code"):
            frappe.throw("存在未匹配的食材，请先选择物料。")
        item = _read("Item", mapping["item_code"])
        if item.disabled or not item.is_purchase_item or item.has_variants or not item.is_stock_item:
            frappe.throw("食材必须关联启用的、可采购的库存物料，且不能是变体模板。")
        if mapping.get("uom") != item.stock_uom:
            frappe.throw("物料库存单位已变化，请重新匹配。")
        if not frappe.db.exists("UOM", item.stock_uom):
            frappe.throw(f"物料 {item.name} 引用的库存单位 {item.stock_uom} 不存在，请管理员先修复基础数据。")
        try:
            factor = number(mapping.get("factor"))
            count = number(meals.get(row["date"] + ":" + row["slot"]), zero=True, integer=True)
            amount = number(row["amount"], zero=True)
            number(amount * count * factor, zero=True)
        except (ValueError, TypeError, OverflowError):
            frappe.throw("请完整填写非负整数人数、正数换算系数，并核对食谱用量；不接受无效或无限大数值。")
        if getdate(row["date"]) < getdate(nowdate()):
            frappe.throw("食谱含过去日期，不能按过去日期新建采购需求；请使用当前或未来食谱。")
        checked[row["key"]] = {"item_code": item.name, "uom": item.stock_uom, "factor": factor}
        key = (row["date"], item.name)
        line = lines.setdefault(key, {"schedule_date": row["date"], "item_code": item.name,
            "item_name": item.item_name, "uom": item.stock_uom, "qty": 0.0, "warehouse": warehouse})
        line["qty"] += amount * count * factor
    result = [dict(line, qty=round(line["qty"], 6)) for _, line in sorted(lines.items()) if line["qty"] > 0]
    if not result or any(line["qty"] <= 0 for line in result):
        frappe.throw("需求为空或小于支持精度，请核对人数、用量与换算。")
    for line in result:
        uom = _read("UOM", line["uom"])
        if uom.must_be_whole_number and not float(line["qty"]).is_integer():
            frappe.throw("库存单位要求整数数量，请核对包装规格和换算，不能自动取整改变需求。")
    plan = {"recipe": doc.name, "company": company, "warehouse": warehouse,
            "revision": digest(source), "mappings": checked, "meals": meals, "lines": result}
    plan["token"] = digest(plan)
    return plan


@frappe.whitelist()
def preview(recipe, company, warehouse, mappings, meals):
    _permission("Material Request", "create")
    _permission(TRACE, "create")
    return _plan(recipe, company, warehouse, mappings, meals)


@frappe.whitelist(methods=["POST"])
def create_request(recipe, company, warehouse, mappings, meals, token, confirmed=0):
    if str(confirmed) != "1":
        frappe.throw("请明确确认物料、备餐人数及采购毛料换算。")
    _permission("Material Request", "create")
    _permission(TRACE, "create")
    _permission(TRACE, "write")
    _permission(TRACE, "read")
    plan = _plan(recipe, company, warehouse, mappings, meals)
    if token != plan["token"]:
        frappe.throw("食谱或参数已变化，请重新预览。")
    trace_key = KIND + "::" + digest([recipe, company])[:32]
    # A transaction-scoped unique trace also protects against double-clicks and concurrent requests.
    if frappe.db.exists(TRACE, trace_key):
        existing = _read(TRACE, trace_key)
        saved = json.loads(existing.record_json)
        mr = _read("Material Request", saved["material_request"])
        if saved["token"] != token:
            frappe.throw("此食谱已生成采购需求。请先核对原单及修订方案，系统不会重复采购或覆盖原单。")
        return {"name": mr.name, "existing": True}
    trace = frappe.get_doc({"doctype": TRACE, "data_key": trace_key, "record_type": KIND,
        "record_id": plan["token"], "title": "食谱采购需求 · " + recipe,
        "status": "草稿", "parent_id": recipe, "source": "ERPNext Material Request",
        "record_json": json.dumps(plan, ensure_ascii=False)})
    trace.insert()
    request = frappe.get_doc({"doctype": "Material Request", "material_request_type": "Purchase",
        "company": company, "transaction_date": nowdate(), "set_warehouse": warehouse,
        "items": plan["lines"]})
    request.insert()
    plan["material_request"] = request.name
    trace.record_json = json.dumps(plan, ensure_ascii=False)
    trace.save()
    return {"name": request.name, "existing": False}
