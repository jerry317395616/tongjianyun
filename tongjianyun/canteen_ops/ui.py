import frappe
from frappe.utils import cint, get_url_to_form
from frappe.utils.print_format_generator import get_qr_code

from tongjianyun.canteen_ops import purchasing
from tongjianyun.canteen_ops.common import CANTEEN, DELIVERY, SAMPLE, linked, require, submitted


@frappe.whitelist(methods=["GET"])
def get_labels(doctype, names, food_lots=0):
    require(doctype in (DELIVERY, SAMPLE), "请选择配送批次或食品留样。")
    names = frappe.parse_json(names)
    require(isinstance(names, list) and 0 < len(names) <= 50 and all(isinstance(name, str) for name in names),
            "每次最多打印 50 张标签。")
    if cint(food_lots):
        require(doctype == DELIVERY and len(names) == 1, "请选择一张配送单打印食材标签。")
        doc = linked(DELIVERY, names[0])
        require(doc.docstatus < 2 and doc.progress != "拒接", "该配送单已作废或拒接。")
        doc.onload()
        titles = (doc.get_onload() or {}).get("delivery_item_names", {})
        qr = get_qr_code(f"TGY-MEAL:{doc.qr_token}")
        labels = []
        seen = set()
        for row in doc.items:
            ref = row.receipt_trace_no or row.lot_number
            if not ref or not row.manufactured_on or not row.expires_on:
                continue
            source = row.lot_source or "上游原批号"
            key = (row.item_code, source, ref, str(row.manufactured_on), str(row.expires_on))
            if key in seen:
                continue
            seen.add(key)
            text = [doc.supplier, source, ("到货追溯号 " if row.receipt_trace_no else "供应商批号 ") + ref,
                    f"生产日期 {row.manufactured_on}", f"有效期至 {row.expires_on}"]
            labels.append(dict(title=titles.get(row.item_code) or row.item_code, name=doc.name, qr=qr, text=text))
        require(labels, "请先补齐至少一批食材的批次资料。")
        return labels
    labels = []
    for name in dict.fromkeys(names):
        doc = submitted(linked(doctype, name))
        site = linked(CANTEEN, doc.canteen)
        if doctype == DELIVERY:
            value = f"TGY-MEAL:{doc.qr_token}"
            info = [site.canteen_name, doc.package_reference, str(doc.expected_on), doc.purchase_order]
            title = "随货标签"
        else:
            value = get_url_to_form(SAMPLE, doc.name)
            dish = linked("BOM", doc.dish) if doc.dish else None
            title = (dish.get("item_name") or dish.item) if dish else doc.external_dish
            info = [site.canteen_name, f"{doc.meal_type} · {title}",
                    f"留样 {doc.sampled_at} · {doc.weight} 克", f"保存至 {doc.dispose_after}", doc.storage_location]
            title = "食品留样标签"
        qr = get_qr_code(value)
        require(qr, "无法生成该单据的二维码。")
        labels.append(dict(title=title, name=doc.name, qr=qr, text=info))
    return labels


@frappe.whitelist(methods=["GET"])
def order_site(purchase_order):
    order = linked("Purchase Order", purchase_order)
    return purchasing.order_site(order, strict=False)


@frappe.whitelist(methods=["GET"])
def order_delivery_status(purchase_order):
    order = linked("Purchase Order", purchase_order)
    result = {"batches": []}
    if order.docstatus != 1 or not order.get("custom_meal_week"):
        return result
    if frappe.has_permission(DELIVERY, "read"):
        result["batches"] = frappe.get_list(
            DELIVERY, filters={"purchase_order": order.name, "docstatus": ["<", 2]},
            fields=["name", "docstatus", "progress"], order_by="creation desc", limit_page_length=0,
        )
        result["pending"] = next((batch.name for batch in result["batches"]
                                  if batch.docstatus == 0 and batch.progress != "拒接"), None)
    if order.status in purchasing.FINAL_ORDER_STATES or not frappe.has_permission(DELIVERY, "create"):
        return result
    if purchasing.order_site(order, strict=False):
        result["can_create"] = any(purchasing.remaining_delivery_items(order))
    else:
        requests = {row.material_request for row in order.items if row.material_request}
        if len(requests) == 1:
            request = next(iter(requests))
            if frappe.has_permission("Material Request", "read", doc=request):
                result["dispatch_request"] = request
    return result


@frappe.whitelist(methods=["GET"])
def dispatch_source(request):
    from tongjianyun.canteen_ops.common import linked
    linked("Material Request", request)
    for kind in ("Meal Plan Adjustment", "Meal Planning Week"):
        if not frappe.has_permission(kind, "read"):
            continue
        names = frappe.get_list(kind,filters={"material_request":request,"docstatus":1},pluck="name",limit_page_length=1)
        if names:
            doc = linked(kind,names[0])
            return {"week_name":doc.meal_week,"meal_adjustment":doc.name} if kind=="Meal Plan Adjustment" else {"week_name":doc.name}
