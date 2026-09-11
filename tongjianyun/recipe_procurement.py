"""Recipe-to-ERP purchase demand. No schema changes, commits or permission bypasses."""
from __future__ import annotations

import hashlib
import json
import math
from html import escape

import frappe
import frappe.defaults
from tongjianyun.procurement_precision import apply_precision, new_target
from frappe.utils import flt, getdate, nowdate

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


def _doctype_available(doctype):
    """Check registered metadata, not just a table left by a retired DocType."""
    try:
        return bool(frappe.db.exists("DocType", doctype))
    except Exception:
        return False


def _trace_available():
    return _doctype_available(TRACE)


def checked_quantity(row, mapping, meals):
    ingredient = escape(str(row['ingredient_name']))
    context = escape(str(row['date']) + ' ' + str(row['slot']))
    try:
        factor = number(mapping.get('factor'))
    except (ValueError, TypeError, OverflowError):
        frappe.throw(f"{ingredient}：食谱单位为 {escape(str(row.get('unit') or '未填写'))}，物料库存单位为 {escape(str(mapping.get('uom') or '未填写'))}，缺少有效换算关系。请确认自制/外购及每份含量；这不是备餐人数问题。")
    try:
        count = number(meals.get(row['date'] + ':' + row['slot']), zero=True, integer=True)
    except (ValueError, TypeError, OverflowError):
        frappe.throw(f"{context}：备餐人数未填写或不是非负整数，请核对该餐次人数。")
    try:
        amount = number(row['amount'], zero=True)
    except (ValueError, TypeError, OverflowError):
        frappe.throw(f"{context} {ingredient}：食谱用量无效，请修正为非负数。")
    try:
        number(amount * count * factor, zero=True)
    except (ValueError, TypeError, OverflowError):
        frappe.throw(f"{context} {ingredient}：计算结果超出有效范围，请核对用量、人数和单位。")
    return factor, count, amount


def _read(doctype, name):
    doc = frappe.get_doc(doctype, name)
    doc.check_permission("read")
    return doc


def _permission(doctype, action):
    if frappe.session.user == "Guest" or not frappe.has_permission(doctype, ptype=action):
        frappe.throw(f"没有 {doctype} 的 {action} 权限。", frappe.PermissionError)


def _payload(value):
    return frappe.parse_json(value) if isinstance(value, str) else value


def _source(recipe, allow_draft=False):
    doc = _read(RECIPE, recipe)
    if doc.is_deleted or (doc.workflow_status != "已发布" and not (allow_draft and doc.workflow_status == "草稿")):
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
def default_scope(recipe):
    """Use ERPNext defaults without offering arbitrary companies or warehouses."""
    _permission("Material Request", "create")
    _read(RECIPE, recipe)
    company = frappe.defaults.get_user_default("company") or frappe.defaults.get_global_default("company")
    if not company:
        frappe.throw("尚未配置默认公司，请联系管理员设置 ERPNext 默认公司。")
    company_doc = _read("Company", company)
    warehouse = company_doc.default_warehouse
    if not warehouse:
        frappe.throw("默认公司尚未配置收货仓库，请联系管理员设置公司的默认仓库。")
    wh = _read("Warehouse", warehouse)
    if wh.company != company or wh.is_group or wh.disabled:
        frappe.throw("默认仓库不可用或不属于默认公司，请联系管理员修正配置。")
    return {"company": company, "warehouse": warehouse}


def _default_buying_price_list():
    price_list = (
        frappe.defaults.get_user_default("buying_price_list")
        or frappe.defaults.get_global_default("buying_price_list")
        or frappe.db.get_single_value("Buying Settings", "buying_price_list")
    )
    if not price_list:
        frappe.throw("尚未配置默认采购价格表，请联系管理员设置 ERPNext Buying Settings。")
    row = frappe.db.get_value("Price List", price_list, ["enabled", "buying"], as_dict=True)
    if not row or not row.enabled or not row.buying:
        frappe.throw("默认采购价格表不可用，请联系管理员修正 ERPNext 价格表配置。")
    return price_list


def _price_key(item_code, uom):
    return digest([item_code, uom])[:24]


def _price_list_currency(price_list, company):
    return (
        frappe.db.get_value("Price List", price_list, "currency")
        or frappe.db.get_value("Company", company, "default_currency")
        or "CNY"
    )


def _current_buying_price(item_code, price_list, uom):
    """Read the effective buying price used by Tongjianyun's one-click flow."""
    today = getdate(nowdate())
    rows = frappe.get_all(
        "Item Price",
        filters={"item_code": item_code, "price_list": price_list, "buying": 1},
        fields=["name", "price_list_rate", "uom", "valid_from", "valid_upto"],
        order_by="valid_from desc, modified desc, creation desc",
        limit_page_length=50,
    )
    candidates = []
    for row in rows:
        if row.uom and row.uom != uom:
            continue
        if row.valid_from and getdate(row.valid_from) > today:
            continue
        if row.valid_upto and getdate(row.valid_upto) < today:
            continue
        rate = float(row.price_list_rate or 0)
        # A blank Item Price UOM means the stock UOM, not the requested quote UOM.
        if not row.uom:
            stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
            factor = conversion(uom, stock_uom) if stock_uom else None
            if not factor:
                continue
            rate *= factor
        if rate > 0:
            candidates.append((0 if row.uom == uom else 1, rate))
    if not candidates:
        stock_uom = frappe.db.get_value("Item", item_code, "stock_uom")
        factor = conversion(uom, stock_uom) if stock_uom else None
        if stock_uom != uom and factor:
            return _current_buying_price(item_code, price_list, stock_uom) * factor
        return 0.0
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _plan_price_index(plan):
    index = {}
    for line in plan["lines"]:
        key = _price_key(line["item_code"], line["uom"])
        index.setdefault(key, {"item_code": line["item_code"], "item_name": line["item_name"], "uom": line["uom"]})
    return index


def _purchase_rate_precision(plan):
    """Read the existing ERPNext precision across the entire document chain."""
    from frappe.model.meta import get_field_precision

    currency = _price_list_currency(plan["buying_price_list"], plan["company"])
    return min(
        get_field_precision(frappe.get_meta(doctype).get_field("rate"), currency=currency)
        for doctype in (
            "Material Request Item", "Purchase Order Item",
            "Purchase Receipt Item", "Purchase Invoice Item",
        )
    )


def _attach_line_prices(plan):
    plan["price_precision"] = _purchase_rate_precision(plan)
    plan["price_currency"] = _price_list_currency(plan["buying_price_list"], plan["company"])
    for line in plan["lines"]:
        price_key = _price_key(line["item_code"], line["uom"])
        rate = _current_buying_price(line["item_code"], plan["buying_price_list"], line["uom"])
        line["price_key"] = price_key
        line["unit_price"] = rate
        line["amount"] = round(float(line["qty"] or 0) * rate, 6) if rate > 0 else 0
    return plan


def _apply_plan_rates(plan):
    for line in plan["lines"]:
        rate = _current_buying_price(line["item_code"], plan["buying_price_list"], line["uom"])
        if rate > 0:
            line["price_list_rate"] = rate
            line["rate"] = rate
            line["amount"] = round(float(line["qty"] or 0) * rate, 6)
    return plan


def _generic_item_price(item_code, price_list, uom):
    rows = frappe.get_all(
        "Item Price",
        filters={"item_code": item_code, "price_list": price_list, "buying": 1, "uom": uom},
        fields=["name"],
        order_by="modified desc, creation desc",
        limit_page_length=20,
    )
    for row in rows:
        doc = frappe.get_doc("Item Price", row.name)
        if not doc.get("supplier"):
            return doc
    return None


def _upsert_buying_prices(plan, prices):
    prices = _payload(prices or {})
    if not prices:
        return {"created": 0, "updated": 0, "unchanged": 0}
    if not isinstance(prices, dict):
        frappe.throw("采购单价格式无效，请重新打开采购清单。")

    _permission("Item Price", "read")
    _permission("Item Price", "create")
    _permission("Item Price", "write")
    price_index = _plan_price_index(plan)
    currency = _price_list_currency(plan["buying_price_list"], plan["company"])
    created = updated = unchanged = 0
    for key, raw_price in prices.items():
        key = str(key)
        if key not in price_index:
            frappe.throw("采购单价与当前清单不匹配，请重新预览。")
        try:
            rate = number(raw_price)
        except (TypeError, ValueError, OverflowError):
            frappe.throw(f"{escape(price_index[key]['item_name'])}：采购单价必须是正数。")
        row = price_index[key]
        item_price = _generic_item_price(row["item_code"], plan["buying_price_list"], row["uom"])
        if item_price:
            item_price.check_permission("write")
            if float(item_price.price_list_rate or 0) == rate and item_price.currency == currency:
                unchanged += 1
                continue
            item_price.price_list_rate = rate
            item_price.currency = currency
            item_price.save()
            updated += 1
        else:
            doc = frappe.get_doc({
                "doctype": "Item Price",
                "item_code": row["item_code"],
                "price_list": plan["buying_price_list"],
                "price_list_rate": rate,
                "currency": currency,
                "uom": row["uom"],
                "buying": 1,
                "selling": 0,
            })
            doc.insert()
            created += 1
    return {"created": created, "updated": updated, "unchanged": unchanged}


def _validate_plan_prices(plan, prices=None):
    supplied = _payload(prices or {})
    if not isinstance(supplied, dict):
        frappe.throw("采购单价格式无效，请重新打开采购清单。")
    precision = _purchase_rate_precision(plan)
    missing = []
    for key, row in _plan_price_index(plan).items():
        raw_rate = supplied.get(key) if key in supplied else _current_buying_price(
            row["item_code"], plan["buying_price_list"], row["uom"]
        )
        try:
            rate = number(raw_rate)
        except (TypeError, ValueError, OverflowError):
            missing.append(row["item_name"])
            continue
        if flt(rate, precision) <= 0:
            frappe.throw(
                f"{escape(row['item_name'])}：单价 {rate:g} / {escape(row['uom'])} 过小，"
                f"当前采购单据保留 {precision} 位小数，会被舍入为 0。"
                "请在采购清单核对单价及计价单位后重试；本次未新建采购、收货、发票或付款单据。"
            )
        if not math.isclose(rate, flt(rate, precision), rel_tol=0, abs_tol=1e-9):
            frappe.throw(f"{escape(row['item_name'])}：当前计价单位 {escape(row['uom'])} 的单价超出 {precision} 位小数，请核对价格后再结算；不会自动抬高或压低单价。")
    if missing:
        frappe.throw(
            "请在确认采购清单中补齐采购单价："
            + "、".join(escape(name) for name in missing[:12])
            + (" 等" if len(missing) > 12 else "")
        )


@frappe.whitelist()
def prepare(recipe, company, allow_draft=False):
    _permission("Item", "read")
    trace_available = _trace_available()
    if trace_available:
        _permission(TRACE, "read")
    _read("Company", company)
    doc, rows = _source(recipe, allow_draft=allow_draft)
    remembered = {}
    if trace_available:
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
    if trace_available and frappe.db.exists(TRACE, auto_key):
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
    # Student-level plans may be used for purchasing, but remain explicitly estimates.
    from tongjianyun.student_meals import procurement_counts
    planned_by_day = {}
    for meal in meals.values():
        if meal["count"] is None:
            if meal["date"] not in planned_by_day:
                planned_by_day[meal["date"]] = procurement_counts(meal["date"])
            planned = planned_by_day[meal["date"]]
            if planned is not None:
                meal["count"] = planned[SLOTS[meal["slot"]] + "_count"]
                meal["basis"] = "各班学生就餐安排汇总（未全部实际确认，采购预计参考）"
    from tongjianyun.ingredient_resolution import suggestions
    return {"recipe": doc.name, "revision": digest(rows), "as_of_date": nowdate(), "ingredients": suggestions(list(ingredients.values())),
            "meals": sorted(meals.values(), key=lambda r: r["key"])}


@frappe.whitelist(methods=["POST"])
def auto_match_items(recipe):
    """Procurement reuses the audited Codex sync, never a second Item creator."""
    _permission("Material Request", "create")
    _source(recipe)
    from tongjianyun.recipe_item_sync import get_sync_status, schedule_after_save
    state = get_sync_status(recipe)
    if state.get("status") in ("queued", "running"):
        return state
    return schedule_after_save(recipe)


def _plan(recipe, company, warehouse, mappings, meals, include_history=0, allow_draft=False):
    if str(include_history) not in ("0", "1"):
        frappe.throw("历史补录选项无效，请重新预览。")
    include_history = str(include_history) == "1"
    today = getdate(nowdate())
    _read("Company", company)
    wh = _read("Warehouse", warehouse)
    if wh.company != company or wh.is_group or wh.disabled:
        frappe.throw("请选择所属公司的有效明细仓库。")
    buying_price_list = _default_buying_price_list()
    doc, source = _source(recipe, allow_draft=allow_draft)
    mappings, meals = _payload(mappings), _payload(meals)
    if not isinstance(mappings, dict) or not isinstance(meals, dict):
        frappe.throw("食材匹配和分餐人数格式无效，请重新打开采购预览。")
    lines, checked = {}, {}
    excluded_dates = set()
    for row in source:
        if getdate(row["date"]) < today and not include_history:
            excluded_dates.add(row["date"])
            continue
        from tongjianyun.recipe_product_decisions import read_decision
        from tongjianyun.ingredient_resolution import requires_product_confirmation
        if requires_product_confirmation(row["ingredient_name"]):
            decision = read_decision(recipe, row)
            if decision and decision.get("mode") in ("自制", "暂时跳过"):
                frappe.throw("存在自制配方待办或暂时跳过的食材，不能生成完整采购需求。请先处理：" + row["ingredient_name"])
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
        factor, count, amount = checked_quantity(row, mapping, meals)
        checked[row["key"]] = {"item_code": item.name, "uom": item.stock_uom, "factor": factor}
        key = (row["date"], item.name)
        line = lines.setdefault(key, {"schedule_date": row["date"], "item_code": item.name,
            "item_name": item.item_name, "uom": item.stock_uom, "qty": 0.0, "warehouse": warehouse})
        line["qty"] += amount * count * factor
    result = [dict(line, qty=round(line["qty"], 6)) for _, line in sorted(lines.items()) if line["qty"] > 0]
    if not result and excluded_dates:
        frappe.throw("今天及之后没有有效采购需求。若需补录过去的需求，请勾选“包含过去日期（历史补录）”后重新预览。")
    if not result or any(line["qty"] <= 0 for line in result):
        frappe.throw("需求为空或小于支持精度，请核对人数、用量与换算。")
    for line in result:
        uom = _read("UOM", line["uom"])
        if uom.must_be_whole_number and not float(line["qty"]).is_integer():
            frappe.throw("库存单位要求整数数量，请核对包装规格和换算，不能自动取整改变需求。")
    _normalize_purchase_units(result)
    historical_dates = sorted({line["schedule_date"] for line in result if getdate(line["schedule_date"]) < today})
    for line in result:
        if line["schedule_date"] in historical_dates:
            line["description"] = f"历史需求补录；原用餐日期：{line['schedule_date']}。不代表已采购、已入库或已付款，请勿重复采购。"
    # ERPNext requires required-by dates >= transaction_date. The preview
    # explicitly discloses backdating; original meal dates remain unchanged.
    transaction_date = historical_dates[0] if historical_dates else today.isoformat()
    plan = {"recipe": doc.name, "company": company, "warehouse": warehouse,
            "include_history": int(include_history), "as_of_date": today.isoformat(),
            "historical_dates": historical_dates, "excluded_dates": sorted(excluded_dates),
            "transaction_date": transaction_date, "buying_price_list": buying_price_list,
            "revision": digest(source), "mappings": checked, "meals": meals, "lines": result}
    plan["token"] = digest(plan)
    return plan


def _normalize_purchase_units(lines):
    """Keep recipe/stock units; quote mass and volume per kg/l without rounding up prices."""
    for line in lines:
        unit = UNITS.get(line["uom"].strip().lower())
        if not unit or unit[1] != 1:
            continue
        candidates = ("Kg", "kg", "Kilogram") if unit[0] == "mass" else ("Litre", "Liter", "L")
        target = next((u for u in candidates if frappe.db.exists("UOM", u)), None)
        if not target:
            frappe.throw("缺少公斤或升计价单位，请管理员维护现有单位后重试。")
        line.update(stock_uom=line["uom"], stock_qty=line["qty"],
                    uom=target, conversion_factor=1000, qty=line["qty"] / 1000)


@frappe.whitelist()
def preview(recipe, company, warehouse, mappings, meals, include_history=0):
    _permission("Material Request", "create")
    plan = _plan(recipe, company, warehouse, mappings, meals, include_history)
    return _attach_line_prices(plan)


@frappe.whitelist()
def revision_impact(recipe):
    """Read-only warning for existing requests; never revise submitted documents."""
    doc = _read(RECIPE, recipe)
    _permission("Material Request", "read")
    current_revision = None
    if not doc.is_deleted and doc.workflow_status == "已发布":
        _, rows = _source(recipe)
        current_revision = digest(rows)
    if not _trace_available():
        return {
            "requests": [],
            "message": "采购需求已改用 ERPNext 标准物料需求和采购订单；当前食谱没有旧采购追踪记录。",
        }
    _permission(TRACE, "read")
    output = []
    for row in frappe.get_list(TRACE, filters={"parent_id": recipe, "record_type": KIND},
            fields=["name"], limit_page_length=0):
        saved = json.loads(_read(TRACE, row.name).record_json)
        request = _read("Material Request", saved["material_request"])
        output.append({"name": request.name, "docstatus": request.docstatus,
            "changed": current_revision is None or current_revision != saved.get("revision")})
    return {"requests": output, "message": "食谱修改不会覆盖原采购需求、订单或库存。发现差异后请核对原单并走修订流程。"}


@frappe.whitelist(methods=["POST"])
def create_request(recipe, company, warehouse, mappings, meals, token, confirmed=0, include_history=0):
    if str(confirmed) != "1":
        frappe.throw("请明确确认物料、备餐人数及采购毛料换算。")
    _permission("Material Request", "create")
    _read(RECIPE, recipe)
    frappe.db.get_value(RECIPE, recipe, "name", for_update=True)
    plan = _plan(recipe, company, warehouse, mappings, meals, include_history)
    if token != plan["token"]:
        frappe.throw("食谱或参数已变化，请重新预览。")
    _apply_plan_rates(plan)
    trace_available = _trace_available()
    trace_key = KIND + "::" + digest([recipe, company])[:32]
    # Retain the old idempotency trace only on sites that still have its DocType.
    if trace_available:
        _permission(TRACE, "create")
        _permission(TRACE, "write")
        _permission(TRACE, "read")
        if frappe.db.exists(TRACE, trace_key):
            existing = _read(TRACE, trace_key)
            saved = json.loads(existing.record_json)
            mr = _read("Material Request", saved["material_request"])
            if saved["token"] != token:
                frappe.throw("此食谱已生成采购需求。请先核对原单及修订方案，系统不会重复采购或覆盖原单。")
            return {"name": mr.name, "existing": True}
    title = "童健云食谱采购 · " + recipe
    if not trace_available:
        existing_rows = frappe.get_list(
            "Material Request",
            filters={
                "title": title,
                "company": company,
                "material_request_type": "Purchase",
                "docstatus": ["<", 2],
            },
            fields=["name"],
            limit_page_length=1,
        )
        if existing_rows:
            return {"name": existing_rows[0].name, "existing": True}
    request = frappe.get_doc({"doctype": "Material Request", "title": title, "material_request_type": "Purchase",
        "company": company, "transaction_date": plan["transaction_date"], "set_warehouse": warehouse,
        "buying_price_list": plan["buying_price_list"], "items": plan["lines"]})
    request.insert()
    if trace_available:
        plan["material_request"] = request.name
        trace = frappe.get_doc({"doctype": TRACE, "data_key": trace_key, "record_type": KIND,
            "record_id": plan["token"], "title": title,
            "status": "草稿", "parent_id": recipe, "source": "ERPNext Material Request",
            "record_json": json.dumps(plan, ensure_ascii=False)})
        trace.insert()
    return {"name": request.name, "existing": False}


def _daily_order_groups(request, rows):
    """Use source demand dates, never the mapper's rescheduled delivery dates."""
    source_dates = {item.name: item.schedule_date for item in request.items}
    grouped = {}
    for row in rows:
        source_date = source_dates.get(row["material_request_item"])
        if not source_date:
            frappe.throw("物料需求明细缺少原始日期，请先核对，不能自动合并采购。")
        key = (getdate(source_date).isoformat(), row["supplier"])
        grouped.setdefault(key, {})[row["material_request_item"]] = row["qty"]
    return grouped


def _active_purchase_orders(name):
    """Return non-cancelled purchase orders linked to a material request."""
    linked = frappe.get_all(
        "Purchase Order Item",
        filters={"material_request": name},
        fields=["parent"],
        limit_page_length=0,
    )
    orders = []
    for order_name in sorted({row.parent for row in linked if row.parent}):
        order = _read("Purchase Order", order_name)
        if order.docstatus != 2:
            orders.append(order)
    return orders


def _create_purchase_orders(name):
    """Submit demand and map daily draft orders using ERPNext."""
    from erpnext.stock.doctype.material_request.mapper import (
        get_item_default_suppliers, make_purchase_order,
    )
    _permission("Purchase Order", "create")
    request = _read("Material Request", name)
    # Serialize all automated continuations for this request, including retries.
    frappe.db.get_value("Material Request", name, "name", for_update=True)
    request.reload()
    if request.docstatus == 2 or request.material_request_type != "Purchase":
        frappe.throw("仅能处理未取消的采购物料需求。")
    # A retry may arrive after another worker has already created the orders.
    # Re-check while holding the request lock so concurrent clicks cannot
    # create a second set of purchase orders.
    existing = _active_purchase_orders(name)
    if existing:
        return [order.name for order in existing]
    fallback = frappe.defaults.get_global_default("tongjianyun_supplier::" + request.company)
    rows = get_item_default_suppliers(name)
    if not rows:
        frappe.throw("该需求已无待采购数量，请核对已有订单或收货记录。")
    for row in rows:
        row["supplier"] = row.get("supplier") or fallback
        if not row["supplier"]:
            frappe.throw("尚未配置食材默认供应商，请联系管理员。")
        supplier = _read("Supplier", row["supplier"])
        if supplier.disabled:
            frappe.throw("默认供应商已停用，请联系管理员。")
        row["qty"] = row["pending_qty"]
    grouped = _daily_order_groups(request, rows)
    if request.docstatus == 0:
        request.check_permission("submit")
        request.submit()
    orders = []
    source_rates = {row.name: float(row.rate or 0) for row in request.items}
    for (recipe_date, supplier), quantities in sorted(grouped.items()):
        order = make_purchase_order(name, target_doc=new_target("Purchase Order"), args={"supplier": supplier,
            "filtered_children": list(quantities), "requested_qty": quantities})
        apply_precision(order)
        order.buying_price_list = request.buying_price_list or _default_buying_price_list()
        # ERPNext clears past dates; normalize both retained and rescheduled dates
        # before its min(schedule_date) validation (date/string mix otherwise fails).
        for item in order.items:
            item.schedule_date = getdate(item.schedule_date or nowdate())
            item.description = f"食谱日期：{recipe_date}<br>" + (item.description or "")
            source_rate = source_rates.get(item.material_request_item)
            if source_rate is not None:
                item.price_list_rate = source_rate
                item.rate = source_rate
        order.title = f"{recipe_date} · {order.supplier_name or supplier}"
        order.run_method("set_missing_values")
        order.run_method("calculate_taxes_and_totals")
        order.insert()
        orders.append(order.name)
    return orders


def complete_purchase_request(name):
    """Create daily purchase-order drafts without submitting them."""
    existing = _active_purchase_orders(name)
    if existing:
        return {"name": name, "purchase_orders": [order.name for order in existing], "existing": True}
    orders = _create_purchase_orders(name)
    return {"name": name, "purchase_orders": orders, "existing": False}


def _submit_if_draft(doc):
    """Submit a document once while preserving ERPNext permissions and hooks."""
    if doc.docstatus == 2:
        frappe.throw(f"{doc.doctype} {doc.name} 已取消，不能继续自动处理。")
    if doc.docstatus == 0:
        doc.check_permission("submit")
        doc.submit()
    return doc


def _linked_active_documents(child_doctype, filters, parent_doctype):
    """Find existing non-cancelled downstream documents through ERPNext child links."""
    rows = frappe.get_all(child_doctype, filters=filters, fields=["parent"], limit_page_length=0)
    documents = []
    for parent in sorted({row.parent for row in rows if row.parent}):
        doc = _read(parent_doctype, parent)
        if doc.docstatus != 2:
            documents.append(doc)
    return documents


def _ensure_purchase_receipt(order):
    """Receive all pending PO quantity, reusing or extending prior receipts."""
    from erpnext.buying.doctype.purchase_order.mapper import make_purchase_receipt

    receipts = _linked_active_documents(
        "Purchase Receipt Item",
        {"purchase_order": order.name},
        "Purchase Receipt",
    )
    for receipt in receipts:
        _submit_if_draft(receipt)

    order.reload()
    pending = any(
        float(item.qty or 0) > float(item.received_qty or 0)
        for item in order.items
    )
    if not pending:
        if receipts:
            return receipts[-1]
        frappe.throw(f"采购订单 {order.name} 没有待收货数量，无法自动入库。")

    receipt = make_purchase_receipt(order.name, target_doc=new_target("Purchase Receipt"))
    apply_precision(receipt)
    if not receipt.items:
        frappe.throw(f"采购订单 {order.name} 没有可收货明细，无法自动入库。")
    receipt.posting_date = nowdate()
    receipt.insert()
    receipt.submit()
    return receipt


def _ensure_purchase_invoice(order):
    """Create an invoice for all unbilled PO quantity without double billing."""
    from erpnext.buying.doctype.purchase_order.mapper import make_purchase_invoice

    invoices = _linked_active_documents(
        "Purchase Invoice Item",
        {"purchase_order": order.name},
        "Purchase Invoice",
    )
    for invoice in invoices:
        _submit_if_draft(invoice)

    order.reload()
    if float(order.per_billed or 0) >= 100:
        if invoices:
            return invoices[-1]
        frappe.throw(f"采购订单 {order.name} 已全部开票，但未找到关联采购发票。")

    invoice = make_purchase_invoice(order.name, target_doc=new_target("Purchase Invoice"))
    apply_precision(invoice)
    if not invoice.items:
        frappe.throw(f"采购订单 {order.name} 没有可开票明细，无法自动开票。")
    if any(float(item.qty or 0) > 0 and float(item.rate or 0) <= 0 for item in invoice.items):
        frappe.throw(
            f"采购订单 {order.name} 尚未配置有效采购价，无法自动开票和付款。"
            "请返回童健云采购清单直接填写单价，系统会自动保存到 ERPNext 默认采购价格表。"
        )
    # Stock was already updated by Purchase Receipt. Never duplicate it from the invoice.
    invoice.update_stock = 0
    invoice.posting_date = nowdate()
    invoice.bill_date = nowdate()
    invoice.insert()
    invoice.submit()
    return invoice


def _ensure_payment_entry(invoice):
    """Pay the invoice once using ERPNext's configured default bank or cash account."""
    from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

    payments = _linked_active_documents(
        "Payment Entry Reference",
        {
            "reference_doctype": "Purchase Invoice",
            "reference_name": invoice.name,
            "parenttype": "Payment Entry",
        },
        "Payment Entry",
    )
    for payment in payments:
        _submit_if_draft(payment)
    if payments:
        return payments[-1]

    invoice.reload()
    if float(invoice.outstanding_amount or 0) <= 0:
        return None

    payment = get_payment_entry("Purchase Invoice", invoice.name)
    payment.insert()
    payment.submit()
    return payment


def complete_purchase_cycle(name, progress=None):
    """Run the complete one-click ERPNext procurement cycle in one transaction."""
    request = _read("Material Request", name)
    required_permissions = [
        ("Purchase Order", "create"),
        ("Purchase Order", "submit"),
        ("Purchase Receipt", "create"),
        ("Purchase Receipt", "submit"),
        ("Purchase Invoice", "create"),
        ("Purchase Invoice", "submit"),
        ("Payment Entry", "create"),
        ("Payment Entry", "submit"),
    ]
    if request.docstatus == 0:
        required_permissions.insert(0, ("Material Request", "submit"))
    for doctype, action in required_permissions:
        _permission(doctype, action)

    frappe.db.get_value("Material Request", name, "name", for_update=True)
    request.reload()
    if request.docstatus == 2 or request.material_request_type != "Purchase":
        frappe.throw("仅能处理未取消的采购物料需求。")

    orders = _active_purchase_orders(name)
    existing = bool(orders)
    if not orders:
        orders = [_read("Purchase Order", order_name) for order_name in _create_purchase_orders(name)]

    receipts, invoices, payments = [], [], []
    for index, order in enumerate(orders):
        if progress:
            progress("orders", f"第 {index + 1}/{len(orders)} 天：提交采购订单")
        _submit_if_draft(order)
        if progress:
            progress("receipts", f"第 {index + 1}/{len(orders)} 天：登记收货")
        receipt = _ensure_purchase_receipt(order)
        if progress:
            progress("invoices", f"第 {index + 1}/{len(orders)} 天：登记采购发票")
        invoice = _ensure_purchase_invoice(order)
        if progress:
            progress("payments", f"第 {index + 1}/{len(orders)} 天：登记付款")
        payment = _ensure_payment_entry(invoice)
        invoice.reload()
        if float(invoice.outstanding_amount or 0) > 0.005:
            frappe.throw(f"采购发票 {invoice.name} 仍有未结清余额，不能标记结算完成。")
        receipts.append(receipt.name)
        invoices.append(invoice.name)
        if payment:
            payments.append(payment.name)

    return {
        "name": name,
        "existing": existing,
        "purchase_orders": [order.name for order in orders],
        "purchase_receipts": receipts,
        "purchase_invoices": invoices,
        "payment_entries": payments,
        "status": "已完成",
    }


@frappe.whitelist(methods=["POST"])
def create_purchase(recipe, company, warehouse, mappings, meals, token, confirmed=0, include_history=0, prices=None):
    """One explicit confirmation; complete the ERPNext procurement cycle."""
    if str(confirmed) != "1":
        frappe.throw("请明确确认物料、备餐人数、采购毛料换算及采购单价。")
    plan = _plan(recipe, company, warehouse, mappings, meals, include_history)
    if token != plan["token"]:
        frappe.throw("食谱或参数已变化，请重新预览。")
    # Validate the submitted rates before writing prices or creating any documents.
    _validate_plan_prices(plan, prices)
    price_result = _upsert_buying_prices(plan, prices)
    _validate_plan_prices(plan)
    result = create_request(recipe, company, warehouse, mappings, meals, token, confirmed, include_history)
    cycle = complete_purchase_cycle(result["name"])
    cycle["price_updates"] = price_result
    return cycle


@frappe.whitelist()
def weekly_purchase_orders(start_date=None, end_date=None):
    """Compact, date-grouped view for the one-week purchasing workflow."""
    _permission("Purchase Order", "read")
    start_date = getdate(start_date or nowdate())
    end_date = getdate(end_date or start_date)
    if (end_date - start_date).days > 7:
        frappe.throw("一次最多查看 7 天采购订单。")
    rows = frappe.get_list("Purchase Order", filters={"transaction_date": ["between", [start_date, end_date]], "docstatus": ["<", 2]},
        fields=["name", "supplier", "supplier_name", "transaction_date", "schedule_date", "docstatus", "grand_total"],
        order_by="transaction_date asc, creation asc", limit_page_length=100)
    for row in rows:
        row["status_label"] = "草稿" if row.docstatus == 0 else "已提交"
    return {"orders": rows, "start_date": str(start_date), "end_date": str(end_date)}


@frappe.whitelist(methods=["POST"])
def submit_weekly_purchase_orders(names):
    _permission("Purchase Order", "submit")
    names = frappe.parse_json(names) if isinstance(names, str) else names
    if not isinstance(names, list) or not names or len(names) > 7:
        frappe.throw("请选择 1 至 7 张订单。")
    result = []
    for name in names:
        order = frappe.get_doc("Purchase Order", name)
        order.check_permission("submit")
        if order.docstatus == 0:
            order.submit()
            result.append(name)
    return {"submitted": result}
