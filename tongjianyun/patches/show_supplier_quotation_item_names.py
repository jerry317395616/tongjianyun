"""Add the name column to previously saved quotation grids, preserving their other columns."""
import json

import frappe


def _with_item_name(raw):
    settings = frappe.parse_json(raw) if raw else None
    if not isinstance(settings, dict):
        return
    columns = (settings.get("GridView") or {}).get("Supplier Quotation Item")
    if not columns or any(col.get("fieldname") == "item_name" for col in columns):
        return
    index = next((i + 1 for i, col in enumerate(columns) if col.get("fieldname") == "item_code"), 0)
    columns.insert(index, {"fieldname": "item_name"})
    return json.dumps(settings)


def execute():
    doctype = "Supplier Quotation"
    for user, raw in frappe.db.sql(
        "SELECT `user`, data FROM `__UserSettings` WHERE doctype=%s FOR UPDATE", doctype
    ):
        if updated := _with_item_name(raw):
            frappe.db.sql("UPDATE `__UserSettings` SET data=%s WHERE doctype=%s AND `user`=%s",
                          (updated, doctype, user))

    # Frappe may hold a newer layout solely in Redis until the next settings sync.
    for key in frappe.cache.hkeys("_user_settings"):
        key = frappe.safe_decode(key)
        if key.startswith(doctype + "::"):
            if updated := _with_item_name(frappe.cache.hget("_user_settings", key)):
                frappe.cache.hset("_user_settings", key, updated)
