"""Explicit, repeatable metadata retirement and installation; never purge business data."""
from pathlib import Path

import frappe

from tongjianyun.canteen_ops.setup import report_names
from frappe.core.doctype.scheduled_job_type.scheduled_job_type import get_scheduler_events

WEEKLY_MENU = "Tongjianyun Weekly Menu"
LEGACY_WEEKLY_MENU = "Meal Weekly Plan"

REPORTS = (
    WEEKLY_MENU, "Weekly Recipe Nutrition Analysis", "Tongjianyun Meal Ledger",
    "Tongjianyun Ingredient Analysis", "Tongjianyun Canteen Staffing Analysis",
) + report_names()


def adopt_legacy_weekly_menu():
    """Resolve old I-ONE report names and saved links through the Tongjianyun report."""
    source = frappe.db.get_value(
        "Report", LEGACY_WEEKLY_MENU, ["module", "is_standard", "report_type", "ref_doctype", "disabled"], as_dict=True,
    )
    if not source or source.disabled or (source.module, source.is_standard, source.report_type, source.ref_doctype) != (
        "I ONE AI", "Yes", "Script Report", "Meal Planning Week",
    ):
        return
    # A Frappe alias uses the reference report's roles. Preserve any narrower site-specific access.
    from frappe.core.doctype.custom_role.custom_role import get_custom_allowed_roles

    def report_roles(name):
        return set(get_custom_allowed_roles("report", name) or
                   [row.role for row in frappe.get_doc("Report", name).roles])

    old_roles = report_roles(LEGACY_WEEKLY_MENU)
    new_roles = report_roles(WEEKLY_MENU)
    if old_roles and (not new_roles or not new_roles <= old_roles):
        return
    frappe.db.set_value("Report", LEGACY_WEEKLY_MENU, {
        "module": "Tongjianyun",
        "is_standard": "No",
        "report_type": "Custom Report",
        "reference_report": WEEKLY_MENU,
    })
    frappe.clear_document_cache("Report", LEGACY_WEEKLY_MENU)


def install():
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw("需要系统管理员部署食谱报表。", frappe.PermissionError)
    if not frappe.db.exists("DocType", "Meal Planning Week"):
        frappe.throw("周食谱编排 DocType 尚未同步。")
    from frappe.modules.import_file import import_file_by_path

    root = Path(__file__).parent / "tongjianyun"
    # These are declared application metadata files. Use the framework importer,
    # including its standard Sidebar provenance handling, rather than raw SQL.
    report_slugs = map(frappe.scrub, REPORTS)
    files = [root / "report" / slug / f"{slug}.json" for slug in report_slugs]
    files.extend((root / "workspace/tongjianyun/tongjianyun.json", root / "sidebar/tongjianyun.json"))
    previous = frappe.flags.get("in_migrate")
    frappe.flags.in_migrate = True
    try:
        for path in files:
            import_file_by_path(str(path), force=True)
        adopt_legacy_weekly_menu()
        if frappe.db.exists("DocType", "Desktop Icon"):
            for name in frappe.get_all("Desktop Icon", filters={"app": "tongjianyun"}, pluck="name"):
                frappe.db.set_value("Desktop Icon", name, "link", "/desk/tongjianyun/query-report/Tongjianyun%20Weekly%20Menu")
        active_jobs = {method for events in get_scheduler_events().values()
                       for methods in (events.values() if isinstance(events, dict) else [events]) for method in methods}
        for row in frappe.get_all("Scheduled Job Type", filters={"method": ["like", "tongjianyun.%"]}, fields=["name", "method", "stopped"]):
            if row.method not in active_jobs and not row.stopped:
                frappe.db.set_value("Scheduled Job Type", row.name, "stopped", 1)
        for row in frappe.get_all("Report", filters={"module": "Tongjianyun"}, fields=["name", "disabled"]):
            if row.name != LEGACY_WEEKLY_MENU and row.name not in REPORTS and not row.disabled:
                frappe.db.set_value("Report", row.name, "disabled", 1)
        # Old Page metadata is executable navigation, not recipe/attendance data.
        for row in frappe.get_all("Page", filters={"module": "Tongjianyun"}, pluck="name"):
            frappe.delete_doc("Page", row, ignore_permissions=True, force=True)
        for doctype in ("Dashboard Chart", "Number Card"):
            for name in frappe.get_all(doctype, filters={"module": "Tongjianyun"}, pluck="name"):
                frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
        # App-specific sidebar customizations must not resurrect retired routes.
        if frappe.db.exists("DocType", "Custom Sidebar"):
            for name in frappe.get_all("Custom Sidebar", pluck="name"):
                doc = frappe.get_doc("Custom Sidebar", name)
                if any(doc.get(field) == "Tongjianyun" for field in ("sidebar", "module")):
                    frappe.delete_doc("Custom Sidebar", name, ignore_permissions=True, force=True)
    finally:
        frappe.flags.in_migrate = previous
    frappe.clear_cache()
    return {"reports": list(REPORTS), "read_only": True, "legacy_records_preserved": True}
