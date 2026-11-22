"""Permission-scoped views of existing meal, kitchen and purchasing records."""

import json
from collections import defaultdict
from datetime import timedelta

import frappe
from frappe.utils import cint, flt, getdate
from ione_core import meal_kitchen
from ione_core.meal_adjustments import get_effective_meals

from tongjianyun import special_ingredients

WEEK = "Meal Planning Week"
DAY = "Meal Kitchen Day"
SUMMARY, MEALS, STOCK, PURCHASE = "按日汇总", "餐次核对", "食材流水", "采购与日结"
SPECIAL = "专项食材"
NO_DAY, OPEN_DAY, CLOSED_DAY, UNVERIFIED_DAY = "暂无执行记录", "待日结", "已日结", "日结依据待核对"


def _column(name, label, fieldtype="Data", width=120, **properties):
    return dict(fieldname=name, label=label, fieldtype=fieldtype, width=width, **properties)


def columns(view):
    shared = [
        _column("meal_date", "供餐日期", "Date", 106),
        _column("company", "园所", "Link", 145, options="Company"),
        _column("meal_week", "食谱周计划", "Link", 160, options=WEEK),
    ]
    planned = _column("planned", "计划供餐人数", "Int")
    actual = _column("actual", "已确认实际人数", "Int", 130)
    day = _column("day", "厨房执行", "Link", 160, options=DAY)
    if view == SUMMARY:
        return shared + [
            _column("planned", "计划供餐人次", "Int"),
            _column("actual", "已确认实际人次", "Int", 132),
            _column("unconfirmed", "未确认餐次", "Int", 110),
            _column("day_status", "日结状态", width=130),
            _column("week_progress", "整周日结进度", width=125),
            day,
        ]
    if view == MEALS:
        return shared + [
            _column("slot", "餐次", width=75), _column("menu", "有效菜单", width=230), planned, actual,
            _column("difference", "人数差异", "Int", 95), _column("actual_status", "人数确认", width=125),
            _column("reason", "实际差异或停供原因", width=185), day,
        ]
    if view == STOCK:
        amounts = [
            ("planned_qty", "计划用量"), ("opening_qty", "期初留厨"), ("issued_qty", "本日领用"),
            ("consumed_qty", "实际耗用"), ("returned_qty", "退料"), ("loss_qty", "损耗"),
            ("carry_out_qty", "期末留厨"),
        ]
        return shared + [
            _column("item_code", "食材", "Link", 140, options="Item"),
            _column("item_name", "食材名称", width=150), _column("stock_uom", "库存单位", width=84),
            *(_column(name, label, "Float", 100, precision=9) for name, label in amounts),
            _column("stock_entries", "来源库存单", width=235), _column("note", "核对说明", width=220), day,
        ]
    if view == SPECIAL:
        return shared + [
            _column("meal_type", "餐次", width=75),
            _column("item_code", "食材", "Link", 125, options="Item"),
            _column("item_name", "食材名称", width=145),
            _column("planned_people", "计划供餐人数", "Int", 110),
            _column("eligible_people", "专项计划人数", "Int", 110),
            _column("stock_uom", "库存单位", width=86),
            _column("special_qty", "专项需求量", "Float", 108, precision=9),
            _column("ordinary_qty", "普通需求量", "Float", 108, precision=9),
            _column("purchase_qty", "合计拟采购量", "Float", 115, precision=9),
            _column("purchase_uom", "采购单位", width=86),
            _column("special_status", "用途归属", width=90),
            _column("plan_title", "营养改善计划", width=145),
            _column("plan_version", "计划版本时间", "Datetime", 155),
            _column("basis_doctype", "审核来源类型", hidden=1),
            _column("basis_source", "审核来源", "Dynamic Link", 160, options="basis_doctype"),
            _column("reason", "人数核对依据", width=170),
        ]
    return shared + [
        _column("kind", "记录类型", width=120),
        _column("source_doctype", "来源单据类型", hidden=1),
        _column("source", "原单", "Dynamic Link", 195, options="source_doctype"),
        _column("source_date", "单据日期", "Date", 108), _column("note", "状态", width=220),
    ]


def execute(filters=None):
    filters = frappe._dict(filters or {})
    view = filters.get("view") or SUMMARY
    if view not in (SUMMARY, MEALS, STOCK, PURCHASE, SPECIAL):
        frappe.throw("请选择有效的台账视图。")
    frappe.has_permission(WEEK, "read", throw=True)
    frappe.has_permission(DAY, "read", throw=True)
    today = getdate()
    monday = today - timedelta(days=today.weekday())
    start = getdate(filters.get("from_date") or monday)
    end = getdate(filters.get("to_date") or (start + timedelta(days=4)))
    if start > end:
        frappe.throw("结束日期须晚于或等于开始日期。")

    rows = []
    for week, daily in _weeks(filters, start, end):
        visible_days = [day for day in daily if not filters.get("day_status") or day.status == filters.day_status]
        if view == SPECIAL:
            meals = [meal for context in visible_days for meal in context.plans.values()]
            status = filters.get("special_status") or special_ingredients.SPECIAL
            rows.extend(_special_rows(week, meals, status))
            continue
        for context in visible_days:
            if view == SUMMARY:
                rows.append(_summary(week, context))
            elif view == MEALS:
                rows.extend(_meals(week, context))
            elif view == STOCK:
                rows.extend(_stock(week, context))
            else:
                rows.append(_day_reference(week, context))
        if view == PURCHASE and visible_days:
            rows.extend(_purchase(week))
    return columns(view), rows


def _special_rows(week, meals, status):
    for row in special_ingredients.ledger_rows(week, meals):
        if status != "全部" and row["special_status"] != status:
            continue
        yield {**row, "company": week.company, "meal_week": week.name,
               **{field: flt(row[field]) for field in ("special_qty", "ordinary_qty", "purchase_qty")}}


def _weeks(filters, start, end):
    criteria = {"docstatus": 1, "week_start": ("<=", end), "week_end": (">=", start)}
    if filters.get("company"):
        criteria["company"] = filters.company
    if filters.get("week_name"):
        criteria["name"] = filters.week_name
    names = frappe.get_list(WEEK, filters=criteria, pluck="name", order_by="week_start asc, company asc", limit_page_length=0)
    if not names:
        return
    by_week = defaultdict(dict)
    for row in frappe.get_list(DAY, filters={"meal_week": ("in", names), "docstatus": ("<", 2)},
                               fields=["name", "meal_week", "meal_date", "company", "docstatus"], limit_page_length=0):
        by_week[row.meal_week][str(row.meal_date)] = row

    for name in names:
        week = frappe.get_doc(WEEK, name)
        if not week.has_permission("read"):
            continue
        meals_by_day = defaultdict(dict)
        for meal in get_effective_meals(week):
            meals_by_day[str(meal.meal_date)][meal.meal_type] = meal
        frozen_week = _week_proof(week)
        current = getdate(week.week_start)
        week_end = getdate(week.week_end)
        contexts = []
        while current <= week_end:
            date = str(current)
            context = _day_context(week, date, by_week[name].get(date), meals_by_day[date], frozen_week)
            contexts.append(context)
            current += timedelta(days=1)
        progress = f"{sum(context.status == CLOSED_DAY for context in contexts)} / 5 天"
        if frozen_week and not any(context.status == UNVERIFIED_DAY for context in contexts):
            progress = "已核销 · " + progress
        elif week.get("kitchen_reconciled"):
            progress = "核销依据待核对 · " + progress
        for context in contexts:
            context.progress = progress
        yield week, [context for context in contexts if str(start) <= context.date <= str(end)]


def _day_context(week, date, token, plans, frozen_week):
    context = frappe._dict(date=date, plans=plans, day=None, proof=None, status=NO_DAY)
    if not token or token.company != week.company:
        return context
    day = frappe.get_doc(DAY, token.name)
    if not day.has_permission("read"):
        return context
    context.day = day
    if day.docstatus == 1:
        context.proof = _day_proof(day, frozen_week)
        context.status = CLOSED_DAY if context.proof else UNVERIFIED_DAY
    else:
        context.status = OPEN_DAY
    return context


def _proof(value, key, **identity):
    try:
        proof = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        return None
    if not isinstance(proof, dict) or any(proof.get(field) != expected for field, expected in identity.items()):
        return None
    content = {field: data for field, data in proof.items() if field != key}
    return proof if proof.get(key) == meal_kitchen._hash(content) else None


def _week_proof(week):
    if not week.get("kitchen_reconciled"):
        return None
    proof = _proof(week.get("kitchen_reconciliation_snapshot"), "basis_hash", week_name=week.name)
    days = proof.get("days") if proof else None
    dates = {str(getdate(week.week_start) + timedelta(days=offset)) for offset in range(5)}
    if not isinstance(days, list) or len(days) != 5 or not all(isinstance(row, dict) for row in days):
        return None
    if {row.get("meal_date") for row in days} != dates:
        return None
    return proof


def _day_proof(day, frozen_week):
    proof = _proof(day.get("execution_snapshot"), "ledger_hash", day_name=day.name, meal_week=day.meal_week,
                   meal_date=str(day.meal_date), company=day.company)
    meals = proof.get("actual_meals") if proof else None
    if not isinstance(meals, list) or len(meals) != len(meal_kitchen.SLOTS):
        return None
    if not all(isinstance(row, dict) for row in meals) or {row.get("meal_type") for row in meals} != set(meal_kitchen.SLOTS):
        return None
    if frozen_week and not any(
        row.get("name") == day.name and row.get("ledger_hash") == proof["ledger_hash"] for row in frozen_week["days"]
    ):
        return None
    return proof


def _row(week, context):
    return dict(meal_date=context.date, company=week.company, meal_week=week.name, day=context.day.name if context.day else None)


def _meals(week, context):
    rows = []
    confirmed = {}
    if context.proof:
        confirmed = {row["meal_type"]: row for row in context.proof["actual_meals"]}
    elif context.status == OPEN_DAY:
        confirmed = {row.meal_type: row for row in context.day.meals if row.actual_confirmed}
    for slot in meal_kitchen.SLOTS:
        plan = context.plans.get(slot, {})
        actual = confirmed.get(slot)
        planned = (actual.get("planned_headcount") if context.proof and actual is not None
                   else plan.get("planned_headcount"))
        people = actual.get("actual_headcount") if actual is not None else None
        rows.append(dict(
            _row(week, context), slot=slot, menu="停供" if plan.get("service_suspended") else plan.get("menu"),
            planned=planned, actual=people,
            difference=people - planned if people is not None and planned is not None else None,
            actual_status="已确认零供餐" if people == 0 else "已确认" if people is not None else "待确认",
            reason=(actual.get("reason") if actual is not None else None) or plan.get("suspension_reason"),
        ))
    return rows


def _summary(week, context):
    meals = _meals(week, context)
    expected = [row["planned"] for row in meals if row["planned"] is not None]
    confirmed = [row["actual"] for row in meals if row["actual"] is not None]
    return dict(_row(week, context), planned=sum(expected) if expected else None,
                actual=sum(confirmed) if confirmed else None, unconfirmed=len(meals) - len(confirmed),
                day_status=context.status, week_progress=context.progress)


def _visible_records(doctype, names, fields=None, **filters):
    if not names or not frappe.has_permission(doctype, "read"):
        return []
    return frappe.get_list(doctype, filters={"name": ("in", sorted(set(names))), **filters}, fields=fields or ["name"],
                           order_by="name asc", limit_page_length=0)


def _stock(week, context):
    base = _row(week, context)
    day = context.day
    if not day or context.status == UNVERIFIED_DAY:
        return [dict(base, note=context.status)]
    if context.proof:
        ledger = context.proof
    else:
        try:
            ledger = meal_kitchen._ledger(day, verify_sle=True)
        except frappe.ValidationError:
            frappe.clear_messages()
            return [dict(base, note="库存流水待核对，请打开厨房执行记录查看。")]

    totals = ledger["totals"]
    if not totals:
        return [dict(base, note="本日暂无食材流水。")]
    items = {row.item_code: row for row in day.items}
    units = {code: row.stock_uom for code, row in items.items()}
    for ref in (*ledger.get("opening_sources", []), *ledger.get("carry_out_sources", [])):
        units.setdefault(ref["item_code"], ref.get("stock_uom"))
    sources = [(row["item_code"], row["entry"]) for row in ledger["stock_ledger"]]
    sources.extend((row["item_code"], row["origin_entry"]) for row in ledger.get("opening_sources", []))
    visible = {row.name for row in _visible_records("Stock Entry", [entry for _, entry in sources],
                                                   company=week.company, docstatus=1)}
    entries_by_item = defaultdict(set)
    for code, entry in sources:
        if entry in visible:
            entries_by_item[code].add(entry)
    item_names = {row.name: row.item_name for row in _visible_records("Item", totals, ["name", "item_name"])}
    pending = len(ledger.get("drafts", []))
    rows = []
    for code, quantities in sorted(totals.items()):
        entries = sorted(entries_by_item[code])
        values = {key: flt(quantities.get(key)) for key in
                  ("opening_qty", "issued_qty", "consumed_qty", "returned_qty", "loss_qty")}
        values["carry_out_qty"] = flt(quantities.get("carry_out_qty", quantities.get("balance_qty")))
        rows.append(dict(base, **values, item_code=code, item_name=item_names.get(code), stock_uom=units.get(code),
                         planned_qty=items[code].planned_qty if code in items else None,
                         stock_entries=", ".join(entries), stock_entry_names=entries,
                         note=f"待处理库存草稿 {pending} 笔" if pending else context.status))
    return rows


def _day_reference(week, context):
    return dict(_row(week, context), kind="厨房执行", source_doctype=DAY,
                source=context.day.name if context.day else None, source_date=context.date, note=context.status)


def _linked_parents(doctype, company, child, foreign_key, names, date_field):
    if not names or not frappe.has_permission(doctype, "read"):
        return []
    fields = ["name", "docstatus", "status", date_field]
    if doctype == "Purchase Receipt":
        fields.append("is_return")
    return frappe.get_list(doctype, filters=[[doctype, "company", "=", company],
                                           [child, foreign_key, "in", sorted(set(names))]],
                           fields=fields, distinct=True,
                           order_by="name asc", limit_page_length=0)


def _purchase(week):
    kinds = (("Material Request", "采购申请"), ("Purchase Order", "采购订单"), ("Purchase Receipt", "采购收货单"))
    frozen = _week_proof(week)
    base = dict(meal_week=week.name, company=week.company)
    if week.get("kitchen_reconciled") and not frozen:
        return [dict(base, kind="本周关联采购", note="核销依据待核对")]
    if frozen:
        by_kind = frozen.get("procurement", {})
        groups = []
        for (doctype, _), key in zip(kinds, ("material_requests", "purchase_orders", "purchase_receipts"), strict=True):
            facts = {entry["name"]: entry for entry in by_kind.get(key, [])}
            date_field = "posting_date" if doctype == "Purchase Receipt" else "transaction_date"
            visible = _visible_records(doctype, facts, ["name", date_field], company=week.company)
            groups.append([dict(facts[row.name], **{date_field: row.get(date_field)}) for row in visible])
    else:
        from ione_core.meal_purchasing import _plan_names

        plans = _plan_names(week, for_update=False)
        requests = _linked_parents("Material Request", week.company, "Material Request Item", "production_plan", plans, "transaction_date")
        if week.material_request and not any(row.name == week.material_request for row in requests):
            requests.extend(_visible_records("Material Request", [week.material_request],
                                              ["name", "docstatus", "status", "transaction_date"], company=week.company))
        orders = _linked_parents("Purchase Order", week.company, "Purchase Order Item", "material_request",
                                 [row.name for row in requests], "transaction_date")
        receipts = _linked_parents("Purchase Receipt", week.company, "Purchase Receipt Item", "purchase_order",
                                   [row.name for row in orders], "posting_date")
        groups = (requests, orders, receipts)
    output = []
    for (doctype, label), records in zip(kinds, groups, strict=True):
        for row in records:
            status = (frappe._(row["status"]) if row.get("status")
                      else {0: "草稿", 1: "已提交", 2: "已取消"}.get(cint(row.get("docstatus"))))
            if doctype == "Purchase Receipt" and row.get("is_return") and row.get("docstatus") == 1:
                status = "已退货"
            output.append(dict(base, kind=f"本周{label}", source_doctype=doctype, source=row["name"],
                               source_date=row.get("transaction_date") or row.get("posting_date"), note=status))
    if not output:
        output.append(dict(base, kind="本周关联采购", note="暂无可见采购单据"))
    return output
