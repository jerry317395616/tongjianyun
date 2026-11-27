import frappe
from frappe.utils import getdate

from tongjianyun.canteen_ops.common import DELIVERY, CanteenDocument, active_policy
from tongjianyun.canteen_ops.purchasing import evidence_problems, evidence_rules, note_verifies_line, whole_delivery_note


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
        notes = [t for t in delivery.evidence if whole_delivery_note(t)]
        date = getdate(self.arrived_at)
        details["delivery_notes"] = [{"id": t.name, "number": t.reference_no, "file": t.attachment,
                                      "expired": bool(t.valid_until and getdate(t.valid_until) < date)} for t in notes]
        selected = next((t for t in notes if t.name == self.verified_delivery_note), None)
        delivery.onload()
        manifest = delivery.get_onload() or {}
        details["names"] = manifest.get("delivery_item_names", {})
        codes = {row.item_code for row in self.items if row.item_code}
        if codes and frappe.has_permission("Item", "read"):
            images = frappe.get_list("Item", filters={"name": ("in", list(codes))},
                                     fields=["name", "image"], limit_page_length=0)
            details["images"] = {item.name: item.image for item in images if item.image}
        scheduled = manifest.get("delivery_order_dates", {})
        rules, issues = {}, {}
        for row in delivery.items:
            line = details["by_line"][row.name] = {"due": scheduled.get(row.order_item), "made": row.manufactured_on}
            if policy:
                if row.item_code not in rules:
                    rules[row.item_code] = evidence_rules(policy, row.item_code)
                applicable = rules[row.item_code]
                line["notes_covering_all_rules"] = [t.name for t in notes if note_verifies_line(t, applicable)
                                                    and (not t.valid_until or getdate(t.valid_until) >= date)]
                key = row.item_code, row.lot_number
                if key not in issues:
                    issues[key] = evidence_problems(delivery, row, policy, getdate(self.arrived_at),
                                                    rules=applicable, note=selected)
                line["issues"] = issues[key]
