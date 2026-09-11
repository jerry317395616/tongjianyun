"""Read-only campus viewer. Frappe normalizes HTML hyphens to module underscores."""
import frappe
from tongjianyun.business_access import ROLE

no_cache = 1
sitemap = 0


def get_context(context):
    user = frappe.session.user
    if user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/tongjianyun-campus"
        raise frappe.Redirect
    if not frappe.db.get_value("User", user, "enabled"):
        raise frappe.PermissionError("账号已停用")
    if user != "Administrator" and ROLE not in frappe.get_roles(user):
        raise frappe.PermissionError("需要童健云业务操作权限")
    context.no_cache = 1
    context.title = "临潼区幼儿园 · 园区数字孪生"
