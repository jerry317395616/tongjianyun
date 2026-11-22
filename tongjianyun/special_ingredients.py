"""Nutrition programme attribution for native, dated meal procurement demand."""

import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import frappe
from frappe.utils import getdate, now_datetime
from ione_core import meal_planning, meal_procurement

PLAN = "Tongjianyun Nutrition Improvement Plan"
BASIS = "Tongjianyun Special Ingredient Basis"
WEEK = "Meal Planning Week"
ADJUSTMENT = "Meal Plan Adjustment"
ALL = "全校在册学生"
CLASSES = "指定班级"
PENDING = "待核对"
SPECIAL = "含专项"
ORDINARY = "普通"
STEP = Decimal("0.000000001")


def _source(doctype, name, *, write=False, lock=False):
    if doctype not in (WEEK, ADJUSTMENT):
        frappe.throw("请选择有效的周食谱或单餐变更。")
    source = frappe.get_doc(doctype, name, for_update=lock)
    source.check_permission("write" if write else "read")
    week = source if doctype == WEEK else frappe.get_doc(WEEK, source.meal_week, for_update=lock)
    week.check_permission("read")
    if doctype == ADJUSTMENT and week.docstatus != 1:
        frappe.throw("单餐变更须关联本校已审核的周食谱。")
    return source, week


def _lock_company(company):
    if not frappe.db.get_value("Company", company, "name", for_update=True):
        frappe.throw("请选择有效的学校。")


def _plan_filters(company, start, end):
    return {"company": company, "docstatus": 1, "start_date": ("<=", end), "end_date": (">=", start)}


def validate_plan(doc):
    if not doc.start_date or not doc.end_date or getdate(doc.start_date) > getdate(doc.end_date):
        frappe.throw("结束日期须晚于或等于开始日期。")
    frappe.get_doc("Company", doc.company).check_permission("read")
    if doc.student_scope not in (ALL, CLASSES):
        frappe.throw("请选择适用学生范围。")
    batches = [row.student_batch for row in doc.batches]
    if (doc.student_scope == CLASSES) != bool(batches) or len(set(batches)) != len(batches):
        frappe.throw("指定班级须选择至少一个且不可重复，全校范围的班级表须留空。")
    for batch in batches:
        record = frappe.get_doc("Student Batch Name", batch)
        record.check_permission("read")
        if record.company != doc.company or record.disabled:
            frappe.throw("请选择同一学校的启用班级。")
    items = {(row.meal_type, row.item_code) for row in doc.ingredients}
    if not items or len(items) != len(doc.ingredients):
        frappe.throw("请维护专项食材，同一餐次与食材不能重复。")
    for item_code in {row.item_code for row in doc.ingredients}:
        item = frappe.get_doc("Item", item_code)
        item.check_permission("read")
        if item.disabled or not item.is_purchase_item:
            frappe.throw("请选择启用且可采购的食材。")


def activate_plan(doc):
    _lock_company(doc.company)
    filters = _plan_filters(doc.company, doc.start_date, doc.end_date)
    filters["name"] = ("!=", doc.name)
    if frappe.db.get_value(PLAN, filters, "name", for_update=True):
        frappe.throw("本校在所选日期内已有生效计划，请调整计划日期。")


def _plans(week, start, end, lock=False):
    if not frappe.db.table_exists(PLAN):
        return []
    names = frappe.db.get_values(PLAN, _plan_filters(week.company, start, end), "name", for_update=lock)
    return [frappe.get_doc(PLAN, name, for_update=lock) for (name,) in names]


def _meal_key(row):
    return (str(getdate(row.get("meal_date"))), row.get("meal_type"))


def _meals(source):
    if source.doctype == WEEK:
        return {_meal_key(row): int(row.planned_headcount) for row in source.meals if not row.service_suspended}
    return {} if source.service_suspended else {_meal_key(source): int(source.target_headcount)}


def _source_plans(source, week, lock=False):
    if source.doctype == WEEK:
        return _plans(week, week.week_start, week.week_end, lock)
    return _plans(week, source.meal_date, source.meal_date, lock)


def _count_bounds(plan, population, target):
    total = population.get("total")
    if not isinstance(total, int) or total <= 0:
        return None
    if plan.student_scope == ALL:
        return (target, target) if target <= total else (0, total)
    counts = population.get("classes", [])
    selected = {row.student_batch for row in plan.batches}
    if sum(row["count"] for row in counts) != total:
        return None
    eligible = sum(row["count"] for row in counts if row["student_batch"] in selected)
    minimum = max(0, target - (total - eligible)) if target <= total else 0
    return minimum, min(target, eligible)


def _count_context(source, week, plans):
    populations = meal_planning._json(week.population_snapshot).get("dates", {})
    result = {}
    for (date, slot), target in _meals(source).items():
        matches = [p for p in plans if str(p.start_date) <= date <= str(p.end_date)
                   and any(item.meal_type == slot for item in p.ingredients)]
        if len(matches) > 1:
            frappe.throw("同一学校和供餐日存在多个生效的营养改善计划。")
        if not matches:
            continue
        plan = matches[0]
        population = populations.get(date, {})
        bounds = _count_bounds(plan, population, target)
        key = f"{date}|{slot}"
        result[(date, slot)] = {
            "key": key, "plan": plan.name, "plan_title": plan.plan_title, "plan_version": str(plan.modified),
            "items": {row.item_code for row in plan.ingredients if row.meal_type == slot},
            "target": target, "bounds": bounds,
            "proof": meal_planning._digest([source.name, key, target, plan.name, str(plan.modified), population]),
        }
    return result


def _storage_name(source):
    return meal_planning._digest([source.doctype, source.name, str(source.creation)])


def _stored(source, *, lock=False):
    if not frappe.db.table_exists(BASIS):
        return None
    name = _storage_name(source)
    if frappe.db.get_value(BASIS, name, "name", for_update=lock):
        return frappe.get_doc(BASIS, name, for_update=lock)
    return None


def _store(source, week, field, value, document=None):
    record = document or frappe.new_doc(BASIS, source_doctype=source.doctype, source_name=source.name,
                                       meal_week=week.name, company=week.company)
    record.flags.special_ingredients_service = True
    record.set(field, frappe.as_json(value))
    if field == "approved_basis":
        record.approved = 1
    if record.is_new():
        record.insert(ignore_permissions=True, set_name=_storage_name(source))
    else:
        record.save(ignore_permissions=True)


def _approved(source):
    record = _stored(source)
    if not record or not record.approved:
        return None
    try:
        data = json.loads(record.approved_basis)
    except (TypeError, ValueError):
        data = None
    if not isinstance(data, dict):
        frappe.throw("专项使用依据校验失败，请联系管理员核对。")
    proof = data.pop("basis_hash", None)
    week_name = source.name if source.doctype == WEEK else source.meal_week
    if proof != meal_planning._digest(data) or (
        data.get("source"), data.get("source_doctype"), data.get("company"), data.get("week")
    ) != (source.name, source.doctype, record.company, week_name):
        frappe.throw("专项使用依据校验失败，请联系管理员核对。")
    return data


def _count(row, confirmations):
    bounds = row["bounds"]
    if bounds is None:
        return None, "班级名册人数不完整，请刷新周食谱人数。"
    low, high = bounds
    if low == high:
        return low, ""
    entry = confirmations.get(row["key"], {})
    if entry.get("proof") == row["proof"] and low <= entry["count"] <= high:
        return entry["count"], entry.get("reason", "")
    return None, "请核对停餐或调整后仍纳入专项的计划人数。"


def split_quantity(required, eligible, total):
    """Allocate the unrounded native gross requirement once, preserving its total."""
    amount = Decimal(str(required))
    special = amount if eligible == total else min(amount, (amount * eligible / total).quantize(STEP, rounding=ROUND_HALF_UP))
    return format(special, "f"), format(amount - special, "f")


def _classify(row, context, confirmations):
    counted, reason = None, ""
    special, ordinary = "0", row["required_qty"]
    label = ORDINARY
    applies = context and row["item_code"] in context["items"]
    if applies:
        special, ordinary = None, None
        if row["status"] == "purchase":
            counted, reason = _count(context, confirmations)
        else:
            reason = "请先处理该食材的采购口径或单位。"
        label = PENDING
        if counted is not None:
            special, ordinary = split_quantity(row["required_qty"], counted, context["target"])
            label = SPECIAL if Decimal(special) > 0 else ORDINARY
    return {
        **{key: row.get(key) for key in ("meal_date", "meal_type", "production_plan", "item_code", "item_name",
                                        "stock_uom", "purchase_uom", "required_qty", "purchase_qty")},
        "planned_people": context["target"] if context else int(Decimal(str(row["headcount"]))),
        "eligible_people": counted, "special_qty": special, "ordinary_qty": ordinary, "special_status": label,
        "plan": context["plan"] if applies else None,
        "plan_title": context["plan_title"] if applies else None,
        "plan_version": context["plan_version"] if applies else None, "reason": reason,
    }


def _build(source, week, plans, demand, *, lock=False):
    context = _count_context(source, week, plans)
    record = _stored(source, lock=lock)
    confirmations = meal_planning._json(record.count_confirmations) if record else {}
    rows = [_classify(row, context.get(_meal_key(row)), confirmations) for row in demand]
    pending = {(_meal_key(row)) for row in rows if row["special_status"] == PENDING}
    return rows, _reviews(context, confirmations, pending), confirmations, record


def _reviews(context, confirmations, keys):
    reviews = []
    for key in sorted(keys):
        row = context[key]
        if row["bounds"] and row["bounds"][0] != row["bounds"][1] and _count(row, confirmations)[0] is None:
            reviews.append({"date": key[0], "meal_type": key[1], "minimum": row["bounds"][0],
                            "maximum": row["bounds"][1], "proof": row["proof"]})
    return reviews


@frappe.whitelist(methods=["GET"])
def availability(doctype: str, name: str):
    source, week = _source(doctype, name)
    if source.docstatus == 1:
        return bool(_approved(source))
    return source.docstatus == 0 and bool(_source_plans(source, week))


@frappe.whitelist(methods=["GET"])
def preview(doctype: str, name: str):
    source, week = _source(doctype, name)
    if source.docstatus == 1:
        data = _approved(source)
        return {"active": bool(data), "approved": bool(data), "rows": data["rows"] if data else [], "reviews": []}
    plans = _source_plans(source, week)
    if source.docstatus or not plans:
        return {"active": False, "rows": [], "reviews": []}
    if doctype == ADJUSTMENT:
        record = _stored(source)
        confirmations = meal_planning._json(record.count_confirmations) if record else {}
        context = _count_context(source, week, plans)
        reviews = _reviews(context, confirmations, context)
        return {"active": True, "rows": [], "reviews": reviews, "adjustment_draft": True}
    native = meal_procurement.get_procurement_preview(week.name)
    rows, reviews, _, _ = _build(source, week, plans, native["rows"])
    return {"active": True, "rows": rows, "reviews": reviews, "blockers": native["blockers"]}


@frappe.whitelist(methods=["POST"])
def confirm_count(doctype: str, name: str, date: str, meal_type: str, count: str, reason: str, proof: str):
    source, week = _source(doctype, name, write=True)
    _lock_company(week.company)
    source, week = _source(doctype, name, write=True, lock=True)
    if source.docstatus:
        frappe.throw("只能核对尚未审核的供餐人数。")
    if not date:
        frappe.throw("请选择需要核对的供餐日期。")
    date = str(getdate(date))
    row = _count_context(source, week, _source_plans(source, week, True)).get((date, meal_type))
    try:
        value = Decimal(str(count))
    except InvalidOperation:
        frappe.throw("专项人数须为整数。")
    if not row or not row["bounds"] or not value.is_finite() or value != value.to_integral_value():
        frappe.throw("该餐次缺少可核对的专项人数依据。")
    if row["proof"] != proof:
        frappe.throw("餐次人数或计划依据已变化，请刷新专项预览后重新核对。")
    if not row["bounds"][0] <= value <= row["bounds"][1] or not reason.strip():
        frappe.throw("请在允许的范围内填写人数，并说明核对依据。")
    document = _stored(source, lock=True)
    confirmations = meal_planning._json(document.count_confirmations) if document else {}
    confirmations[row["key"]] = {"proof": row["proof"], "count": int(value), "reason": reason.strip(),
                                  "confirmed_by": frappe.session.user, "confirmed_at": str(now_datetime())}
    _store(source, week, "count_confirmations", confirmations, document)


def freeze(source, method=None):
    """Run after native submit has produced the authoritative procurement snapshot."""
    if not frappe.db.table_exists(PLAN) or not frappe.db.table_exists(BASIS):
        return
    week = source if source.doctype == WEEK else frappe.get_doc(WEEK, source.meal_week, for_update=True)
    _lock_company(week.company)
    plans = _source_plans(source, week, lock=True)
    if not plans:
        return
    if source.doctype == WEEK:
        native = meal_planning._json(source.procurement_snapshot).get("rows", [])
    else:
        native = meal_planning._json(source.applied_snapshot).get("requirements", [])
    rows, _, confirmations, record = _build(source, week, plans, native, lock=True)
    pending = {(row["meal_date"], row["meal_type"]) for row in rows if row["special_status"] == PENDING}
    if pending:
        names = "、".join(" ".join(key) for key in sorted(pending))
        frappe.throw(f"请在专项食材预览中先核对以下餐次，再审核提交：{names}")
    data = {
        "source": source.name, "source_doctype": source.doctype, "week": week.name, "company": week.company,
        "approved_by": frappe.session.user, "approved_at": str(now_datetime()), "rows": rows,
        "plans": {plan.name: {"title": plan.plan_title, "version": str(plan.modified)} for plan in plans},
        "confirmations": confirmations,
    }
    data["basis_hash"] = meal_planning._digest(data)
    _store(source, week, "approved_basis", data, record)


def ledger_rows(week, meals):
    """Show the approved version for each effective meal, including replacements."""
    sources = defaultdict(set)
    for meal in meals:
        sources[meal.get("adjustment")].add(_meal_key(meal))
    rows = []
    for adjustment, keys in sources.items():
        source = frappe.get_doc(ADJUSTMENT, adjustment) if adjustment else week
        if source.doctype == ADJUSTMENT and (source.docstatus != 1 or source.meal_week != week.name):
            continue
        data = _approved(source)
        if data:
            visible = source.has_permission("read")
            rows.extend(dict(row, basis_source=source.name if visible else None,
                             basis_doctype=source.doctype if visible else None)
                        for row in data["rows"] if _meal_key(row) in keys)
    return rows
