"""Explicit, repeatable metadata retirement and installation; never purge business data."""
from pathlib import Path

import frappe

REPORTS = ("Tongjianyun Weekly Menu", "Weekly Recipe Nutrition Analysis")


def install():
    if frappe.session.user != "Administrator" and "System Manager" not in frappe.get_roles():
        frappe.throw("需要系统管理员部署食谱报表。", frappe.PermissionError)
    if not frappe.db.exists("Report", "Meal Weekly Plan"):
        frappe.throw("请先安装并配置 I-ONE Core 的 ERP 周食谱报表。")
    from frappe.modules.import_file import import_file_by_path

    root = Path(__file__).parent / "tongjianyun"
    # These are declared application metadata files. Use the framework importer,
    # including its standard Sidebar provenance handling, rather than raw SQL.
    files = [root / "report" / slug / (slug + ".json") for slug in ("tongjianyun_weekly_menu", "weekly_recipe_nutrition_analysis")]
    files.extend((root / "workspace/tongjianyun/tongjianyun.json", root / "sidebar/tongjianyun.json"))
    previous = frappe.flags.get("in_migrate")
    frappe.flags.in_migrate = True
    try:
        for path in files:
            import_file_by_path(str(path), force=True)
        if frappe.db.exists("DocType", "Desktop Icon"):
            for name in frappe.get_all("Desktop Icon", filters={"app": "tongjianyun"}, pluck="name"):
                frappe.db.set_value("Desktop Icon", name, "link", "/desk/tongjianyun/query-report/Tongjianyun%20Weekly%20Menu")
        for row in frappe.get_all("Scheduled Job Type", filters={"method": ["like", "tongjianyun.%"]}, fields=["name", "stopped"]):
            if not row.stopped:
                frappe.db.set_value("Scheduled Job Type", row.name, "stopped", 1)
        for row in frappe.get_all("Report", filters={"module": "Tongjianyun"}, fields=["name", "disabled"]):
            if row.name not in REPORTS and not row.disabled:
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
