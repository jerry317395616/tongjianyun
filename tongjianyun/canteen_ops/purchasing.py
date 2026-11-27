from collections import defaultdict
from datetime import timedelta
import json
from secrets import token_urlsafe
from statistics import median

import frappe
from frappe.utils import cint, get_datetime, getdate, now_datetime

from tongjianyun.canteen_ops.common import (
    CANTEEN, CREDENTIAL, DELIVERY, DISPATCH, POLICY, PRICE, RECEIVING, WEEK, ZERO, Handler,
    active_policy, attached_file, canteen_for_week, company_doc, dates, decimal, linked,
    lock_company, locked_rows, permission, positive, records, require, restricted_supplier, submitted, unique_active,
)

from tongjianyun.canteen_ops.delivery_lots import BULK, SUPPLIER, UPSTREAM, lot_identity

ORDER, RECEIPT, REQUEST, RFQ, QUOTE = "Purchase Order", "Purchase Receipt", "Material Request", "Request for Quotation", "Supplier Quotation"
ADJUSTMENT = "Meal Plan Adjustment"
PROGRESS = {"待接单": {"已接单", "拒接"}, "已接单": {"备货", "拒接"}, "备货": {"分拣"},
            "分拣": {"配送"}, "配送": {"到货"}}
FINAL_ORDER_STATES = {"Closed", "Completed", "Cancelled", "On Hold"}


class Policy(Handler):
    def validate(self):
        doc = self.doc
        dates(doc.from_date, doc.to_date)
        require(doc.evidence_rules, "请至少维护一条验收必需票证规则。")
        pairs = [(row.item_group or "", row.evidence_type) for row in doc.evidence_rules]
        require(len(set(pairs)) == len(pairs), "食材分类与票证类型的组合不可重复。")
        if doc.cost_center:
            source = company_doc(doc, "Cost Center", doc.cost_center)
            require(not source.is_group and not source.get("disabled"), "请选择有效的明细成本中心。")
        doc.sample_required = doc.companion_required = 1
        require(decimal(doc.sample_min_weight) >= 125 and decimal(doc.sample_keep_hours) >= 48,
                "成品留样下限为每种125克、专柜冷藏48小时；可以设置更严格的标准。")
        attached_file(doc, doc.report_template)

    def before_submit(self):
        doc = self.doc
        lock_company(doc.company)
        require(not frappe.db.exists(POLICY, {
            "canteen": doc.canteen, "docstatus": 1, "name": ("!=", doc.name),
            "from_date": ("<=", doc.to_date), "to_date": (">=", doc.from_date),
        }), "该食堂已有生效日期重叠的规则。")
        if doc.cost_center:
            require(not frappe.db.exists(POLICY, {
                "company": doc.company, "cost_center": doc.cost_center, "canteen": ("!=", doc.canteen), "docstatus": 1,
            }), "同一成本中心只能归属于一个食堂。")


class Dispatch(Handler):
    def validate(self):
        doc = self.doc
        week = submitted(company_doc(doc, WEEK, doc.meal_week))
        canteen_for_week(week, doc.canteen)
        request = submitted(company_doc(doc, REQUEST, doc.material_request))
        source = submitted(linked(ADJUSTMENT, doc.meal_adjustment)) if doc.meal_adjustment else week
        require(source.doctype == WEEK or source.meal_week == week.name, "单餐变更须属于当前周食谱。")
        require(request.material_request_type == "Purchase" and request.name == source.material_request,
                "采购申请须是该周食谱已提交的原生采购申请。")
        require(request.status not in ("Stopped", "Cancelled"), "该采购申请已终止。")
        first = min(getdate(row.schedule_date or request.schedule_date) for row in request.items)
        policy = active_policy(doc.canteen, getdate())
        doc.policy = policy.name
        doc.procurement_mode = policy.procurement_mode
        doc.assigned_to = policy.purchase_assignee
        doc.needed_by = first
        doc.order_by = first - timedelta(days=cint(policy.lead_days))
        if not doc.docstatus:
            doc.dispatched_at = None

    def before_submit(self):
        doc = self.doc
        unique_active(doc, {"material_request": doc.material_request}, "此采购申请已建立下发记录。")
        doc.dispatched_at = now_datetime()

    def on_submit(self):
        doc = self.doc
        request = linked(REQUEST, doc.material_request)
        permission(request.has_permission("read", user=doc.assigned_to) and doc.has_permission("read", user=doc.assigned_to),
                   "采购受理人须能读取本食堂下发记录和采购申请。")
        require(frappe.db.get_value("User", doc.assigned_to, "enabled"), "采购受理人已停用。")
        if not frappe.db.exists("ToDo", {"reference_type": DISPATCH, "reference_name": doc.name,
                                         "allocated_to": doc.assigned_to, "status": "Open"}):
            frappe.get_doc({"doctype": "ToDo", "reference_type": DISPATCH, "reference_name": doc.name,
                            "allocated_to": doc.assigned_to, "assigned_by": frappe.session.user,
                            "description": "审核并办理已下发的食堂采购申请", "status": "Open",
                            "date": max(getdate(), getdate(doc.order_by))}).insert()

    def before_cancel(self):
        doc = self.doc
        require(not native_parents("Purchase Order Item", "material_request", [doc.material_request], ORDER, positive_only=True),
                "申请已形成采购订单，请先处理采购订单。")
        for row in records("ToDo", {"reference_type": DISPATCH, "reference_name": doc.name, "status": "Open"}):
            todo = linked("ToDo", row.name, "write")
            todo.status = "Cancelled"
            todo.save()


def native_parents(child, field, values, parent, *, positive_only=False):
    if not values:
        return []
    filters = {"parenttype": parent, field: ("in", list(values)), "docstatus": 1 if positive_only else ("<", 2)}
    return frappe.get_all(child, filters=filters, pluck="parent", distinct=True)


@frappe.whitelist(methods=["POST"])
def prepare_dispatch(week_name, meal_adjustment=None):
    from tongjianyun.meal_procurement import create_material_request

    week = submitted(linked(WEEK, week_name))
    site = canteen_for_week(week)
    lock_company(site.company)
    source = submitted(linked(ADJUSTMENT, meal_adjustment)) if meal_adjustment else week
    require(source.doctype == WEEK or source.meal_week == week.name, "单餐变更须属于当前周食谱。")
    request_name = source.get("material_request")
    if not request_name:
        if meal_adjustment:
            return {"request": None}
        result = create_material_request(week.name)
        return {"request": result.get("material_request"), "needs_submit": bool(result.get("material_request"))}
    request = linked(REQUEST, request_name)
    if not request.docstatus:
        return {"request": request.name, "needs_submit": True}
    submitted(request)
    present = frappe.db.get_value(DISPATCH, {"material_request": request.name, "docstatus": ("<", 2)}, "name", for_update=True)
    if present:
        return {"dispatch": linked(DISPATCH, present).name}
    doc = frappe.get_doc({"doctype": DISPATCH, "company": site.company, "canteen": site.name,
                          "meal_week": week.name, "meal_adjustment": meal_adjustment, "material_request": request.name})
    doc.insert()
    return {"dispatch": doc.name}


def order_site(order, *, strict=True):
    requests = {row.material_request for row in order.items if row.get("material_request")}
    if not requests:
        return None
    criteria = {"company": order.company, "material_request": ("in", list(requests)), "docstatus": 1}
    fields = ["canteen", "material_request"]
    dispatches = locked_rows(DISPATCH, criteria, fields) if strict else frappe.get_all(DISPATCH, filters=criteria, fields=fields)
    criteria = {"material_request": ("in", list(requests)), "docstatus": 1}
    if strict:
        weeks = frappe.get_all(WEEK, filters={**criteria, "company": order.company},
                                fields=["name", "raw_material_warehouse", "kitchen_warehouse", "material_request"])
        revisions = frappe.get_all(ADJUSTMENT, filters=criteria, fields=["meal_week", "material_request"])
        for revision in revisions:
            week = frappe.db.get_value(WEEK, {"name": revision.meal_week, "company": order.company},
                                       ["raw_material_warehouse", "kitchen_warehouse"], as_dict=True)
            if week:
                weeks.append(week | {"material_request": revision.material_request})
        sites = frappe.get_all(CANTEEN, filters={"company": order.company, "disabled": 0},
                               fields=["name", "raw_warehouse", "kitchen_warehouse"])
        dispatched = {row.material_request for row in dispatches}
        for week in weeks:
            if any(site.raw_warehouse == week["raw_material_warehouse"]
                   and (not week.get("kitchen_warehouse") or site.kitchen_warehouse == week["kitchen_warehouse"])
                   and active_policy(site.name, order.transaction_date, required=False) for site in sites):
                require(week["material_request"] in dispatched, "请先审核下发对应周食谱的采购申请。")
    sites = {row.canteen for row in dispatches}
    require(len(sites) <= 1, "不同食堂的采购申请须分开下单。")
    if sites:
        require(all(row.get("material_request") in {i.material_request for i in dispatches} for row in order.items),
                "食堂采购订单应全部来自该食堂已下发的采购申请。")
        return next(iter(sites))
    return None


def evidence_rules(policy, item_code):
    group = frappe.db.get_value("Item", item_code, "item_group")
    bounds = frappe.db.get_value("Item Group", group, ["lft", "rgt"], as_dict=True) if group else None
    groups = set()
    if bounds:
        groups.update(frappe.get_all("Item Group", filters={"lft": ("<=", bounds.lft), "rgt": (">=", bounds.rgt)}, pluck="name"))
    return [row for row in policy.evidence_rules if not row.item_group or row.item_group in groups]


def credentials(canteen, supplier, on_date):
    return frappe.db.exists(CREDENTIAL, {"canteen": canteen, "supplier": supplier, "subject_kind": "供应商",
                                         "docstatus": 1, "from_date": ("<=", on_date), "to_date": (">=", on_date)})


def comparable_rate(row):
    factor = decimal(row.get("conversion_factor") or 1)
    if factor <= 0:
        return None
    value = row.get("base_net_rate")
    if value is None:
        value = row.get("base_rate")
    return decimal(value) / factor if value is not None else None


def quotation_rows(rfq, item_code=None):
    parents = native_parents("Supplier Quotation Item", "request_for_quotation", [rfq.name], QUOTE, positive_only=True)
    if not parents:
        return []
    rows = []
    for match in records(QUOTE, {"name": ("in", parents), "company": rfq.company, "docstatus": 1}):
        quote = linked(QUOTE, match.name)
        for row in quote.items:
            if row.request_for_quotation != rfq.name or (item_code and item_code != row.item_code):
                continue
            price = comparable_rate(row)
            if price is None:
                continue
            rows.append(frappe._dict(item_code=row.item_code, supplier=quote.supplier, quotation=quote.name,
                                     quantity=row.qty, uom=row.uom, rate=row.rate, base_stock_rate=float(price),
                                     currency=quote.currency, date=quote.transaction_date, expires=quote.valid_till,
                                     active=not quote.valid_till or getdate(quote.valid_till) >= getdate()))
    return rows


def _history(order, item_code):
    candidates = native_parents("Purchase Order Item", "item_code", [item_code], ORDER, positive_only=True)
    if not candidates:
        return []
    parents = records(ORDER, {"company": order.company, "name": ("in", candidates),
                              "transaction_date": (">=", getdate(order.transaction_date) - timedelta(days=90))})
    values = []
    for parent in parents:
        if parent.name == order.name:
            continue
        prior = linked(ORDER, parent.name)
        if getdate(prior.transaction_date) > getdate(order.transaction_date):
            continue
        values.extend(value for line in prior.items if line.item_code == item_code
                      for value in [comparable_rate(line)] if value is not None and value > 0)
    return values


def price_basis(order, policy, rfq=None, contract=None):
    findings = []
    quotes = quotation_rows(rfq) if rfq else []
    for row in order.items:
        value = comparable_rate(row)
        require(value is not None and value >= 0, "订单缺少可换算金额。请先计算单价和单位。")
        reasons = []
        samples = _history(order, row.item_code) if policy.price_deviation else []
        reference = median(samples) if samples else None
        if reference and abs(value - reference) * 100 / reference > decimal(policy.price_deviation):
            reasons.append("偏离近90天成交中位价")
        acceptable = {q.supplier for q in quotes if q.item_code == row.item_code and q.active}
        if len(acceptable) < cint(policy.min_quotations) and not contract:
            reasons.append("有效报价家数不足")
        if quotes and order.supplier not in acceptable and not contract:
            reasons.append("所选供应商缺少有效报价")
        if contract:
            choices = [line for line in contract.items if line.item_code == row.item_code]
            require(bool(choices), "订单食材超出采购协议范围。")
            prices = [decimal(line.rate) * decimal(order.conversion_rate or 1)
                      / positive(line.get("conversion_factor") or (row.conversion_factor if line.get("uom") == row.uom else 0))
                      for line in choices]
            if all(value > price * (1 + decimal(policy.contract_deviation) / 100) for price in prices):
                reasons.append("高于框架协议限价")
        findings.append({"order_item": row.name, "item_code": row.item_code, "unit_rate": str(value),
                         "history_reference": str(reference) if reference else None,
                         "valid_quotations": len(acceptable), "reasons": reasons})
    return findings


class PriceReview(Handler):
    def validate(self):
        doc = self.doc
        order = company_doc(doc, ORDER, doc.purchase_order)
        require(order.docstatus == 0 and order_site(order) == doc.canteen, "请选择该食堂待提交的采购订单。")
        lock_company(doc.company)
        policy = active_policy(doc.canteen, order.transaction_date)
        rfq = submitted(company_doc(doc, RFQ, doc.quotation_request)) if doc.quotation_request else None
        if rfq:
            requests = {line.material_request for line in order.items}
            require(all(line.material_request in requests for line in rfq.items),
                    "询价单须来源于本订单对应的原生采购申请。")
        contract = submitted(company_doc(doc, "Blanket Order", doc.contract)) if doc.contract else None
        if contract:
            on_date = getdate(order.transaction_date)
            require(contract.supplier == order.supplier and getdate(contract.from_date) <= on_date <= getdate(contract.to_date),
                    "请选择该供应商有效的框架协议。")
        require(policy.procurement_mode != "框架协议采购" or contract, "框架协议采购须关联框架采购协议。")
        doc.basis = json.dumps({"policy": policy.name, "rows": price_basis(order, policy, rfq, contract)},
                               ensure_ascii=False, sort_keys=True)

    def before_submit(self):
        doc = self.doc
        unique_active(doc, {"purchase_order": doc.purchase_order}, "请先撤销本订单已有的价格复核。")
        permission(frappe.session.user != doc.owner or frappe.session.user == "Administrator",
                   "须由其他采购主管复核。")

    def before_cancel(self):
        require(frappe.db.get_value(ORDER, self.doc.purchase_order, "docstatus") != 1,
                "采购订单已提交，请先处理原单。")


def check_order(doc, method=None):
    if not frappe.db.table_exists(DISPATCH):
        return
    canteen = order_site(doc)
    if not canteen:
        return
    policy = active_policy(canteen, doc.transaction_date)
    if policy.require_supplier_credential:
        require(credentials(canteen, doc.supplier, getdate(doc.transaction_date)), "供应商缺少有效的已核对资质。")
    review_name = frappe.db.get_value(PRICE, {"purchase_order": doc.name, "docstatus": 1}, "name")
    review = frappe.get_doc(PRICE, review_name) if review_name else None
    if policy.procurement_mode == "框架协议采购" or cint(policy.min_quotations) or any(
        row["reasons"] for row in price_basis(doc, policy)
    ):
        require(review, "请先完成该食堂采购订单的价格复核。")
    if review:
        rfq = frappe.get_doc(RFQ, review.quotation_request) if review.quotation_request else None
        contract = frappe.get_doc("Blanket Order", review.contract) if review.contract else None
        require((not rfq or rfq.docstatus == 1) and (not contract or contract.docstatus == 1),
                "价格复核所用询价单或协议已失效。")
        current = {"policy": policy.name, "rows": price_basis(doc, policy, rfq, contract)}
        require(json.loads(review.basis) == current, "订单、报价或历史价依据有变化，请重做价格复核。")


def delivery_order(doc, lock=False):
    if restricted_supplier():
        # Supplier accounts see the linked line projection, without ERP order-read privileges.
        order = frappe.get_doc(ORDER, doc.purchase_order, for_update=lock)
        permission(order.supplier == doc.supplier and order.company == doc.company)
    else:
        order = linked(ORDER, doc.purchase_order, lock=lock)
    require(order.supplier == doc.supplier and order.company == doc.company and order_site(order) == doc.canteen,
            "配送须关联本食堂已下发的同一供应商订单。")
    return submitted(order)


class Delivery(Handler):
    def before_insert(self):
        permission(not restricted_supplier(), "配送批次须由采购经办人从已提交订单建立。")
        self.doc.qr_token = token_urlsafe(24)

    def validate(self):
        doc = self.doc
        lock_company(doc.company)
        order = delivery_order(doc, lock=True)
        last = doc.get_doc_before_save()
        for field in ("company", "canteen", "supplier", "purchase_order", "qr_token"):
            require(not last or doc.get(field) == last.get(field), "配送身份及来源订单须保留。")
        if last:
            permission(doc.progress == last.progress or doc.flags.get("changing_progress"),
                       "请使用配送状态操作。")
        else:
            doc.progress, doc.progress_at = "待接单", now_datetime()
        if doc.progress != "拒接":
            require(doc.items, "请填写配送明细。")
        order_items = {row.name: row for row in order.items}
        previous_deliveries = locked_rows(DELIVERY, {"purchase_order": order.name, "docstatus": 1,
                                                    "name": ("!=", doc.name or "")}, ["name"])
        shipped = defaultdict(lambda: ZERO)
        for record in previous_deliveries:
            name = record.name
            other = frappe.get_doc(DELIVERY, name, for_update=True)
            if other.progress == "拒接" or frappe.db.exists(RECEIVING, {"delivery": name, "docstatus": 1}):
                continue
            for row in other.items:
                shipped[row.order_item] += decimal(row.quantity)
        own = defaultdict(lambda: ZERO)
        keys = set()
        previous_rows = {r.name: r for r in last.items} if last else {}
        lot_dates = {}
        for row in doc.items:
            origin = order_items.get(row.order_item)
            require(origin and row.item_code == origin.item_code and row.uom == origin.uom,
                    "配送食材、单位必须与采购订单明细一致。")
            previous = previous_rows.get(row.name)
            if not doc.flags.get("applying_delivery_lots") and (
                row.lot_source in (SUPPLIER, BULK) or row.receipt_trace_no
                or (previous and previous.lot_source in (SUPPLIER, BULK))
            ):
                require(previous and (row.lot_source, row.item_code, lot_identity(row)) ==
                        (previous.lot_source, previous.item_code, lot_identity(previous)),
                        "请在快速补录中生成或更换批号。")
            if row.lot_source == BULK:
                require(row.receipt_trace_no and not row.lot_number, "散装到货须使用单独的到货追溯号。")
            else:
                require(not row.receipt_trace_no and row.lot_source in (None, "", UPSTREAM, SUPPLIER),
                        "请核对批号来源。")
                if row.lot_number:
                    row.lot_number = row.lot_number.strip()
                if row.lot_source != SUPPLIER:
                    row.lot_source = UPSTREAM if row.lot_number else ""
            identity = lot_identity(row)
            if any(identity) and row.manufactured_on and row.expires_on:
                key = (row.item_code, identity)
                pair = (getdate(row.manufactured_on), getdate(row.expires_on))
                require(lot_dates.setdefault(key, pair) == pair, "同一食材同一批次的生产日期与有效期须一致。")
            key = row.order_item, identity
            require(key not in keys, "同一订单明细的同一批号请合并填写。")
            keys.add(key)
            # The initial order-backed draft can be prepared before a supplier knows the actual lot.
            if row.manufactured_on or row.expires_on:
                dates(row.manufactured_on, row.expires_on)
            own[row.order_item] += positive(row.quantity)
            require(own[row.order_item] + shipped[row.order_item] + decimal(origin.received_qty) <= decimal(origin.qty)
                    or (last and last.docstatus == 1), "配送数量超过订单尚可收货数量。")
        for evidence in doc.evidence:
            attached_file(doc, evidence.attachment)
            if evidence.item_code:
                require(any(row.item_code == evidence.item_code and
                            (not evidence.lot_number or row.lot_number == evidence.lot_number) for row in doc.items),
                        "票证食材和批号须对应配送明细。")

    def before_submit(self):
        doc = self.doc
        require(doc.progress == "分拣" and doc.flags.get("changing_progress"), "请通过「开始配送」提交随货批次。")
        for row in doc.items:
            require(any(lot_identity(row)) and row.manufactured_on and row.expires_on,
                    "请先填齐每批食材的批号或到货追溯号、生产日期和有效期。")

    def before_update_after_submit(self):
        doc = self.doc
        permission(doc.flags.get("changing_progress") or doc.flags.get("adding_evidence"),
                   "已发货配送单的票证和批次须保留。")

    def before_cancel(self):
        permission(not restricted_supplier(), "请由采购主管撤销发货。")
        require(not frappe.db.exists(RECEIVING, {"delivery": self.doc.name, "docstatus": ("<", 2)}),
                "配送已有验收记录，请先核对验收。")


def remaining_delivery_items(order):
    shipped = defaultdict(lambda: ZERO)
    batches = frappe.get_all(DELIVERY, filters={"purchase_order": order.name, "docstatus": 1}, pluck="name")
    if batches:
        received = frappe.get_all(RECEIVING, filters={"delivery": ("in", batches), "docstatus": 1}, pluck="delivery")
        in_transit = set(batches).difference(received)
        if in_transit:
            for row in frappe.get_all("Tongjianyun Canteen Delivery Item",
                                      filters={"parenttype": DELIVERY, "parent": ("in", list(in_transit)), "docstatus": 1},
                                      fields=["order_item", "quantity"]):
                shipped[row.order_item] += decimal(row.quantity)
    for row in order.items:
        remaining = decimal(row.qty) - decimal(row.received_qty) - shipped[row.name]
        if remaining > 0:
            yield row, remaining


@frappe.whitelist(methods=["POST"])
def create_delivery(purchase_order):
    order = submitted(linked(ORDER, purchase_order))
    lock_company(order.company)
    order = submitted(linked(ORDER, purchase_order, lock=True))
    site = order_site(order)
    require(site and order.status not in FINAL_ORDER_STATES, "请选择已下发且尚待收货的食堂采购订单。")
    pending = next(iter(records(DELIVERY, {"purchase_order": order.name, "docstatus": 0,
                                          "progress": ("!=", "拒接")}, order_by="creation asc")), None)
    if pending:
        return pending.name
    doc = frappe.get_doc({"doctype": DELIVERY, "company": order.company, "canteen": site, "supplier": order.supplier,
                          "purchase_order": order.name, "expected_on": order.schedule_date or getdate(),
                          "package_reference": order.name, "items": []})
    for row, remaining in remaining_delivery_items(order):
        doc.append("items", {"order_item": row.name, "item_code": row.item_code, "uom": row.uom, "quantity": float(remaining)})
    require(doc.items, "本订单已全部安排配送。")
    doc.insert()
    return doc.name


@frappe.whitelist(methods=["POST"])
def advance_delivery(name, target, note=None):
    scope = linked(DELIVERY, name, "write")
    lock_company(scope.company)
    doc = linked(DELIVERY, name, "write", lock=True)
    if doc.progress == target:
        return doc.name
    require(doc.docstatus != 2 and target in PROGRESS.get(doc.progress, set()), "请按实际履约顺序登记状态。")
    require(target != "拒接" or note, "请填写拒接理由。")
    doc.flags.changing_progress = True
    doc.progress_at = now_datetime()
    doc.progress_note = str(note or "").strip()
    if target == "配送":
        doc.submit()
        # Submitted lot records are immutable; change only the three status fields.
        doc.flags.changing_progress = True
    doc.progress = target
    doc.save()
    return doc.name


@frappe.whitelist(methods=["POST"])
def add_delivery_evidence(name, evidence_type, reference_no, attachment, item_code=None, lot_number=None,
                          valid_until=None):
    scope = linked(DELIVERY, name, "write")
    lock_company(scope.company)
    doc = submitted(linked(DELIVERY, name, "write", lock=True))
    require(not frappe.db.exists(RECEIVING, {"delivery": doc.name, "docstatus": 1}),
            "验收已完成，请按食品安全复核流程单独归档后续证据。")
    attached_file(doc, attachment, required=True)
    if item_code or lot_number:
        require(item_code and any(row.item_code == item_code and (not lot_number or row.lot_number == lot_number)
                                  for row in doc.items), "票证食材和批号须对应配送明细。")
    doc.flags.adding_evidence = True
    doc.append("evidence", {"evidence_type": evidence_type, "reference_no": reference_no,
                            "attachment": attachment, "item_code": item_code, "lot_number": lot_number,
                            "valid_until": valid_until, "added_by": frappe.session.user, "added_at": now_datetime()})
    doc.save()
    return doc.name


def evidence_problems(delivery, row, policy, date, *, rules=None):
    applicable = rules if rules is not None else evidence_rules(policy, row.item_code)
    if not applicable:
        return ["该食材缺少适用的票证规则"]
    problems = []
    for rule in applicable:
        matches = [item for item in delivery.evidence if item.evidence_type == rule.evidence_type and
                   (item.item_code == row.item_code or not item.item_code) and item.attachment and item.reference_no]
        if not matches:
            problems.append(f"缺少{rule.evidence_type}")
            continue
        valid = [item for item in matches if (
            (not rule.require_matching_batch or (row.lot_number and item.item_code == row.item_code and item.lot_number == row.lot_number))
            and (not rule.require_expiry or item.valid_until)
            and (not item.valid_until or getdate(item.valid_until) >= date)
        )]
        if not valid:
            problems.append(f"{rule.evidence_type}批号或有效期异常")
    return problems


def _mapped_receipt(doc, delivery, site, order, lines):
    from erpnext.buying.doctype.purchase_order import purchase_order
    from tongjianyun.canteen_ops import inventory
    # ERPNext 16 places mappers in a separate module; installed older versions expose them on the controller.
    mapper = getattr(purchase_order, "make_purchase_receipt", None)
    if not mapper:
        from erpnext.buying.doctype.purchase_order.mapper import make_purchase_receipt as mapper
    references = {lines[row.delivery_item].order_item for row in doc.items if decimal(row.accepted_qty) > 0}
    receipt = mapper(order.name, args={"filtered_children": list(references)})
    native = {row.purchase_order_item: row for row in receipt.items}
    receipt.set("items", [])
    receipt.posting_date, receipt.posting_time = getdate(), now_datetime().time()
    receipt.set_warehouse = site.raw_warehouse
    saved = []
    for row in doc.items:
        if decimal(row.accepted_qty) <= 0:
            continue
        lot = lines[row.delivery_item]
        source = native.get(lot.order_item)
        require(source, "订单明细已无可收货数量，请刷新并核对实际到货。")
        item = linked("Item", lot.item_code)
        require(item.is_stock_item and not item.has_serial_no and not item.has_batch_no,
                "本餐次原料须使用支持原生厨房执行的库存物料。供应商批号由膳食批次追溯记录。")
        values = source.as_dict()
        for key in ("name", "idx", "parent", "parenttype", "parentfield", "serial_and_batch_bundle",
                    "rejected_serial_and_batch_bundle"):
            values.pop(key, None)
        values.update(qty=float(row.accepted_qty), received_qty=float(row.accepted_qty), rejected_qty=0,
                      warehouse=site.raw_warehouse)
        saved.append((row, lot, receipt.append("items", values)))
    receipt.flags.canteen_receiving = doc.name
    receipt.insert()
    receipt.submit()
    inventory.record_accepted(doc, receipt, saved)
    return receipt.name


class Receiving(Handler):
    def validate(self):
        doc = self.doc
        delivery = submitted(company_doc(doc, DELIVERY, doc.delivery))
        require(delivery.canteen == doc.canteen and delivery.progress in ("配送", "到货"), "请选择本食堂已发货配送。")
        doc.supplier = delivery.supplier
        require(doc.arrived_at and get_datetime(doc.arrived_at) <= now_datetime(), "实际到货时间不能晚于当前时间。")
        site = linked(CANTEEN, doc.canteen)
        policy = active_policy(site.name, getdate(doc.arrived_at))
        require(get_datetime(doc.arrived_at) >= get_datetime(delivery.progress_at) or delivery.progress == "到货",
                "实际到货时间不能早于发货。")
        require(doc.items, "请选择配送明细并填写验收数量。")
        lots = {row.name: row for row in delivery.items}
        require(len({row.delivery_item for row in doc.items}) == len(doc.items) and
                set(lots) == {row.delivery_item for row in doc.items}, "请逐条核对配送单的全部批次。")
        for row in doc.items:
            lot = lots[row.delivery_item]
            row.item_code = lot.item_code
            row.expected_qty = lot.quantity
            row.uom = lot.uom
            row.lot_number = lot.lot_number
            row.lot_source = lot.lot_source or UPSTREAM
            row.receipt_trace_no = lot.receipt_trace_no
            row.expires_on = lot.expires_on
            issues = evidence_problems(delivery, lot, policy, getdate(doc.arrived_at))
            row.evidence_status = "、".join(issues) or ("已核对" if row.evidence_verified else "票证齐全，待人工核实")
            gross, tare = decimal(row.gross_weight), decimal(row.tare_weight)
            require(gross >= tare >= 0, "称重毛重须大于等于皮重。")
            row.net_weight = float(gross - tare) if row.gross_weight or row.tare_weight else None
            accepted, rejected = decimal(row.accepted_qty), decimal(row.rejected_qty)
            require(accepted >= 0 and rejected >= 0 and accepted + rejected <= decimal(lot.quantity),
                    "合格量与拒收量合计不能超过送货量。")
            if accepted + rejected != decimal(lot.quantity) or rejected:
                require(row.reason, "请说明短送或拒收原因。")
        attached_file(doc, doc.photo, image=True)
        if doc.position:
            try:
                latitude, longitude = [decimal(part.strip()) for part in doc.position.split(",")]
            except ValueError:
                frappe.throw("请填写有效验收经纬度。")
            require(-90 <= latitude <= 90 and -180 <= longitude <= 180 and decimal(doc.accuracy) > 0
                    and doc.location_at and get_datetime(doc.location_at) <= now_datetime(), "请获取有效的现场定位。")
        if not doc.docstatus:
            doc.reviewer = doc.received_at = doc.purchase_receipt = None
            previous = doc.get_doc_before_save()
            doc.inspector = previous.inspector if previous else frappe.session.user

    def before_submit(self):
        doc = self.doc
        lock_company(doc.company)
        delivery = submitted(linked(DELIVERY, doc.delivery, lock=True))
        policy = active_policy(doc.canteen, getdate(doc.arrived_at))
        unique_active(doc, {"delivery": doc.delivery}, "此配送已建立有效验收记录。")
        if policy.require_dual_review:
            permission(doc.inspector != frappe.session.user, "请由不同于现场验收员的库存主管复核。")
        attached_file(doc, doc.photo, required=bool(policy.require_photo), image=True)
        require(not policy.require_location or doc.position, "该食堂规则要求验收现场定位。")
        lines = {row.name: row for row in delivery.items}
        for row in doc.items:
            if decimal(row.accepted_qty) < decimal(lines[row.delivery_item].quantity):
                require((row.reason or "").strip() not in ("", "待现场核对"),
                        f"第 {row.idx} 行：请填写实际短送或拒收原因后再提交。")
        acceptance = [row for row in doc.items if decimal(row.accepted_qty) > 0]
        if acceptance and policy.require_supplier_credential:
            require(credentials(doc.canteen, doc.supplier, getdate(doc.arrived_at)), "供应商资质在验收日期无效。")
        for row in acceptance:
            lot = lines[row.delivery_item]
            on_date = max(getdate(), getdate(doc.arrived_at))
            require(getdate(lot.manufactured_on) <= getdate(doc.arrived_at) <= on_date <= getdate(lot.expires_on),
                    "生产日期或有效期异常，不能作为合格入库。")
            problems = evidence_problems(delivery, lot, policy, getdate(doc.arrived_at))
            require(not problems, f"{row.item_code}：{'、'.join(problems)}。")
            require(row.evidence_verified, "合格数量入库前须人工核对随货票证。")
        if acceptance:
            doc.purchase_receipt = _mapped_receipt(doc, delivery, linked(CANTEEN, doc.canteen),
                                                   delivery_order(delivery, lock=True), lines)
        doc.reviewer, doc.received_at = frappe.session.user, now_datetime()

    def before_cancel(self):
        require(not self.doc.purchase_receipt or frappe.db.get_value(RECEIPT, self.doc.purchase_receipt, "docstatus") == 2,
                "请先按 ERPNext 流程取消本验收生成的采购收货单。")


def check_receipt(doc, method=None):
    if doc.is_return or not frappe.db.table_exists(DISPATCH):
        return
    if doc.flags.get("canteen_receiving"):
        return
    for name in {row.purchase_order for row in doc.items if row.get("purchase_order")}:
        if order_site(frappe.get_doc(ORDER, name)):
            frappe.throw("该食堂采购订单须通过扫码验收生成采购收货单。")


@frappe.whitelist(methods=["POST"])
def receiving_from_code(code, expected_delivery=None):
    token = str(code or "").strip().removeprefix("TGY-MEAL:")
    require(20 < len(token) < 90, "请扫描随货二维码或粘贴完整随货码。")
    name = frappe.db.get_value(DELIVERY, {"qr_token": token, "docstatus": 1, "progress": ("in", ["配送", "到货"])}, "name")
    permission(name, "随货码无效或尚未发货。")
    delivery = submitted(linked(DELIVERY, name))
    require(not expected_delivery or delivery.name == expected_delivery, "该随货码与所选配送批次不一致。")
    lock_company(delivery.company)
    previous = frappe.db.get_value(RECEIVING, {"delivery": name, "docstatus": ("<", 2)}, "name", for_update=True)
    if previous:
        return linked(RECEIVING, previous).name
    doc = frappe.get_doc({"doctype": RECEIVING, "company": delivery.company, "canteen": delivery.canteen,
                          "delivery": delivery.name, "arrived_at": now_datetime()})
    for row in delivery.items:
        doc.append("items", {"delivery_item": row.name, "item_code": row.item_code, "accepted_qty": 0,
                             "rejected_qty": 0, "reason": "待现场核对"})
    doc.insert()
    return doc.name


@frappe.whitelist(methods=["GET"])
def delivery_acceptance(name):
    shipment = submitted(linked(DELIVERY, name))
    key = frappe.db.get_value(RECEIVING, {"company": shipment.company, "supplier": shipment.supplier,
                                         "delivery": shipment.name, "docstatus": 1}, "name")
    if not key:
        return {"stage": "待验收", "items": []}
    receipt = frappe.get_doc(RECEIVING, key)
    lots = {row.name: row for row in shipment.items}
    items = [{"item_code": row.item_code, "quantity": lots[row.delivery_item].quantity,
              "uom": lots[row.delivery_item].uom, "accepted": row.accepted_qty, "rejected": row.rejected_qty}
             for row in receipt.items]
    return {"stage": "已验收", "items": items, "receiving": key if receipt.has_permission("read") else None}
