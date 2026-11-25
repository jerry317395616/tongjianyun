"""Transfer the child site's existing model ownership to Tongjianyun before uninstalling I-ONE Core."""

import frappe
from frappe.installer import get_app_owned_modules

SOURCE_APP = "ione_core"
TARGET_APP = "tongjianyun"
MODULES = ("I ONE AI", "I ONE Mobile")


def adopt():
    """Move metadata and callable paths in place. Existing document identities stay stable."""
    frappe.only_for("System Manager")
    installed = frappe.get_installed_apps()
    if TARGET_APP not in installed:
        frappe.throw("请先部署童健云。")
    if SOURCE_APP not in installed:
        return {"modules": [], "updated": 0}

    owner_modules = set(get_app_owned_modules(SOURCE_APP))
    if owner_modules - set(MODULES):
        frappe.throw("发现未纳入迁移的 IONE Core 模块，请核对。")

    module_docs = [frappe.get_doc("Module Def", module, for_update=True) for module in MODULES]
    for doc in module_docs:
        if doc.custom or doc.app_name not in (SOURCE_APP, TARGET_APP):
            frappe.throw(f"模块「{doc.name}」的归属与迁移要求不符。")

    updates = 0
    for doctype, fields in {
        "Flow Tool": ("import_path", "code"),
        "Custom HTML Block": ("script", "style", "html"),
        "Client Script": ("script",),
        "Server Script": ("script",),
    }.items():
        if not frappe.db.exists("DocType", doctype):
            continue
        for field in fields:
            for row in frappe.get_all(doctype, filters={field: ["like", "%ione_core%"]}, fields=["name", field]):
                value = row[field]
                mapped = value.replace("ione_core.", "tongjianyun.").replace("/assets/ione_core/", "/assets/tongjianyun/")
                if mapped != value:
                    frappe.db.set_value(doctype, row.name, field, mapped, update_modified=False)
                    updates += 1

    for row in frappe.get_all("Scheduled Job Type", filters={"method": ["like", "ione_core.%"]},
                              fields=["name", "method"]):
        method = row.method.replace("ione_core.", "tongjianyun.", 1)
        frappe.get_attr(method)
        if frappe.db.exists("Scheduled Job Type", {"method": method}):
            frappe.throw(f"定时任务 {method} 已存在，请核对调度设置。")
        frappe.db.set_value("Scheduled Job Type", row.name, "method", method, update_modified=False)
        updates += 1

    # The standard uninstall also handles Studio records by application, not module.
    if frappe.db.exists("DocType", "Studio App"):
        for name in frappe.get_all("Studio App", filters={"frappe_app": SOURCE_APP}, pluck="name"):
            frappe.db.set_value("Studio App", name, "frappe_app", TARGET_APP, update_modified=False)
            updates += 1

    for doc in module_docs:
        if doc.app_name == SOURCE_APP:
            frappe.db.set_value("Module Def", doc.name, "app_name", TARGET_APP, update_modified=False)

    frappe.clear_cache()
    return {"modules": list(MODULES), "updated": updates}
