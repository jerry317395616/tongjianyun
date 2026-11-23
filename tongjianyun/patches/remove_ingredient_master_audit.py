"""Remove the retired standard ingredient audit report and its sidebar links."""

import frappe

REPORT = "Tongjianyun Ingredient Master Audit"


def execute():
    report = frappe.db.get_value("Report", REPORT, ["module", "is_standard"], as_dict=True)
    if report and (report.module, report.is_standard) != ("Tongjianyun", "Yes"):
        return
    sidebars = frappe.get_all(
        "Sidebar Item",
        filters={"parenttype": ["in", ["Sidebar", "Custom Sidebar"]], "parentfield": "sidebar_items",
                 "link_type": "Report", "link_to": REPORT},
        fields=["parenttype", "parent"],
        distinct=True,
    )
    for row in sidebars:
        sidebar = frappe.get_doc(row.parenttype, row.parent, for_update=True)
        for item in list(sidebar.sidebar_items):
            if item.link_type == "Report" and item.link_to == REPORT:
                sidebar.remove(item)
        sidebar.save(ignore_permissions=True)
    if report:
        frappe.delete_doc("Report", REPORT, ignore_permissions=True)
