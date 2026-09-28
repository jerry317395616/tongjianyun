"""Narrow meal-manager role and its server-rendered app launcher view."""

from __future__ import annotations

import frappe


ROLE = "膳食管理员"
APP = "tongjianyun"
APP_TITLE = "童健云"
APP_ROUTE = "/tongjianyun-entry"
RECIPE_DOCTYPES = (
    "Tongjianyun Recipe",
    "Tongjianyun Recipe Dish",
    "Tongjianyun Recipe Ingredient",
)


def is_meal_manager(user: str | None = None, roles=None) -> bool:
    """Administrator retains the full system desktop even if it has every role."""
    user = user or frappe.session.user
    return user not in {"Administrator", "Guest"} and ROLE in set(roles if roles is not None else frappe.get_roles(user))


def limit_app_launcher(bootinfo) -> None:
    """Filter the server boot payload used by Frappe's Apps desktop."""
    if not is_meal_manager():
        return
    bootinfo.tongjianyun_meal_manager = True
    bootinfo.app_data = [app for app in (bootinfo.get("app_data") or []) if app.get("app_name") == APP]
    # Sites using the legacy Desktop Icons layout also receive a filtered list.
    # The desk bootstrap switches these users to the Apps renderer, which ignores
    # any older per-user layout containing unrelated icons.
    bootinfo.desktop_icons = [
        icon for icon in (bootinfo.get("desktop_icons") or [])
        if icon.get("icon_type") == "App"
        and (icon.get("app") == APP or (icon.get("label") == APP_TITLE and icon.get("link") == APP_ROUTE))
    ]


def install() -> None:
    """Create the role and recipe DocPerms, never assign it to a user."""
    if not frappe.db.exists("Role", ROLE):
        frappe.get_doc({
            "doctype": "Role", "role_name": ROLE, "desk_access": 1, "is_custom": 1,
        }).insert(ignore_permissions=True)

    from tongjianyun.education_integration import _ensure_permission

    for doctype in RECIPE_DOCTYPES:
        if frappe.db.exists("DocType", doctype):
            _ensure_permission(doctype, ROLE, "rwcd")
    frappe.clear_cache()
