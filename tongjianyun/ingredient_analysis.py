"""Read-only quantity analysis of traced meal purchases and kitchen execution."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation

import frappe
from frappe.utils import cint, flt, getdate

from tongjianyun import meal_ledger as ledger, special_orders

REPORT = "Tongjianyun Ingredient Analysis"
SUMMARY, TREND, PURCHASE, KITCHEN = "食材汇总", "趋势分析", "采购明细", "消耗明细"
DAY, WEEK, MONTH = "按日", "按周", "按月"
ZERO = Decimal(0)
KITCHEN_FIELDS = ("issued_qty", "consumed_qty", "returned_qty", "loss_qty")
PURCHASE_FIELDS = ("ordered_qty", "received_qty", "purchase_return_qty", "pending_qty")
ORDER, RECEIPT, REQUEST = "Purchase Order", "Purchase Receipt", "Material Request"


def _qty(value):
    return Decimal(str(value or 0))


def _column(fieldname, label, fieldtype="Data", width=112, **options):
    return {"fieldname": fieldname, "label": label, "fieldtype": fieldtype, "width": width, **options}


def _quantities(*fields):
    return [_column(key, title, "Float", precision=9) for key, title in fields]


def columns(view):
    item = [_column("item_code", "食材", "Link", 142, options="Item"),
            _column("item_name", "食材名称", width=155), _column("stock_uom", "库存单位", width=84)]
    dated = [_column("date", "单据日期" if view == PURCHASE else "供餐日期", "Date", 110), *item]
    if view == PURCHASE:
        return dated + [
            _column("stage", "采购环节"), _column("supplier", "供应商", "Link", 143, options="Supplier"),
            _column("warehouse", "仓库", "Link", 140, options="Warehouse"),
            _column("purchase_use", "采购用途", width=88),
            *_quantities(("quantity", "数量"), ("pending_qty", "当前待到货")),
            _column("source_doctype", "单据类型", hidden=1),
            _column("source", "采购原单", "Dynamic Link", 160, options="source_doctype"),
            _column("meal_week", "食谱周计划", "Link", 150, options=ledger.WEEK),
        ]
    if view == KITCHEN:
        return dated + [
            *_quantities(("planned_qty", "计划用量"), ("opening_qty", "期初留厨"), ("issued_qty", "领用量"),
                         ("consumed_qty", "实际耗用"), ("loss_qty", "厨房损耗"), ("returned_qty", "退回原料库"),
                         ("carry_out_qty", "期末留厨")),
            _column("status", "数据状态", width=160),
            _column("day", "厨房执行", "Link", 155, options=ledger.DAY),
            _column("stock_entries", "库存原单", width=245), _column("meal_week", "食谱周计划", "Link", 150,
                                                                   options=ledger.WEEK),
        ]
    aggregated = [
        *_quantities(("ordered_qty", "已下单"), ("received_qty", "已验收"), ("purchase_return_qty", "采购退货"),
                     ("net_received_qty", "净到货"), ("pending_qty", "当前待到货"),
                     ("planned_qty", "计划用量"), ("issued_qty", "厨房领用"), ("consumed_qty", "实际耗用"),
                     ("returned_qty", "退回原料库"), ("loss_qty", "厨房损耗"), ("difference", "耗用差异")),
        _column("loss_rate", "损耗率 (%)", "Float", precision=2),
        _column("status", "异常与核对", width=230),
    ]
    if view == TREND:
        return [_column("period", "统计周期", "Date", 110), *item, *aggregated]
    return item + aggregated + _quantities(("opening_balance", "期初库存"), ("closing_balance", "期末库存"))


def execute(filters=None):
    filters = frappe._dict(filters or {})
    view = filters.get("view") or SUMMARY
    period = filters.get("period") or DAY
    if view not in (SUMMARY, TREND, PURCHASE, KITCHEN) or period not in (DAY, WEEK, MONTH):
        frappe.throw("请选择有效的分析视图和统计周期。")
    company = filters.get("company")
    if not company:
        return columns(view), [], "请选择需要分析的园所。"
    frappe.get_doc("Company", company).check_permission("read")
    frappe.has_permission(ledger.WEEK, "read", throw=True)
    frappe.has_permission(ledger.DAY, "read", throw=True)
    frappe.has_permission("Item", "read", throw=True)
    today = getdate()
    start, end = getdate(filters.get("from_date") or today - timedelta(days=29)), getdate(filters.get("to_date") or today)
    if start > end:
        frappe.throw("结束日期须晚于或等于开始日期。")

    source = Sources(company, start, end, filters.get("item_code"))
    notices = []
    if view == PURCHASE:
        rows = sorted(source.purchases(filters.get("supplier"), filters.get("purchase_use")),
                      key=lambda row: (row["date"], row["item_code"], row["stage"], row["source"]))
    elif view == KITCHEN:
        rows = list(source.kitchen())
    else:
        daily = list(source.kitchen())
        purchased = list(source.purchases())
        threshold = filters.get("variance_threshold")
        try:
            threshold = _qty(10 if threshold in (None, "") else threshold)
        except InvalidOperation:
            frappe.throw("差异阈值须为非负数。")
        if not threshold.is_finite() or threshold < 0:
            frappe.throw("差异阈值须为非负数。")
        rows = _aggregate(source, daily, purchased, period if view == TREND else None, threshold, today)
        if view == SUMMARY:
            balances = source.balances({row["item_code"] for row in rows})
            if balances is not None:
                for row in rows:
                    row["opening_balance"], row["closing_balance"] = balances.get(_item(row), (0, 0))
                notices.append("期初和期末库存汇总所选期间关联且可读的原料仓和厨房仓。")
            elif rows:
                notices.append("期初和期末库存需要可读取的膳食仓和原生库存余额报表权限。")
        if cint(filters.get("only_anomalies")):
            rows = [row for row in rows if row["status"]]
    if view != KITCHEN and not source.can_read_purchases:
        notices.append("当前账号的单据权限未覆盖完整采购链，请按可见范围核对。")
    if view in (SUMMARY, TREND):
        notices.append("采购按单据日期统计，计划和耗用按供餐日期统计。待到货取所选期间订单的当前剩余量。")
    chart = _chart(rows) if view == TREND and source.item_code else None
    return columns(view), rows, " ".join(notices) or None, chart


def _readable(doctype, names, **criteria):
    if not names or not frappe.has_permission(doctype, "read"):
        return []
    return frappe.get_list(doctype, filters={"name": ("in", sorted(names)), **criteria},
                           pluck="name", limit_page_length=0)


def _item(row):
    return row["item_code"], row["stock_uom"]


class Sources:
    def __init__(self, company, start, end, item_code):
        self.company, self.start, self.end, self.item_code = company, start, end, item_code
        self.warehouses = set()
        self.items = {}
        self.documents = {}
        self.can_read_orders = all(frappe.has_permission(dt, "read") for dt in (ORDER, REQUEST, "Production Plan"))
        self.can_read_purchases = self.can_read_orders and frappe.has_permission(RECEIPT, "read")

    def document(self, doctype, name):
        if not name:
            return None
        key = (doctype, name)
        if key not in self.documents:
            doc = frappe.get_doc(doctype, name) if frappe.db.exists(doctype, name) else None
            self.documents[key] = doc if doc and doc.has_permission("read") else None
        return self.documents[key]

    def identity(self, item_code, unit):
        if not item_code or (self.item_code and item_code != self.item_code):
            return None
        if item_code not in self.items:
            doc = self.document("Item", item_code)
            self.items[item_code] = doc.item_name if doc else None
        if self.items[item_code] is None:
            return None
        return {"item_code": item_code, "item_name": self.items[item_code], "stock_uom": unit}

    def remember_warehouses(self, week):
        self.warehouses.update(filter(None, (week.raw_material_warehouse, week.get("kitchen_warehouse"))))

    def kitchen(self):
        for week, contexts in ledger._weeks(frappe._dict(company=self.company), self.start, self.end):
            self.remember_warehouses(week)
            for context in contexts:
                if context.day:
                    self.warehouses.add(context.day.kitchen_warehouse)
                yield from self.kitchen_day(week, context)

    def kitchen_day(self, week, context):
        plan = defaultdict(Decimal)
        complete_plan = set(context.plans) == set(ledger.meal_kitchen.SLOTS)
        for meal in context.plans.values():
            if meal.get("service_suspended") or not meal.get("planned_headcount"):
                continue
            requirements = meal.get("frozen_requirements") or []
            complete_plan = complete_plan and bool(requirements)
            for row in requirements:
                if row.get("policy") == "采购" and row.get("stock_uom"):
                    plan[_item(row)] += _qty(row.get("required_qty"))

        movements = ledger._stock(week, context)
        actual = {_item(row): row for row in movements if row.get("item_code") and row.get("stock_uom")}
        validated = bool(actual) or movements[0].get("note") == "本日暂无食材流水。"
        status = context.status
        if context.day and status == ledger.OPEN_DAY and not validated:
            status = "库存流水待核对"
        if not complete_plan:
            status += " · 计划依据不完整"
        for code, unit in sorted(plan.keys() | actual.keys()):
            identity = self.identity(code, unit)
            if not identity:
                continue
            entry = actual.get((code, unit), {})
            values = {key: flt(entry.get(key)) if validated else None
                      for key in (*KITCHEN_FIELDS, "opening_qty", "carry_out_qty")}
            yield dict(identity, date=context.date, meal_week=week.name, day=context.day.name if context.day else None,
                       planned_qty=float(plan[(code, unit)]) if complete_plan else None,
                       status=status, closed=context.status == ledger.CLOSED_DAY and validated,
                       complete_plan=complete_plan, stock_entries=entry.get("stock_entries", ""),
                       stock_entry_names=entry.get("stock_entry_names", []), **values)

    def purchases(self, supplier=None, purpose=None):
        if not self.can_read_orders:
            return
        orders = self.transaction_names(ORDER, "transaction_date", supplier)
        receipts = self.transaction_names(RECEIPT, "posting_date", supplier) if self.can_read_purchases else []
        for name in orders:
            order = self.document(ORDER, name)
            if order:
                yield from self.purchase_order(order, purpose)
        for name in receipts:
            receipt = self.document(RECEIPT, name)
            if receipt:
                yield from self.purchase_receipt(receipt, purpose)

    def transaction_names(self, doctype, date_field, supplier):
        filters = {"company": self.company, "docstatus": 1, date_field: ("between", (self.start, self.end))}
        if supplier:
            filters["supplier"] = supplier
        return frappe.get_list(doctype, filters=filters, pluck="name", limit_page_length=0)

    def source_week(self, row):
        request = self.document(REQUEST, row.material_request)
        if not request or request.company != self.company or request.docstatus != 1 or request.material_request_type != "Purchase":
            return None
        source = next((item for item in request.items if item.name == row.material_request_item), None)
        if not source or source.item_code != row.item_code or source.warehouse != row.warehouse:
            return None
        plan = self.document("Production Plan", source.production_plan)
        if not plan or plan.company != self.company or plan.docstatus != 1:
            return None
        original = next((item for item in plan.mr_items if item.name == source.material_request_plan_item), None)
        if not original or original.item_code != row.item_code or original.warehouse != row.warehouse:
            return None
        week = self.document(ledger.WEEK, plan.get("custom_meal_week"))
        if week and week.docstatus == 1 and week.company == self.company:
            self.remember_warehouses(week)
            return week
        return None

    def purchase_record(self, doc, row, order_row, purpose):
        identity = self.identity(row.item_code, row.stock_uom)
        use = order_row.get(special_orders.USE) or "未标识"
        if not identity or (purpose and purpose != "全部" and use != purpose):
            return None
        week = self.source_week(order_row)
        if not week or not self.document("Warehouse", row.warehouse):
            return None
        return dict(identity, date=str(doc.get("posting_date") or doc.transaction_date), supplier=doc.supplier,
                    warehouse=row.warehouse, purchase_use=use, meal_week=week.name,
                    source_doctype=doc.doctype, source=doc.name)

    def purchase_order(self, order, purpose):
        for row in order.items:
            result = self.purchase_record(order, row, row, purpose)
            if not result:
                continue
            remaining = ZERO
            if order.status not in ("Closed", "Stopped", "Completed") and not row.get("closed"):
                remaining = max(ZERO, (_qty(row.qty) - _qty(row.received_qty)) * _qty(row.conversion_factor))
            yield dict(result, stage="已下单", quantity=flt(row.stock_qty), ordered_qty=flt(row.stock_qty),
                       pending_qty=float(remaining))

    def purchase_receipt(self, receipt, purpose):
        for row in receipt.items:
            if not row.stock_qty:
                continue
            order = self.document(ORDER, row.purchase_order)
            if not order or order.docstatus != 1 or order.company != self.company or order.supplier != receipt.supplier:
                continue
            source = next((item for item in order.items if item.name == row.purchase_order_item), None)
            if not source or source.item_code != row.item_code or source.stock_uom != row.stock_uom:
                continue
            result = self.purchase_record(receipt, row, source, purpose)
            if not result:
                continue
            qty = abs(flt(row.stock_qty))
            if receipt.is_return:
                yield dict(result, stage="采购退货", quantity=qty, purchase_return_qty=qty)
            else:
                yield dict(result, stage="已验收", quantity=qty, received_qty=qty)

    def balances(self, item_codes):
        if not item_codes or not frappe.has_permission("Stock Ledger Entry", "read"):
            return None
        warehouses = _readable("Warehouse", self.warehouses - {None, ""}, company=self.company, is_group=0)
        if not warehouses or not frappe.db.exists("Report", "Stock Balance"):
            return None
        from frappe.desk.query_report import get_report_doc, run

        try:
            report = get_report_doc("Stock Balance")
            if not frappe.has_permission(report.ref_doctype, "report"):
                return None
            data = run("Stock Balance", filters={
                "company": self.company, "from_date": str(self.start), "to_date": str(self.end),
                "warehouse": warehouses, "item_code": sorted(item_codes), "include_zero_stock_items": 1,
            }, ignore_prepared_report=True)
        except frappe.PermissionError:
            frappe.clear_messages()
            return None
        result = defaultdict(lambda: [ZERO, ZERO])
        fields = [column["fieldname"] for column in data["columns"]]
        for row in data.get("result") or []:
            if not isinstance(row, dict):
                row = dict(zip(fields, row))
            if row.get("item_code") not in item_codes or row.get("warehouse") not in warehouses:
                continue
            values = result[_item(row)]
            values[0] += _qty(row["opening_qty"])
            values[1] += _qty(row["bal_qty"])
        return {key: (float(values[0]), float(values[1])) for key, values in result.items()}


@dataclass
class Totals:
    values: dict = field(default_factory=lambda: defaultdict(Decimal))
    warnings: set = field(default_factory=set)
    kitchen_days: int = 0
    has_actual: bool = False
    closed: bool = True
    complete_plan: bool = True

    def add_kitchen(self, row, today):
        self.kitchen_days += 1
        self.closed &= row["closed"]
        self.complete_plan &= row["complete_plan"]
        self.has_actual |= row["consumed_qty"] is not None
        if not row["closed"] and getdate(row["date"]) <= today:
            self.warnings.add("日结待核对")
        if not row["complete_plan"]:
            self.warnings.add("计划依据待核对")
        for key in (*KITCHEN_FIELDS, "planned_qty"):
            self.values[key] += _qty(row[key])

    def as_row(self, source, threshold):
        amounts = self.values
        consumed = amounts["consumed_qty"]
        planned = amounts["planned_qty"]
        loss = amounts["loss_qty"]
        difference = consumed - planned if self.kitchen_days and self.complete_plan and self.closed else None
        if loss > 0:
            self.warnings.add("有损耗")
        if difference is not None and difference > 0 and not planned:
            self.warnings.add("计划外耗用")
        if difference is not None and planned and abs(difference) * 100 / planned >= threshold and difference:
            self.warnings.add("耗用偏差")
        if amounts["pending_qty"]:
            self.warnings.add("有待到货")
        record = {key: float(amounts[key]) if self.has_actual else None for key in KITCHEN_FIELDS}
        return dict(
            record, planned_qty=float(planned) if self.kitchen_days and self.complete_plan else None,
            difference=float(difference) if difference is not None else None,
            loss_rate=float(loss * 100 / (consumed + loss)) if consumed + loss else None,
            net_received_qty=float(amounts["received_qty"] - amounts["purchase_return_qty"]) if source.can_read_purchases else None,
            status="、".join(sorted(self.warnings)),
            **{key: float(amounts[key]) if source.can_read_orders else None for key in ("ordered_qty", "pending_qty")},
            **{key: float(amounts[key]) if source.can_read_purchases else None for key in ("received_qty", "purchase_return_qty")},
        )


def _period(date, grouping):
    day = getdate(date)
    if grouping == WEEK:
        return str(day - timedelta(days=day.weekday()))
    if grouping == MONTH:
        return str(day.replace(day=1))
    return str(day) if grouping else ""


def _bounds(source, period, grouping):
    if not period:
        return str(source.start), str(source.end)
    day = getdate(period)
    last = day
    if grouping == WEEK:
        last = day + timedelta(days=6)
    elif grouping == MONTH:
        last = (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return str(max(source.start, day)), str(min(source.end, last))


def _aggregate(source, kitchen, purchases, grouping, threshold, today):
    totals = defaultdict(Totals)
    for row in kitchen:
        totals[(_period(row["date"], grouping), *_item(row))].add_kitchen(row, today)
    for row in purchases:
        amounts = totals[(_period(row["date"], grouping), *_item(row))].values
        for key in PURCHASE_FIELDS:
            amounts[key] += _qty(row.get(key))
    rows = []
    for (period, code, unit), value in sorted(totals.items()):
        start, end = _bounds(source, period, grouping)
        rows.append(dict(source.identity(code, unit), period=period or None, range_start=start, range_end=end,
                         **value.as_row(source, threshold)))
    return rows


def _chart(rows):
    if not rows or len({row["stock_uom"] for row in rows}) > 1:
        return None
    datasets = [
        {"name": label, "values": [row[key] for row in rows]}
        for key, label in (("net_received_qty", "净到货"), ("planned_qty", "计划用量"), ("consumed_qty", "实际耗用"))
        if all(row[key] is not None for row in rows)
    ]
    if not datasets:
        return None
    return {
        "type": "line",
        "data": {"labels": [row["period"] for row in rows], "datasets": datasets},
    }
