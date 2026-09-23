"""Authenticated teacher classroom page; deliberately not a public dashboard."""
import frappe
from frappe.sessions import get_csrf_token
from tongjianyun.classroom import require_user

no_cache = 1
sitemap = 0


def get_context(context):
    if frappe.session.user == "Guest":
        frappe.local.flags.redirect_location = "/login?redirect-to=/tongjianyun-classroom"
        raise frappe.Redirect
    require_user()
    from tongjianyun.classroom import _groups
    from tongjianyun.workspace_entry import mark_private_response
    mark_private_response()
    workspace = frappe.form_dict.get("workspace")
    _groups(workspace)  # Validate the requested surface before rendering.
    context.no_cache = 1
    context.csrf_token = get_csrf_token()
    context.title = "班级管理 · 童健云"
