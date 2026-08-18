from __future__ import annotations

import frappe


DOCTYPE = "Tongjianyun Recipe Student Group"


def execute() -> None:
    if frappe.db.exists("DocType", DOCTYPE):
        frappe.delete_doc("DocType", DOCTYPE, force=True, ignore_permissions=True)
    frappe.clear_cache()
