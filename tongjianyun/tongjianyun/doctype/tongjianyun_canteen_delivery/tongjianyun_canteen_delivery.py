import frappe

from tongjianyun.canteen_ops.common import CanteenDocument


class TongjianyunCanteenDelivery(CanteenDocument):
    def onload(self):
        # A supplier can read its own manifest without access to the Item catalogue.
        if not self.purchase_order or not self.items:
            return
        order_lines = {row.order_item: row.item_code for row in self.items}
        rows = frappe.get_all(
            "Purchase Order Item",
            filters={"parenttype": "Purchase Order", "parent": self.purchase_order, "parentfield": "items",
                     "name": ("in", list(order_lines))},
            fields=["name", "item_code", "item_name"],
        )
        self.set_onload("delivery_item_names", {
            row.item_code: row.item_name for row in rows
            if row.item_name and order_lines.get(row.name) == row.item_code
        })
