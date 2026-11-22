import frappe
from frappe.utils import get_url_to_form
from frappe.utils.print_format_generator import get_qr_code

from tongjianyun.canteen_ops import purchasing
from tongjianyun.canteen_ops.common import CANTEEN, DELIVERY, SAMPLE, linked, require, submitted


@frappe.whitelist(methods=["GET"])
def get_labels(doctype, names):
    require(doctype in (DELIVERY, SAMPLE), "请选择配送批次或食品留样。")
    names = frappe.parse_json(names)
    require(isinstance(names, list) and 0 < len(names) <= 50 and all(isinstance(name, str) for name in names),
            "每次最多打印 50 张标签。")
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
            dish = linked("BOM", doc.dish)
            info = [site.canteen_name, f"{doc.meal_type} · {dish.get('item_name') or dish.item}",
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
