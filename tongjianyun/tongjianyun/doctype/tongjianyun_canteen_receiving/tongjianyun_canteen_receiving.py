import frappe
from frappe.utils import getdate

from tongjianyun.canteen_ops.common import DELIVERY, CanteenDocument, active_policy
from tongjianyun.canteen_ops.purchasing import evidence_problems, evidence_rules


class TongjianyunCanteenReceiving(CanteenDocument):
    def onload(self):
        if not self.delivery or not self.canteen:
            return
        policy = active_policy(self.canteen, self.arrived_at, required=False) if not self.docstatus else None
        details = {"policy": {k: bool(policy.get(k)) for k in (
            "require_dual_review", "require_photo", "require_location"
        )} if policy else None, "names": {}, "by_line": {}}
        self.set_onload("inspection", details)
        delivery = frappe.get_doc(DELIVERY, self.delivery)
        if delivery.company != self.company or delivery.canteen != self.canteen or not delivery.has_permission("read"):
            return
        details["can_open_delivery"] = True
        delivery.onload()
        manifest = delivery.get_onload() or {}
        details["names"] = manifest.get("delivery_item_names", {})
        scheduled = manifest.get("delivery_order_dates", {})
        rules, issues = {}, {}
        for row in delivery.items:
            line = details["by_line"][row.name] = {"due": scheduled.get(row.order_item), "made": row.manufactured_on}
            if policy:
                if row.item_code not in rules:
                    rules[row.item_code] = evidence_rules(policy, row.item_code)
                key = row.item_code, row.lot_number
                if key not in issues:
                    issues[key] = evidence_problems(delivery, row, policy, getdate(self.arrived_at),
                                                    rules=rules[row.item_code])
                line["issues"] = issues[key]
