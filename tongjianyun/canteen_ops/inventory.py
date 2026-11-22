"""Trace food lots against native stock movements and the existing kitchen workflow."""
from collections import defaultdict
from datetime import timedelta
from hashlib import sha256

import frappe
from frappe.utils import cint, getdate

from tongjianyun.canteen_ops.common import (
    CANTEEN, LOT_MOVEMENT, RECEIVING, SAFETY_ROLE, ZERO, Handler, active_policy, decimal, linked,
    lock_company, locked_rows, permission, require, roles,
)

STOCK = "Stock Entry"
RECEIPT = "Purchase Receipt"
EPSILON = decimal("0.000000001")


class Movement(Handler):
    def validate(self):
        permission(self.doc.is_new() and self.doc.flags.get("stock_evidence"),
                   "批次追溯由已审核的原生入库或出库操作写入。")


def key_for(supplier, lot):
    identity = "|".join((supplier, lot.item_code, lot.lot_number))
    return "MEAL-" + sha256(identity.encode()).hexdigest()[:22].upper()


def _append(company, site, lot, origin, detail, quantity, from_wh=None, to_wh=None):
    entry = frappe.get_doc({"doctype": LOT_MOVEMENT, "company": company, "canteen": site, "item_code": lot.item_code,
                            "supplier": lot.supplier, "lot_key": lot.lot_key, "lot_number": lot.lot_number,
                            "manufactured_on": lot.manufactured_on, "expires_on": lot.expires_on,
                            "receiving": lot.receiving, "posting_date": origin.posting_date,
                            "from_warehouse": from_wh, "to_warehouse": to_wh, "quantity": float(quantity),
                            "source_type": origin.doctype, "source": origin.name, "native_line": detail})
    entry.flags.stock_evidence = True
    entry.insert()


def record_accepted(receiving, receipt, lines):
    existing = {row.lot_key: row for row in live_movements(receiving.company, canteen=receiving.canteen)}
    for accepted, lot, native in lines:
        number = key_for(receiving.supplier, lot)
        known = existing.get(number)
        if known:
            require(getdate(known.manufactured_on) == getdate(lot.manufactured_on)
                    and getdate(known.expires_on) == getdate(lot.expires_on),
                    "同一供应商同一食材批号的生产日期和有效期必须一致。")
        details = frappe._dict(lot_key=number, lot_number=lot.lot_number, item_code=lot.item_code,
                               supplier=receiving.supplier, manufactured_on=lot.manufactured_on,
                               expires_on=lot.expires_on, receiving=receiving.name)
        accepted.batch_no = number
        _append(receiving.company, receiving.canteen, details, receipt, native.name, decimal(native.stock_qty),
                to_wh=native.warehouse)


def live_movements(company, *, canteen=None, item_codes=None, exclude=None, until=None, lock=False):
    filters = {"company": company}
    if canteen:
        filters["canteen"] = canteen
    if item_codes:
        filters["item_code"] = ("in", list(item_codes))
    if until:
        filters["posting_date"] = ("<=", getdate(until))
    rows = locked_rows(LOT_MOVEMENT, filters, ["*"]) if lock else frappe.get_all(
        LOT_MOVEMENT, filters=filters, fields=["*"], order_by="creation asc",
    )
    sources = defaultdict(set)
    for row in rows:
        if row.source_type in (STOCK, RECEIPT):
            sources[row.source_type].add(row.source)
    live = set()
    for doctype, names in sources.items():
        source_filters = {"company": company, "name": ("in", list(names)), "docstatus": 1}
        documents = locked_rows(doctype, source_filters, ["name"]) if lock else frappe.get_all(
            doctype, filters=source_filters, fields=["name"],
        )
        live.update((doctype, row.name) for row in documents)
    return [row for row in rows if (row.source_type, row.source) in live and (row.source_type, row.source) != exclude]


def lot_balances(movements):
    balances, lots = defaultdict(lambda: ZERO), {}
    for row in movements:
        # Each receipt stays an independent chain, even with the same printed supplier lot.
        origin = (row.lot_key, row.receiving)
        lots[origin] = row
        qty = decimal(row.quantity)
        if row.from_warehouse:
            balances[(row.from_warehouse, *origin)] -= qty
        if row.to_warehouse:
            balances[(row.to_warehouse, *origin)] += qty
    return balances, lots


def allocate(balances, lots, warehouse, item_code, quantity, date, *, allowed=None, permit_expired=False):
    choices = [
        (key, lot) for key, lot in lots.items()
        if lot.item_code == item_code and balances[(warehouse, *key)] > EPSILON
        and (permit_expired or (getdate(lot.manufactured_on) <= date <= getdate(lot.expires_on)))
        and (allowed is None or key in allowed)
    ]
    picks = []
    for key, lot in sorted(choices, key=lambda value: (getdate(value[1].expires_on), value[0])):
        qty = min(quantity, balances[(warehouse, *key)])
        if qty <= EPSILON:
            break
        balances[(warehouse, *key)] -= qty
        quantity -= qty
        picks.append((lot, qty))
    return picks, quantity


def site_warehouses(company):
    sites = frappe.get_all(CANTEEN, filters={"company": company, "disabled": 0},
                           fields=["name", "raw_warehouse", "kitchen_warehouse", "quarantine_warehouse"])
    result = {}
    for site in sites:
        for label, warehouse in (("原料仓", site.raw_warehouse), ("厨房仓", site.kitchen_warehouse),
                                 ("隔离仓", site.quarantine_warehouse)):
            if warehouse:
                require(warehouse not in result or result[warehouse][0] == site.name, "该食堂库存仓库映射不唯一。")
                result[warehouse] = (site.name, label)
    return result


def check_stock_entry(doc, method=None):
    if not frappe.db.table_exists(LOT_MOVEMENT):
        return
    mapping = site_warehouses(doc.company)
    if not any((row.s_warehouse in mapping or row.t_warehouse in mapping) for row in doc.items):
        return
    relevant = [row for row in doc.items if row.s_warehouse in mapping]
    if not relevant:
        return
    lock_company(doc.company)
    item_codes = {row.item_code for row in relevant}
    day = getdate(doc.posting_date)
    movements = live_movements(doc.company, item_codes=item_codes, until=day, lock=True)
    balances, lots = lot_balances(movements)
    source_rows = defaultdict(set)
    for movement in movements:
        if movement.source_type == STOCK:
            source_rows[movement.native_line].add((movement.lot_key, movement.receiving))
    kitchen_action = doc.get("custom_meal_action")
    for row in relevant:
        origin, label = mapping[row.s_warehouse]
        if not active_policy(origin, day, required=False):
            continue
        destination = mapping.get(row.t_warehouse)
        if destination:
            require(destination[0] == origin, "食堂仓库之间的调拨须保留同一个食堂的批次归属。")
        if label == "隔离仓":
            require(not destination or destination[1] == "隔离仓", "隔离库存须先完成质量复核。")
        # Native kitchen transaction rows reference the receipt of their original kitchen issue.
        ref = row.get("custom_meal_source_detail") or row.get("custom_meal_issue_detail")
        allowed = source_rows.get(ref, set()) if ref else None
        permit_expired = kitchen_action in ("退料", "损耗") or bool(destination and destination[1] == "隔离仓")
        quantity = decimal(row.transfer_qty)
        picks, missing = allocate(balances, lots, row.s_warehouse, row.item_code, quantity, day,
                                  allowed=allowed, permit_expired=permit_expired)
        require(missing <= EPSILON,
                f"{row.item_code} 的可追溯合格批次数量不足。请核对历史未追溯库存、隔离和过期批次。")
        for lot, qty in picks:
            if row.t_warehouse:
                balances[(row.t_warehouse, lot.lot_key, lot.receiving)] += qty
            _append(doc.company, origin, lot, doc, row.name, qty, row.s_warehouse, row.t_warehouse)


def on_purchase_return(doc, method=None):
    if not doc.is_return or not frappe.db.table_exists(LOT_MOVEMENT):
        return
    sites = site_warehouses(doc.company)
    references = {row.purchase_receipt_item for row in doc.items if row.get("purchase_receipt_item")}
    original = frappe.get_all(LOT_MOVEMENT, filters={
        "source_type": RECEIPT, "native_line": ("in", list(references)), "company": doc.company,
    }, fields=["*"]) if references else []
    if not original:
        return
    lock_company(doc.company)
    anchors = defaultdict(set)
    for row in original:
        anchors[row.native_line].add((row.lot_key, row.receiving))
    balances, lots = lot_balances(live_movements(doc.company, until=doc.posting_date, lock=True))
    for row in doc.items:
        allowed = anchors.get(row.purchase_receipt_item)
        if not allowed:
            continue
        warehouse = row.warehouse
        require(warehouse in sites, "退货原料须从原食堂仓移出。")
        picks, missing = allocate(balances, lots, warehouse, row.item_code, abs(decimal(row.stock_qty)),
                                  getdate(doc.posting_date), allowed=allowed, permit_expired=True)
        require(missing <= EPSILON, "该批库存余额不足，请核对是否已耗用或调拨。")
        for lot, qty in picks:
            _append(doc.company, sites[warehouse][0], lot, doc, row.name, qty, from_wh=warehouse)


def check_cancel(doc, method=None):
    if not frappe.db.table_exists(LOT_MOVEMENT) or not frappe.db.exists(
        LOT_MOVEMENT, {"source_type": doc.doctype, "source": doc.name, "company": doc.company}
    ):
        return
    lock_company(doc.company)
    balances, _lots = lot_balances(live_movements(doc.company, exclude=(doc.doctype, doc.name), lock=True))
    require(all(value >= -EPSILON for value in balances.values()), "已有下游批次耗用或调拨，请先按原单逆序处理。")


def inventory_rows(site, filters, today):
    mappings = {site.raw_warehouse: "原料仓", site.kitchen_warehouse: "厨房仓"}
    if site.quarantine_warehouse:
        mappings[site.quarantine_warehouse] = "隔离仓"
    if filters.get("warehouse"):
        mappings = {key: value for key, value in mappings.items() if key == filters["warehouse"]}
    regulatory_view = SAFETY_ROLE in roles()
    warehouse_names = [name for name in mappings if regulatory_view or frappe.get_doc("Warehouse", name).has_permission("read")]
    if not warehouse_names:
        return
    item_code = filters.get("item_code")
    if item_code:
        linked("Item", item_code)
    policy = active_policy(site.name, today, required=False)
    warn_date = today + timedelta(days=cint(policy.stock_warning_days) if policy else 7)
    movements = live_movements(site.company, canteen=site.name, item_codes={item_code} if item_code else None)
    balances, lots = lot_balances(movements)
    allocated = defaultdict(lambda: ZERO)
    for (warehouse, lot_key, receiving), qty in sorted(balances.items()):
        if warehouse not in warehouse_names or qty <= EPSILON:
            continue
        lot = lots[(lot_key, receiving)]
        expiry = getdate(lot.expires_on)
        allocated[(warehouse, lot.item_code)] += qty
        state = "已过期" if expiry < today else "临期" if expiry <= warn_date else "正常"
        if mappings[warehouse] == "隔离仓":
            state = "隔离 · " + state
        yield dict(company=site.company, canteen=site.name, warehouse=warehouse, item_code=lot.item_code,
                   lot_number=lot.lot_number, lot_key=lot.lot_key, expires_on=expiry, posted_qty=float(qty),
                   usable_qty=float(qty) if expiry >= today and mappings[warehouse] != "隔离仓" else 0,
                   stage=state, source_type=RECEIVING, source=receiving)
    if not frappe.has_permission("Stock Ledger Entry", "read"):
        return
    rules = {"warehouse": ("in", warehouse_names)}
    if item_code:
        rules["item_code"] = item_code
    for row in frappe.get_all("Bin", filters=rules, fields=["warehouse", "item_code", "actual_qty", "reserved_qty"]):
        if not frappe.get_doc("Item", row.item_code).has_permission("read"):
            continue
        diff = decimal(row.actual_qty) - allocated[(row.warehouse, row.item_code)]
        if abs(diff) > EPSILON or row.reserved_qty:
            yield dict(company=site.company, canteen=site.name, warehouse=row.warehouse, item_code=row.item_code,
                       posted_qty=float(diff), reserved_qty=row.reserved_qty,
                       stage="账面与批次不一致" if diff < 0 else "账面库存待追溯" if diff > 0 else "原生库存已预留")
