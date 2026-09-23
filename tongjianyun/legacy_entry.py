"""Compatibility navigation for teacher bookmarks; this module grants no rights.

The old Desk Page remains restricted to its existing roles. Teachers are sent
to the role-aware entry before its client-side permission screen is displayed.
"""
import frappe

from tongjianyun.workspace_entry import ENTRY, WORKBENCH, entry_model, mark_private_response, temporary_redirect


def is_teacher_only(model):
    profiles = model.get('profiles', [])
    return any(p.get('id') == 'teacher' for p in profiles) and not any(
        p.get('id') == 'business' and p.get('enabled') for p in profiles
    )


def redirect_legacy_teacher_page(context):
    """Native update_website_context hook, limited to one legacy GET/HEAD page.

    Do not redirect writes, API calls, other Desk pages or administrators.
    Query parameters do not choose the actor, grant access or supply a redirect.
    A teacher lacking a class gets the existing setup page, not another class.
    """
    request = getattr(frappe.local, 'request', None)
    if not request or request.method not in ('GET', 'HEAD') or request.path.rstrip('/') != WORKBENCH:
        return
    if frappe.session.user == 'Guest':
        return
    try:
        model = entry_model()
    except frappe.PermissionError:
        return
    if is_teacher_only(model):
        mark_private_response()
        temporary_redirect(ENTRY)
