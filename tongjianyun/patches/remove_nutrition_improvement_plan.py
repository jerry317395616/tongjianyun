"""Retire the unused nutrition improvement plan and its dedicated purchasing and finance records."""

import frappe

DOCTYPES = (
    "Tongjianyun Canteen Subsidy Confirmation",
    "Tongjianyun Special Ingredient Basis",
    "Tongjianyun Nutrition Improvement Plan",
    "Tongjianyun Nutrition Plan Batch",
    "Tongjianyun Nutrition Plan Ingredient",
)
REPORTS = ("Tongjianyun Canteen Nutrition Subsidy", "Tongjianyun Canteen Fund Hierarchy")
USE = "custom_tjy_meal_purchase_use"
PLAN = "custom_tjy_purchase_nutrition_plan"
PROOF = "custom_tjy_meal_split_proof"
PURCHASING_FIELDS = {
    "Material Request": (PROOF,),
    **{doctype: (USE, PLAN) for doctype in (
        "Material Request Item", "Purchase Order", "Purchase Order Item", "Purchase Receipt Item",
    )},
}
FINDING = "Tongjianyun Canteen Finding"


def assert_unused():
    """Protect historical records, including fields already removed from DocType metadata."""
    checks = {
        **{doctype: {} for doctype in DOCTYPES},
        "Material Request": {PROOF: ("is", "set")},
        **{doctype: {USE: "专项", PLAN: ("is", "set")} for doctype in PURCHASING_FIELDS if doctype != "Material Request"},
        "Tongjianyun Meal Term Project": {
            "nutrition_plan": ("is", "set"), "financial_project": ("is", "set"), "approved_budget": ("!=", 0),
        },
        "Tongjianyun Canteen Policy": dict.fromkeys(
            ("subsidy_debit_account", "subsidy_credit_account", "liability_account"), ("is", "set"),
        ),
        "Tongjianyun Canteen Reconciliation Item": {"nutrition_plan": ("is", "set"), "purpose": "专项"},
        "Tongjianyun Canteen Finance Request": {"nutrition_plan": ("is", "set"), "operation": "专项补助到账"},
    }
    for doctype, filters in checks.items():
        if not frappe.db.table_exists(doctype):
            continue
        for field, value in filters.items():
            if frappe.db.has_column(doctype, field) and frappe.db.exists(doctype, {field: value}):
                frappe.throw(f"{doctype}.{field} 仍有营养改善计划相关记录，请先归档并核对。")
        if not filters and frappe.db.exists(doctype, {}):
            frappe.throw(f"{doctype} 仍有业务记录，请先归档并核对。")


def execute():
    assert_unused()
    targets = set(DOCTYPES) | set(REPORTS)
    sidebars = frappe.get_all("Sidebar Item", filters={
        "parenttype": ("in", ["Sidebar", "Custom Sidebar"]), "parentfield": "sidebar_items",
        "link_to": ("in", sorted(targets)), "link_type": ("in", ["DocType", "Report"]),
    }, fields=["parenttype", "parent"], distinct=True)
    for row in sidebars:
        sidebar = frappe.get_doc(row.parenttype, row.parent, for_update=True)
        for item in list(sidebar.sidebar_items):
            if item.link_type in ("DocType", "Report") and item.link_to in targets:
                sidebar.remove(item)
        sidebar.save(ignore_permissions=True)

    for doctype, fields in PURCHASING_FIELDS.items():
        for name in frappe.get_all("Custom Field", filters={
            "dt": doctype, "fieldname": ("in", fields), "module": "Tongjianyun",
        }, pluck="name"):
            frappe.delete_doc("Custom Field", name, ignore_permissions=True)

    for name in REPORTS:
        if frappe.db.get_value("Report", name, "module") == "Tongjianyun":
            frappe.delete_doc("Report", name, ignore_permissions=True)

    frappe.db.set_value(FINDING, {"category": "专项与财务"}, "category", "财务", update_modified=False)

    for name in DOCTYPES:
        if frappe.db.get_value("DocType", name, "module") == "Tongjianyun":
            frappe.delete_doc("DocType", name, ignore_permissions=True)
