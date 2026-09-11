"""Document-instance quantity precision for recipe procurement, never metadata."""
import frappe

QUANTITIES = ("qty", "stock_qty", "received_qty", "received_stock_qty", "rejected_qty")


def apply_precision(doc):
    # Frappe BaseDocument.precision uses this per-instance calculation cache.
    # Currency precision and global/DocType settings remain untouched.
    doc.precision("qty", "items")
    doc._precision["items"].update({field: 9 for field in QUANTITIES})
    for row in doc.get("items") or []:
        row.precision("qty")
        row._precision["main"].update({field: 9 for field in QUANTITIES})
    return doc


def new_target(doctype):
    return apply_precision(frappe.new_doc(doctype))


def before_validate(doc, method=None):
    if doc.doctype == "Material Request":
        linked = str(doc.title or "").startswith("童健云食谱采购 · ")
    else:
        requests = {row.get("material_request") for row in doc.get("items") or [] if row.get("material_request")}
        orders = {row.get("purchase_order") for row in doc.get("items") or [] if row.get("purchase_order")}
        if orders:
            requests.update(frappe.get_all("Purchase Order Item", filters={"parent": ["in", sorted(orders)]}, pluck="material_request"))
        linked = any(str(frappe.db.get_value("Material Request", name, "title") or "").startswith("童健云食谱采购 · ") for name in requests if name)
    if linked:
        apply_precision(doc)
