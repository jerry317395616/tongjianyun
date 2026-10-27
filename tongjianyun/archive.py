"""Read-only controller for retained history; no operational legacy endpoints."""
import frappe
from frappe.model.document import Document

LEGACY_DOCTYPES = ('Tongjianyun Class Meal Confirmation', 'Tongjianyun Teacher Face', 'Tongjianyun Video Event', 'Tongjianyun Video Batch', 'Tongjianyun Video Device', 'Tongjianyun Student Health', 'Tongjianyun Student Meal Row', 'Tongjianyun Recipe Day', 'Tongjianyun Nutrient Formula', 'Tongjianyun Nutrition Rule Set', 'Tongjianyun Nutrition Rule Revision', 'Tongjianyun Daily Meal Adjustment', 'Tongjianyun Daily Meal Confirmation', 'Tongjianyun Daily Meal Confirmation Row', 'Tongjianyun Recipe Ingredient', 'Tongjianyun Recipe Dish', 'Tongjianyun Recipe', 'Tongjianyun Meal Attendance', 'Tongjianyun Meal Attendance Row')

def deny_write(doc=None, method=None, *args, **kwargs):
    frappe.throw("童健云旧业务已停用，历史记录仅归档保留。请通过 ERP 办理新业务。", frappe.PermissionError)

class ReadOnlyArchive(Document):
    # Guard the actual write entry points as well as lifecycle events. A caller's
    # ignore_validate/ignore_permissions flags cannot turn history into live data.
    save = deny_write
    insert = deny_write
    delete = deny_write
    submit = deny_write
    cancel = deny_write
    db_insert = deny_write
    db_update = deny_write
    before_insert = deny_write
    before_validate = deny_write
    validate = deny_write
    before_submit = deny_write
    before_cancel = deny_write
    before_update_after_submit = deny_write
    on_trash = deny_write

def archive_reader(user):
    return user == "Administrator" or "System Manager" in frappe.get_roles(user)

def query_condition(user=None, doctype=None):
    return "" if archive_reader(user or frappe.session.user) else "1=0"

def document_permission(doc, ptype=None, user=None, **kwargs):
    return ptype in (None, "read", "report", "export", "print") and archive_reader(user or frappe.session.user)
