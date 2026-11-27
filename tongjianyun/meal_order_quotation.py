"""Supplier quotation invitations for meal orders, using ERPNext RFQs and supplier accounts."""
from collections import defaultdict

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

from tongjianyun.meal_purchasing import _decimal, _draft_order

RFQ = "Request for Quotation"
ORDER_FIELD = "custom_tjy_source_order"


def _matches_order(rfq, po):
    def quantities(doc):
        result = defaultdict(lambda: _decimal(0))
        for row in doc.items:
            result[(row.item_code, row.uom)] += _decimal(row.qty)
        return result

    return (rfq.company == po.company and [s.supplier for s in rfq.suppliers] == [po.supplier]
            and quantities(rfq) == quantities(po))


def install():
    from tongjianyun.canteen_ops.navigation import ORDER_LAYOUT
    from tongjianyun.standard_recipe_setup import _save_layout

    line_layout = "膳食采购订单明细"
    # Keep the app-owned source link in storage, exposing it only in the meal layout.
    source = frappe.db.get_value("Custom Field", {"dt": "Purchase Order", "fieldname": "custom_meal_week"},
                                 ["name", "hidden"], as_dict=True)
    if source and not source.hidden:
        field = frappe.get_doc("Custom Field", source.name)
        field.hidden = 1
        field.save()
    _save_layout("Purchase Order Item", line_layout, {
        "item_name": {"label": "食材名称", "in_list_view": 1},
        "qty": {"label": "采购数量"}, "schedule_date": {"label": "需求日期"},
    }, is_child_table=1)
    _save_layout("Purchase Order", ORDER_LAYOUT, {
        "company": {"label": "园所", "in_standard_filter": 1},
        "supplier": {"in_list_view": 1, "in_standard_filter": 1},
        "custom_meal_week": {"label": "来源周食谱", "in_list_view": 1, "hidden": 0},
        "schedule_date": {"label": "需求日期", "in_list_view": 1, "in_standard_filter": 1},
        "grand_total": {"label": "订单金额", "in_list_view": 1},
        "items": {"label": "采购食材"},
    }, condition="", child_tables=[{"table_fieldname": "items", "child_layout": line_layout}])
    create_custom_fields({RFQ: [{
        "fieldname": ORDER_FIELD, "label": "来源膳食采购订单", "fieldtype": "Link",
        "options": "Purchase Order", "module": "Tongjianyun", "insert_after": "company",
        "read_only": 1, "no_copy": 1, "print_hide": 1, "search_index": 1,
    }]})
    if not frappe.get_meta("Supplier Quotation Item").get_field("item_name").in_list_view:
        make_property_setter("Supplier Quotation Item", "item_name", "in_list_view", "1", "Check")


@frappe.whitelist(methods=["GET"])
def status(order):
    po = frappe.get_doc("Purchase Order", order)
    po.check_permission("read")
    if not po.custom_meal_week or not frappe.has_permission(RFQ, "read"):
        return {}
    matches = frappe.get_list(RFQ, filters={ORDER_FIELD: po.name, "docstatus": ["<", 2]},
                              fields=["name", "docstatus"], order_by="creation desc", limit_page_length=1)
    if not matches:
        return {}
    rfq = frappe.get_doc(RFQ, matches[0].name)
    rfq.check_permission("read")
    result = {"name": rfq.name, "submitted": rfq.docstatus == 1}
    if not _matches_order(rfq, po):
        result["outdated"] = True
        return result
    if rfq.docstatus == 1:
        if frappe.db.get_value("Portal Menu Item", {"reference_doctype": RFQ}, "enabled"):
            result["portal_url"] = rfq.get_link()
        if frappe.has_permission("Supplier Quotation", "read"):
            result["quotes"] = frappe.get_list(
                "Supplier Quotation",
                filters=[["Supplier Quotation Item", "request_for_quotation", "=", rfq.name],
                         ["Supplier Quotation", "supplier", "=", po.supplier],
                         ["Supplier Quotation", "company", "=", po.company],
                         ["Supplier Quotation", "docstatus", "<", 2]],
                fields=["name", "docstatus"], distinct=True, order_by="creation desc",
            )
    return result


@frappe.whitelist(methods=["POST"])
def prepare(order):
    po, _, _ = _draft_order(order)
    frappe.has_permission(RFQ, "create", throw=True)
    po = frappe.get_doc("Purchase Order", po.name, for_update=True)
    po.check_permission("write")
    if po.docstatus != 0 or not po.custom_meal_week:
        frappe.throw(_("仅草稿膳食采购订单可以邀请报价。"))
    existing = frappe.db.get_value(RFQ, {ORDER_FIELD: po.name, "docstatus": ["<", 2]}, "name", for_update=True)
    if existing:
        invitation = frappe.get_doc(RFQ, existing)
        invitation.check_permission("read")
        if not _matches_order(invitation, po):
            frappe.throw(_("原询价单与当前供应商或需求明细有差异，请先处理原询价单。"))
        return existing
    rfq = frappe.new_doc(RFQ)
    rfq.update({"company": po.company, ORDER_FIELD: po.name, "schedule_date": po.schedule_date,
                "subject": f"{po.company} · 食材询价", "message_for_supplier": "请按清单填写采购单位的单价并注明报价有效期。"})
    supplier = frappe.get_doc("Supplier", po.supplier)
    supplier.check_permission("read")
    rfq.append("suppliers", {"supplier": po.supplier, "contact": po.contact_person or supplier.get("supplier_primary_contact"),
                             "email_id": po.contact_email or supplier.get("email_id"), "send_email": 0})
    groups = {}
    for row in po.items:
        key = (row.item_code, row.uom)
        if key not in groups:
            groups[key] = {"item_code": row.item_code, "item_name": row.item_name, "description": row.description,
                           "stock_uom": row.stock_uom, "uom": row.uom, "conversion_factor": row.conversion_factor,
                           "material_request": row.material_request, "schedule_date": row.schedule_date,
                           "warehouse": row.warehouse, "image": row.image, "qty": _decimal(0)}
        group = groups[key]
        if group["material_request"] != row.material_request:
            group["material_request"] = None
        group["qty"] += _decimal(row.qty)
        group["schedule_date"] = min(group["schedule_date"], row.schedule_date)
    for group in groups.values():
        rfq.append("items", group)
    rfq.insert()
    return rfq.name
