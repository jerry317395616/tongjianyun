"""Split approved meal demand once, then use native procurement documents."""

from collections import defaultdict
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe
from frappe.utils import getdate, now_datetime
from ione_core import meal_planning, meal_procurement, meal_purchasing

from tongjianyun import special_ingredients as ingredients

REQUEST, ORDER, RECEIPT = "Material Request", "Purchase Order", "Purchase Receipt"
USE = "custom_tjy_meal_purchase_use"
PLAN = "custom_tjy_purchase_nutrition_plan"
PROOF = "custom_tjy_meal_split_proof"
SPECIAL, ORDINARY = "专项", "普通"
_APPLY = ContextVar("meal_order_split", default=False)
ZERO = Decimal(0)


def install():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    frappe.only_for("System Manager")
    purpose = dict(fieldname=USE, label="采购用途", fieldtype="Select", options=f"\n{SPECIAL}\n{ORDINARY}", read_only=1)
    plan = dict(fieldname=PLAN, label="营养改善计划", fieldtype="Data", read_only=1)
    fields = {
        child: [dict(purpose, insert_after="item_code", in_list_view=1), dict(plan, insert_after=USE)]
        for child in ("Material Request Item", "Purchase Order Item", "Purchase Receipt Item")
    }
    fields[REQUEST] = [dict(fieldname=PROOF, label="食材拆分审核依据", fieldtype="Long Text",
                            read_only=1, hidden=1, insert_after="custom_meal_week")]
    fields[ORDER] = [dict(purpose, insert_after="supplier", in_standard_filter=1), dict(plan, insert_after=USE)]
    create_custom_fields({doctype: [dict(field, module="Tongjianyun") for field in rows] for doctype, rows in fields.items()})


def _enabled():
    return frappe.get_meta(REQUEST).has_field(PROOF)


def _decimal(value):
    try:
        number = Decimal(str(value if value is not None and value != "" else 0))
    except InvalidOperation:
        frappe.throw("采购数量必须是有效数字。")
    if not number.is_finite():
        frappe.throw("采购数量必须是有效数字。")
    return number


def _text(number):
    return format(number.normalize(), "f")


def _key(row):
    purchase_uom = row.get("purchase_uom") or row.get("uom")
    return (row.get("production_plan"), row.get("item_code"), str(getdate(row.get("meal_date") or row.get("schedule_date"))),
            purchase_uom)


def source_id(row):
    return meal_planning._digest(_key(row))


def _basis(source):
    approved = ingredients._approved(source)
    if not approved:
        return {}, {}
    native = (meal_planning._json(source.procurement_snapshot).get("rows", []) if source.doctype == ingredients.WEEK
              else meal_planning._json(source.applied_snapshot).get("requirements", []))
    before, purpose = {}, {}
    for row in native:
        key = _key(row)
        if key in before:
            frappe.throw("采购冻结依据包含重复的食材来源，请先核对原食谱。")
        before[key] = row
    for row in approved["rows"]:
        purpose[_key(row)] = row
    return before, purpose


def _entry(native, allocation, purchase_qty):
    required = _decimal(native["required_qty"])
    special = _decimal(allocation.get("special_qty"))
    ordinary = required - special
    factor = _decimal(native["conversion_factor"])
    if required <= 0 or factor <= 0 or not ZERO <= special <= required:
        frappe.throw("专项和普通需求的冻结数量不一致。")
    covered = sum(_decimal(native.get(field)) for field in (
        "allocated_stock_qty", "expected_receipt_qty", "already_requested_qty", "planned_surplus_used_qty",
    ))
    rounding = max(ZERO, purchase_qty * factor + covered - required)
    whole = bool(frappe.db.get_value("UOM", native["purchase_uom"], "must_be_whole_number"))
    step = Decimal(1) if whole else Decimal(1).scaleb(-meal_procurement._quantity_precision())
    suggested = purchase_qty if not ordinary else min(
        purchase_qty, (purchase_qty * special / required).quantize(step, rounding=ROUND_HALF_UP)
    )
    return {
        "key": source_id(native), "meal_date": native["meal_date"], "meal_type": native["meal_type"],
        "item_code": native["item_code"], "item_name": native["item_name"], "warehouse": native["warehouse"],
        "stock_uom": native["stock_uom"], "purchase_uom": native["purchase_uom"],
        "special_required": _text(special), "ordinary_required": _text(ordinary),
        "covered": _text(covered), "rounding_stock": _text(rounding), "purchase_qty": _text(purchase_qty),
        "suggested_special": _text(suggested), "suggested_ordinary": _text(purchase_qty - suggested),
        "review_required": bool(special and ordinary and (covered or rounding or suggested * factor != special)),
        "step": _text(step), "factor": _text(factor), "plan": allocation.get("plan"),
    }


def _positive(native, purpose):
    for key, row in native.items():
        quantity = _decimal(row.get("purchase_qty"))
        if quantity > 0 and row.get("status") == "purchase":
            yield key, row, purpose.get(key, {}), quantity


def _request_source(week, request):
    if request.company != week.company or request.material_request_type != "Purchase":
        frappe.throw("请选择本校的采购申请。")
    adjustment = request.get("custom_meal_adjustment")
    if adjustment:
        source = frappe.get_doc(ingredients.ADJUSTMENT, adjustment)
        source.check_permission("read")
        if source.meal_week == week.name and source.docstatus == 1 and source.material_request == request.name:
            return source
    elif week.material_request == request.name:
        return week
    frappe.throw("采购申请须直接关联本周食谱或已审核的单餐变更。")


def _preview(week, request=None):
    source = _request_source(week, request) if request else week
    native, purpose = _basis(source)
    if request and request.get(PROOF):
        saved = _verified_request(request)
        quantities = {(_key(row), row.get(USE)): _decimal(row.qty) for row in request.items}
        rows = []
        keys = {meal_planning._digest(key): key for key in native}
        for row in saved["rows"]:
            key = keys[row["key"]]
            special = quantities.get((key, SPECIAL), ZERO)
            ordinary = quantities.get((key, ORDINARY), ZERO)
            rows.append(dict(row, special_purchase=_text(special), ordinary_purchase=_text(ordinary),
                             purchase_qty=_text(special + ordinary)))
        return source, {"active": True, "saved": True, "rows": rows, "proof": saved["preview_hash"]}
    rows = []
    if request:
        seen = set()
        for row in request.items:
            key = _key(row)
            if key in seen:
                frappe.throw("原采购申请的来源行重复，请按原采购流程核对。")
            seen.add(key)
            if key not in native or _decimal(row.qty) != _decimal(native[key]["purchase_qty"]):
                frappe.throw("采购申请数量已调整，请先按冻结采购依据核对原申请。")
            rows.append(_entry(native[key], purpose.get(key, {}), _decimal(row.qty)))
    else:
        rows = [_entry(row, allocation, qty) for _, row, allocation, qty in _positive(native, purpose)]
    active = any(_decimal(row["special_required"]) for row in rows)
    fingerprint = meal_planning._digest([week.name, source.name, request.name if request else None, rows])
    return source, {"active": active, "saved": False, "rows": rows if active else [], "proof": fingerprint}


@frappe.whitelist(methods=["GET"])
def preview(week_name: str, material_request: str | None = None):
    week = meal_purchasing._week(week_name)
    request_name = material_request or week.material_request
    request = frappe.get_doc(REQUEST, request_name) if request_name else None
    if request:
        request.check_permission("read")
    if not _enabled() or week.docstatus != 1:
        return {"active": False}
    if request and not request.get(PROOF) and not ingredients._approved(_request_source(week, request)):
        return {"active": False}
    _, result = _preview(week, request)
    return dict(result, request=request_name, request_status=int(request.docstatus) if request else None)


def _decide(rows, decisions):
    if not isinstance(decisions, dict) or set(decisions) - {row["key"] for row in rows}:
        frappe.throw("拆分确认行与当前采购明细不一致。")
    chosen = {}
    for row in rows:
        confirmation = decisions.get(row["key"], {})
        if not isinstance(confirmation, dict):
            frappe.throw("拆分核对依据无效。")
        total = _decimal(row["purchase_qty"])
        special_need, ordinary_need = _decimal(row["special_required"]), _decimal(row["ordinary_required"])
        special_covered = _decimal(confirmation.get("special_covered"))
        ordinary_covered = _decimal(confirmation.get("ordinary_covered"))
        if (not ZERO <= special_covered <= special_need or not ZERO <= ordinary_covered <= ordinary_need
                or special_covered + ordinary_covered > _decimal(row["covered"])):
            frappe.throw("专用覆盖量须在本用途需求和原采购覆盖量范围内。")
        special_remaining = special_need - special_covered
        ordinary_remaining = ordinary_need - ordinary_covered
        residual = special_remaining + ordinary_remaining
        step = _decimal(row["step"])
        suggestion = (min(total, (total * special_remaining / residual).quantize(step, rounding=ROUND_HALF_UP))
                      if residual else _decimal(row["suggested_special"]))
        supplied = confirmation.get("special_purchase", _text(suggestion))
        if supplied is None or supplied == "":
            frappe.throw("请填写专项采购量。")
        special = _decimal(supplied)
        reason = str(confirmation.get("reason") or "").strip()
        if (row["review_required"] or special_covered or ordinary_covered or special != suggestion) and not reason:
            frappe.throw(f"{row['item_name']} · {row['meal_date']} {row['meal_type']}须填写库存或整件尾差的核对依据。")
        if not ZERO <= special <= total or special % step:
            frappe.throw("专项采购量须在原申请总量内，并符合采购单位精度。")
        if (not special_need and special) or (not ordinary_need and special != total):
            frappe.throw("采购用途须与已有审核的需求归属一致。")
        factor, rounding = _decimal(row["factor"]), _decimal(row["rounding_stock"])
        # Any whole-unit tail must fit in one purchase unit. The total stays frozen.
        unit = step * factor
        special_tail = unit if special_remaining % unit else ZERO
        ordinary_tail = unit if ordinary_remaining % unit else ZERO
        if (special * factor > special_remaining + max(rounding, special_tail)
                or (total - special) * factor > ordinary_remaining + max(rounding, ordinary_tail)):
            frappe.throw("拆分超出用途需求及可核对的取整尾差，请核对库存或采购单位。")
        chosen[row["key"]] = dict(row, special_purchase=_text(special), ordinary_purchase=_text(total - special),
                                  special_covered=_text(special_covered), ordinary_covered=_text(ordinary_covered),
                                  reason=reason)
    return chosen


def _signature(doc):
    return sorted([
        [row.production_plan, row.material_request_plan_item, row.item_code, row.warehouse,
         str(getdate(row.schedule_date)), row.uom, row.stock_uom, _text(_decimal(row.conversion_factor)),
         _text(_decimal(row.qty)), row.get(USE), row.get(PLAN) or ""]
        for row in doc.items
    ])


def _verified_request(doc):
    data = meal_planning._json(doc.get(PROOF))
    if not isinstance(data, dict):
        frappe.throw("专项拆分依据格式不正确。")
    proof = data.pop("hash", None)
    if not proof or proof != meal_planning._digest(data) or data["company"] != doc.company:
        frappe.throw("专项拆分依据与采购申请明细不一致，请先核对。")
    # The original split is an upper bound. Native corrections can reduce a
    # draft line or remove a superseded meal while keeping its purpose intact.
    signature = data["signature"]
    maximum = {tuple(row[:8] + row[9:]): _decimal(row[8]) for row in signature}
    current = defaultdict(Decimal)
    for row in _signature(doc):
        current[tuple(row[:8] + row[9:])] += _decimal(row[8])
    if any(key not in maximum or not ZERO < qty <= maximum[key] for key, qty in current.items()):
        frappe.throw("采购申请明细须保留已审核的用途，数量以原拆分量为上限。")
    return data


@frappe.whitelist(methods=["POST"])
def apply_split(week_name: str, preview_hash: str, decisions=None, material_request: str | None = None):
    meal_purchasing._operator()
    week = meal_purchasing._week(week_name, for_update=True)
    if not _enabled() or week.docstatus != 1:
        frappe.throw("请在有已审核专项依据的周食谱中办理。")
    name = material_request or week.material_request
    request = frappe.get_doc(REQUEST, name, for_update=True) if name else None
    if request:
        request.check_permission("write")
    source, result = _preview(week, request)
    if not result["active"] or result["proof"] != preview_hash:
        frappe.throw("采购依据已变化，请刷新拆单预览后核对。")
    if result["saved"]:
        return {"material_request": request.name, "created": False}
    choices = _decide(result["rows"], frappe.parse_json(decisions) if decisions else {})
    if not request:
        name = meal_procurement.create_material_request(week.name).get("material_request")
        if not name:
            frappe.throw("当前采购计算没有待申请的数量。")
        request = frappe.get_doc(REQUEST, name, for_update=True)
    if request.docstatus or frappe.db.exists("Purchase Order Item", {"material_request": request.name}):
        frappe.throw("请在未提交且没有采购订单的申请草稿中核对拆分。")
    request.check_permission("write")
    original = [row.as_dict(no_default_fields=True) for row in request.items]
    request.set("items", [])
    for row in original:
        choice = choices[source_id(row)]
        for purpose, quantity, plan in (
            (SPECIAL, choice["special_purchase"], choice["plan"]),
            (ORDINARY, choice["ordinary_purchase"], None),
        ):
            qty = _decimal(quantity)
            if qty:
                request.append("items", {**row, "idx": None, "qty": float(qty),
                    "stock_qty": float(qty * _decimal(row["conversion_factor"])), USE: purpose, PLAN: plan or ""})
    data = dict(company=week.company, week=week.name, source=source.name, preview_hash=preview_hash,
                signature=_signature(request), rows=list(choices.values()), reviewed_by=frappe.session.user,
                reviewed_at=str(now_datetime()))
    data["hash"] = meal_planning._digest(data)
    request.set(PROOF, frappe.as_json(data))
    token = _APPLY.set(True)
    try:
        request.save()
    finally:
        _APPLY.reset(token)
    return {"material_request": request.name, "created": True}


def check_request(doc, method=None):
    if not _enabled():
        return
    old = doc.get_doc_before_save()
    before, value = old.get(PROOF) if old else None, doc.get(PROOF)
    if value:
        _verified_request(doc)
        if not _APPLY.get() and value != before:
            replaced = doc.get("custom_meal_replaces")
            reissue = (not old and replaced and meal_purchasing._MANAGED.get()
                       and frappe.db.get_value(REQUEST, replaced, PROOF) == value)
            if not reissue:
                frappe.throw("专项拆分须通过周食谱采购操作完成。")
    elif before or any(row.get(USE) or row.get(PLAN) for row in doc.items):
        frappe.throw("采购用途须来自有效的专项拆分依据。")
    if method == "before_submit":
        week, _ = meal_purchasing._request_scope(doc, for_update=True)
        if week:
            source = frappe.get_doc(ingredients.ADJUSTMENT, doc.custom_meal_adjustment) if doc.get("custom_meal_adjustment") else week
            _, purpose = _basis(source)
            if not value and any(_decimal(purpose.get(_key(row), {}).get("special_qty")) > 0 for row in doc.items):
                frappe.throw("此申请涉及专项食材，请先在周食谱的采购操作中核对拆分。")
            if value:
                _require_effective_sources(week, doc.items)


def _effective_sources(week, lock=False):
    from ione_core.meal_adjustments import get_effective_meals

    return {row.production_plan for row in get_effective_meals(week, lock=lock) if not row.service_suspended}


def _require_effective_sources(week, rows):
    effective = _effective_sources(week, lock=True)
    if any(row.production_plan not in effective for row in rows):
        frappe.throw("已有单餐变更，请核对原单中已被替换的餐次，调整后再提交或生成订单。")


def _attribution(child, name, parent, *, lock=False):
    if not name or not parent:
        return None
    row = frappe.db.get_value(child, {"name": name, "parent": parent}, [USE, PLAN], as_dict=True, for_update=lock)
    if row and row.get(USE):
        return row.get(USE), row.get(PLAN) or ""
    return None


def _set_purpose(row, scope):
    purpose, plan = scope or ("", "")
    if (row.get(USE) and row.get(USE) != purpose) or (row.get(PLAN) and row.get(PLAN) != plan):
        frappe.throw("采购用途和营养改善计划由原单据带入。")
    row.set(USE, purpose)
    row.set(PLAN, plan)


def check_order(doc, method=None):
    if not _enabled():
        return
    scopes = set()
    for row in doc.items:
        scope = _attribution("Material Request Item", row.material_request_item, row.material_request)
        scopes.add(scope)
        _set_purpose(row, scope)
    if len(scopes) > 1 and any(scopes):
        frappe.throw("请按专项、普通及所属营养改善计划分别生成采购订单。")
    scope = next(iter(scopes), None)
    old = doc.get_doc_before_save()
    if old and old.get(USE) and (old.get(USE), old.get(PLAN) or "") != scope:
        frappe.throw("已保存订单的采购用途须保留。")
    if scope and (method == "before_submit" or doc.is_new()):
        week, sources = meal_purchasing._scope(doc, for_update=True)
        _require_effective_sources(week, [source for _, _, source, _, _ in sources])
    _set_purpose(doc, scope)


def check_receipt(doc, method=None):
    if not _enabled():
        return
    old = doc.get_doc_before_save()
    previous = {row.name: row for row in old.items if row.get(USE)} if old else {}
    for row in doc.items:
        scope = _attribution("Purchase Order Item", row.purchase_order_item, row.purchase_order)
        if doc.is_return and doc.return_against and row.get("purchase_receipt_item"):
            original = _attribution("Purchase Receipt Item", row.purchase_receipt_item, doc.return_against)
            if scope and original != scope:
                frappe.throw("采购退货的用途与原收货单不一致。")
            scope = original
        prior = previous.get(row.name)
        if prior and (prior.get(USE), prior.get(PLAN) or "") != scope:
            frappe.throw("已保存收货明细的采购用途须保留。")
        _set_purpose(row, scope)


@frappe.whitelist(methods=["GET"])
def order_options(week_name: str, material_request: str):
    week = meal_purchasing._week(week_name)
    request = frappe.get_doc(REQUEST, material_request)
    request.check_permission("read")
    _request_source(week, request)
    if not _enabled() or request.docstatus != 1 or not request.get(PROOF) or request.status == "Stopped":
        return []
    _verified_request(request)
    effective = _effective_sources(week)
    fields = ["name", "item_code", "item_name", "schedule_date", "qty", "uom", USE, PLAN]
    return [{key: row.get(key) for key in fields} | {
        "remaining": _text(max(ZERO, (_decimal(row.stock_qty) - max(_decimal(row.ordered_qty), _decimal(row.received_qty)))
                               / _decimal(row.conversion_factor)))
    } for row in request.items if row.production_plan in effective]


@frappe.whitelist(methods=["POST"])
def create_order(week_name: str, material_request: str, supplier: str, purpose: str, selected):
    meal_purchasing._operator()
    week = meal_purchasing._week(week_name, for_update=True)
    rows = frappe.parse_json(selected)
    if not isinstance(rows, list) or not rows or any(not isinstance(row, str) for row in rows):
        frappe.throw("请先选择采购申请明细。")
    request = frappe.get_doc(REQUEST, material_request, for_update=True)
    request.check_permission("read")
    _request_source(week, request)
    _verified_request(request)
    chosen = [row for row in request.items if row.name in set(rows)]
    if (purpose not in (SPECIAL, ORDINARY) or len(chosen) != len(set(rows))
            or {row.get(USE) for row in chosen} != {purpose} or len({row.get(PLAN) for row in chosen}) != 1):
        frappe.throw("请选择同一用途和营养改善计划的采购申请明细。")
    _require_effective_sources(week, chosen)
    return meal_purchasing.create_purchase_order_draft(week.name, supplier, rows, request.name)
