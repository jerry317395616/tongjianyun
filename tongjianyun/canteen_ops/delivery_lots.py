"""Apply supplier lot details to selected rows of a draft delivery."""
from datetime import date
from decimal import Decimal

import frappe
from frappe.model.naming import getseries
from frappe.utils import getdate

from tongjianyun.canteen_ops.common import DELIVERY, decimal, linked, lock_company, require


UPSTREAM = "上游原批号"
SUPPLIER = "供应商自编"
BULK = "未提供上游批号"


def lot_identity(row):
    return (row.get("lot_number") or "", row.get("receipt_trace_no") or "")


def lot_fields(lot, doc, item_code):
    require(isinstance(lot, dict), "请填写本批次的批号和日期。")
    if lot.get("reuse_row"):
        row = next((r for r in doc.items if r.name == lot["reuse_row"] and r.item_code == item_code), None)
        require(row and any(lot_identity(row)) and row.manufactured_on and row.expires_on,
                "请选择本单同一食材已登记的批次。")
        return {"lot_number": row.lot_number, "receipt_trace_no": row.receipt_trace_no,
                "lot_source": row.lot_source or UPSTREAM, "manufactured_on": row.manufactured_on,
                "expires_on": row.expires_on}
    source = lot.get("lot_source") or UPSTREAM
    require(source in (UPSTREAM, SUPPLIER, BULK), "请选择批号来源。")
    try:
        made = date.fromisoformat(lot.get("manufactured_on"))
        expires = date.fromisoformat(lot.get("expires_on"))
    except (TypeError, ValueError):
        frappe.throw("请填写完整的生产日期和有效期。")
    require(made <= expires, "有效期不能早于生产日期。")
    if source == UPSTREAM:
        code = lot.get("lot_number")
        require(isinstance(code, str) and 0 < len(code.strip()) <= 140, "请填写包装或随货单上的原批号。")
        code = code.strip()
    else:
        prefix = ("GYS-" if source == SUPPLIER else "DH-") + getdate().strftime("%Y%m%d") + "-"
        code = prefix + getseries(prefix, 5)
        if source == SUPPLIER:
            while frappe.db.exists("Tongjianyun Canteen Delivery Item", {"lot_number": code}):
                code = prefix + getseries(prefix, 5)
    return {"lot_number": code if source != BULK else "", "receipt_trace_no": code if source == BULK else "",
            "lot_source": source, "manufactured_on": made, "expires_on": expires}


@frappe.whitelist(methods=["POST"])
def apply_lots(name, modified, item_code, row_names, lots):
    scope = linked(DELIVERY, name, "write")
    lock_company(scope.company)
    doc = linked(DELIVERY, name, "write", lock=True)
    require(doc.docstatus == 0 and doc.progress in ("待接单", "已接单", "备货", "分拣"),
            "只能补录尚未发货的配送批次。")
    require(str(doc.modified) == modified, "本单已更新，请重新读取后核对勾选的行。", frappe.TimestampMismatchError)
    names = frappe.parse_json(row_names)
    entries = frappe.parse_json(lots)
    require(isinstance(names, list) and names and all(isinstance(n, str) for n in names)
            and len(names) == len(set(names)), "请选择本批次中的食材明细。")
    chosen = set(names)
    rows = [row for row in doc.items if row.name in chosen]
    require(len(rows) == len(names) and all(row.item_code == item_code for row in rows),
            "每次只能填写本单同一食材的明细。")
    require(isinstance(entries, list) and len(entries) in (1, 2), "请选择同批填写或拆成两批。")
    fields = [lot_fields(entry, doc, item_code) for entry in entries]

    if len(entries) == 2:
        require(len(rows) == 1, "拆批时请选择一行订单明细。")
        first, = rows
        require(lot_identity(fields[0]) != lot_identity(fields[1]), "两批的批号或到货追溯号应不同。")
        quantity = decimal(entries[0].get("quantity"))
        total = decimal(first.quantity)
        precision = first.precision("quantity")
        require(0 < quantity < total, "第一批数量须大于零且小于原行数量。")
        quantum = Decimal(1).scaleb(-precision)
        remainder = total - quantity
        require(quantity == quantity.quantize(quantum) and remainder == remainder.quantize(quantum),
                f"分批数量最多保留 {precision} 位小数。")
        first.quantity = float(quantity)
        second = doc.append("items", {"order_item": first.order_item, "item_code": first.item_code,
                                      "uom": first.uom, "quantity": float(remainder), **fields[1]})
        doc.items.remove(second)
        doc.items.insert(doc.items.index(first) + 1, second)
        for index, row in enumerate(doc.items, start=1):
            row.idx = index
    for row in rows:
        row.update(fields[0])
    doc.flags.applying_delivery_lots = True
    doc.save()
    return doc.name
