"""Install Tongjianyun roles for meal attendance management."""

import frappe


ROLES = [{"role_name": "Tongjianyun Business Operator", "role_text": "童健云业务操作", "desk_access": 1}]


def install():
    """Create roles if they don't exist."""
    for role_def in ROLES:
        if not frappe.db.exists("Role", role_def["role_name"]):
            role = frappe.new_doc("Role")
            role.role_name = role_def["role_name"]
            role.role_text = role_def["role_text"]
            role.desk_access = role_def["desk_access"]
            role.insert(ignore_permissions=True)
            frappe.db.commit()


# Hook: run on every start to ensure roles exist
def before_request():
    install()
