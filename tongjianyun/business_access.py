"""Administrator-run, explicit-target business permission profile installation.

No public endpoint, schema changes, automatic account discovery or transaction commit.
Existing framework roles and permission rows are preserved.
"""
import frappe

ROLE = "Tongjianyun Business Operator"
PROFILE = "童健云业务操作"
BACKING = ("I-ONE Agent User",)
BUSINESS = {
    "Student", "Student Group", "Guardian", "Instructor", "Academic Year", "Academic Term",
    "Program", "Program Enrollment", "Student Attendance", "Student Leave Application",
    "Material Request", "Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry",
    "Stock Entry", "Supplier", "Supplier Group", "Item", "Item Group", "Item Price",
    "Price List", "Address", "Contact", "Batch", "Comment",
}
REFERENCE = {
    "Company", "Warehouse", "Account", "Cost Center", "Fiscal Year", "Mode of Payment",
    "Bank", "Bank Account", "Currency", "Currency Exchange", "UOM", "Country", "Gender",
    "Territory", "Payment Terms Template", "Payment Term", "Terms and Conditions",
    "Purchase Taxes and Charges Template", "Tax Category", "Tax Withholding Category",
    "Stock Settings", "Buying Settings", "Accounts Settings", "Item Variant Settings",
}
DENIED = {
    "User", "Role", "Role Profile", "User Permission", "DocType", "Custom Field",
    "Property Setter", "Custom DocPerm", "Server Script", "Client Script", "System Settings",
    "Accounts Settings", "Buying Settings", "Stock Settings", "Item Variant Settings",
    "Subscription Settings", "POS Settings", "South Africa VAT Settings", "Company",
}
BITS = ("read", "write", "create", "delete", "submit", "cancel", "amend", "report", "export", "print", "email", "select")


def _admin():
    if frappe.session.user != "Administrator":
        raise frappe.PermissionError("Only Administrator may install the business profile")


def plan():
    _admin()
    grants = {}
    names = BUSINESS | REFERENCE | set(frappe.get_all("DocType", filters={"name": ["like", "Tongjianyun%"], "istable": 0}, pluck="name"))
    for name in sorted(names):
        if not frappe.db.exists("DocType", name):
            continue
        meta = frappe.get_meta(name)
        if meta.istable:
            continue
        rows = [p for p in meta.permissions if p.permlevel == 0 and p.role != ROLE]
        values = {bit: int(any(p.get(bit) for p in rows)) for bit in BITS}
        if name in REFERENCE:
            values = {bit: int(bit in {"read", "select"}) for bit in BITS}
        if name == "Comment":
            values = {bit: int(bit in {"read", "create"}) for bit in BITS}
        if values["read"]:
            grants[name] = values
    return grants


def snapshot(users):
    _admin()
    grants = plan()
    return {
        "users": {user: {"roles": [r.role for r in frappe.get_doc("User", user).roles],
                         "profiles": [r.role_profile for r in frappe.get_doc("User", user).role_profiles]}
                  for user in users},
        "custom_permissions": {dt: [dict(r) for r in frappe.get_all("Custom DocPerm", filters={"parent": dt}, fields=["*"])] for dt in grants},
        "role_existed": bool(frappe.db.exists("Role", ROLE)),
        "profile_existed": bool(frappe.db.exists("Role Profile", PROFILE)),
        "grants": grants,
    }


def install(users):
    _admin()
    if not users or len(users) != len(set(users)):
        raise ValueError("Explicit unique users required")
    docs = [frappe.get_doc("User", user) for user in users]
    for doc in docs:
        if doc.name in {"Administrator", "Guest"} or not doc.enabled or doc.user_type != "System User":
            raise ValueError("Only explicitly selected enabled internal accounts are supported")
    grants = plan()
    if not frappe.db.exists("Role", ROLE):
        frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1, "is_custom": 1}).insert()
    from frappe.permissions import setup_custom_perms
    from frappe.core.doctype.doctype.doctype import validate_permissions_for_doctype
    for dt, values in grants.items():
        setup_custom_perms(dt)
        found = frappe.db.get_value("Custom DocPerm", {"parent": dt, "role": ROLE, "permlevel": 0, "if_owner": 0})
        perm = frappe.get_doc("Custom DocPerm", found) if found else frappe.get_doc({
            "doctype": "Custom DocPerm", "parent": dt, "parenttype": "DocType", "parentfield": "permissions",
            "role": ROLE, "permlevel": 0, "if_owner": 0})
        perm.update(values)
        perm.share = 0
        perm.save()
        validate_permissions_for_doctype(dt)
    profile = frappe.get_doc("Role Profile", PROFILE) if frappe.db.exists("Role Profile", PROFILE) else frappe.get_doc({"doctype": "Role Profile", "role_profile": PROFILE})
    profile.set("roles", [{"role": role} for role in (ROLE, *BACKING)])
    profile.save()
    for doc in docs:
        doc.set("role_profiles", [{"role_profile": PROFILE}])
        doc.role_profile_name = None
        doc.save()
        frappe.clear_cache(user=doc.name)
    return {"users": users, "profile": PROFILE, "permission_doctypes": len(grants)}


def verify(users):
    _admin()
    results = {}
    critical = {"Tongjianyun Recipe": ("read", "write", "create"),
                "Student": ("read", "write", "create"), "Student Group": ("read", "write", "create"),
                "Item": ("read", "write", "create"), "Item Group": ("read", "write", "create"),
                "Item Price": ("read", "write", "create")}
    critical.update({dt: ("read", "write", "create", "submit") for dt in
                     ("Material Request", "Purchase Order", "Purchase Receipt", "Purchase Invoice", "Payment Entry")})
    for user in users:
        frappe.set_user(user)
        try:
            for dt, actions in critical.items():
                for action in actions:
                    assert frappe.has_permission(dt, action), (user, dt, action, "required")
            for dt in DENIED:
                if not frappe.db.exists("DocType", dt):
                    continue
                for action in ("write", "create", "delete"):
                    # Frappe shares a user's own profile with them for personal settings.
                    assert not frappe.has_permission(dt, action, ignore_share_permissions=True), (user, dt, action, "forbidden")
            for other in users:
                if other != user:
                    assert not frappe.has_permission("User", "write", doc=other), (user, other, "account administration")
            roles = set(frappe.get_roles())
            assert not roles.intersection({"System Manager", "Script Manager", "Academics User", "Accounts Manager", "I-ONE Agent Manager"})
            results[user] = "business allowed; system administration denied"
        finally:
            frappe.set_user("Administrator")
    assert frappe.has_permission("User", "write") and frappe.has_permission("System Settings", "write")
    return results
