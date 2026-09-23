"""Authenticated full-scene meal workspace, schema-free."""
import frappe
from frappe.sessions import get_csrf_token
from tongjianyun.workspace_entry import mark_private_response, temporary_redirect
from tongjianyun.meal_scene import require_access

no_cache = 1
sitemap = 0


def get_context(context):
    mark_private_response()
    if frappe.session.user == 'Guest':
        temporary_redirect('/login?redirect-to=/tongjianyun-meal-scene')
    require_access()
    context.no_cache = 1
    context.csrf_token = get_csrf_token()
