"""Add price fields to Tongjianyun Recipe Ingredient."""

import frappe


def execute():
    """Add Custom Fields for price and subtotal."""
    fields_to_add = [
        {
            "doctype": "Custom Field",
            "dt": "Tongjianyun Recipe Ingredient",
            "fieldname": "price_section",
            "fieldtype": "Section Break",
            "label": "价格信息",
            "insert_after": "grams_per_child",
        },
        {
            "doctype": "Custom Field",
            "dt": "Tongjianyun Recipe Ingredient",
            "fieldname": "unit_price",
            "fieldtype": "Float",
            "label": "单价（元/kg）",
            "insert_after": "price_section",
            "default": "0",
        },
        {
            "doctype": "Custom Field",
            "dt": "Tongjianyun Recipe Ingredient",
            "fieldname": "subtotal",
            "fieldtype": "Float",
            "label": "小计（元）",
            "insert_after": "unit_price",
            "read_only": 1,
            "default": "0",
        },
    ]

    for cf in fields_to_add:
        if frappe.db.exists("Custom Field", {"dt": cf["dt"], "fieldname": cf["fieldname"]}):
            doc = frappe.get_doc("Custom Field", {"dt": cf["dt"], "fieldname": cf["fieldname"]})
            for key in ["fieldtype", "label", "options", "insert_after", "default", "read_only"]:
                if cf.get(key) is not None:
                    setattr(doc, key, cf[key])
            doc.save(ignore_permissions=True)
        else:
            doc = frappe.new_doc("Custom Field")
            for key, value in cf.items():
                setattr(doc, key, value)
            doc.insert(ignore_permissions=True)

    frappe.db.commit()
