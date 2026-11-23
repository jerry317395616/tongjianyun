"""Install recipe nutrition snapshot fields on existing business forms."""

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from tongjianyun.recipe_nutrition import SNAPSHOT


def install():
    create_custom_fields({
        name: [{
            "fieldname": SNAPSHOT, "label": "发布时营养计算依据", "fieldtype": "Long Text",
            "hidden": 1, "read_only": 1, "no_copy": 1, "print_hide": 1, "module": "Tongjianyun",
            "insert_after": anchor,
        }]
        for name, anchor in (("BOM", "items"), ("Meal Planning Week", "meals"), ("Meal Plan Adjustment", "dishes"))
    })
