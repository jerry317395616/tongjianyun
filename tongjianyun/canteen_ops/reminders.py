"""Create in-app expiry reminders for the authorized person responsible for the canteen."""
from datetime import timedelta

import frappe
from frappe.utils import cint, getdate
from frappe.utils.data import escape_html

from tongjianyun.canteen_ops.common import CANTEEN, CREDENTIAL, LOT_MOVEMENT, active_policy
from tongjianyun.canteen_ops.inventory import EPSILON, live_movements, lot_balances

METHOD = "tongjianyun.canteen_ops.reminders.send_expiry_reminders"


def _notify(user, doc, code, prefix, date):
    if (not frappe.db.get_value("User", user, "enabled") or
            not doc.has_permission("read", user=user)):
        return
    subject = escape_html(f"{prefix} · {code} · {date}")
    values = {"for_user": user, "document_type": doc.doctype, "document_name": doc.name, "subject": subject}
    if not frappe.db.exists("Notification Log", values):
        frappe.get_doc({"doctype": "Notification Log", "type": "Alert", **values}).insert()


def send_expiry_reminders():
    today = getdate()
    for site in frappe.get_all(CANTEEN, filters={"disabled": 0, "manager": ("is", "set")},
                               fields=["name", "company", "manager", "raw_warehouse", "kitchen_warehouse", "quarantine_warehouse"]):
        policy = active_policy(site.name, today, required=False)
        if not policy:
            continue
        deadline = today + timedelta(days=cint(policy.credential_warning_days))
        for row in frappe.get_all(CREDENTIAL, filters={"company": site.company, "canteen": site.name,
                                                      "docstatus": 1, "to_date": ("<=", deadline)},
                                  fields=["name", "credential_type", "to_date"]):
            prefix = "证照已到期" if getdate(row.to_date) < today else "证照临期"
            _notify(site.manager, frappe.get_doc(CREDENTIAL, row.name), row.credential_type, prefix, row.to_date)

        batch_limit = today + timedelta(days=cint(policy.stock_warning_days))
        balances, lots = lot_balances(live_movements(site.company, canteen=site.name))
        relevant = {(key, receiving) for (warehouse, key, receiving), qty in balances.items()
                    if qty > EPSILON and warehouse in (site.raw_warehouse, site.kitchen_warehouse)}
        for key in relevant:
            lot = lots[key]
            date = getdate(lot.expires_on)
            if date <= batch_limit:
                prefix = "食材批次已过期" if date < today else "食材批次临期"
                _notify(site.manager, frappe.get_doc(LOT_MOVEMENT, lot.name), lot.lot_number, prefix, date)
