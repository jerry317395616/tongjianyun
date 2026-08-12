from __future__ import annotations

import frappe
from education.education.doctype.student.student import Student
from frappe.permissions import add_permission, update_permission_property


LEGACY_DOCTYPES = ("Tongjianyun Child", "Tongjianyun Class")

ROLE_PERMISSIONS = {
    "Tongjianyun Director": {
        "Student": "rwc",
        "Guardian": "rwc",
        "Student Group": "rwc",
        "Instructor": "rwc",
        "Academic Year": "rwc",
        "Academic Term": "rwc",
        "Program": "rwc",
        "Program Enrollment": "rwc",
        "Student Attendance": "rwc",
        "Student Leave Application": "rwc",
    },
    "Tongjianyun Academic": {
        "Student": "rwc",
        "Guardian": "rwc",
        "Student Group": "rwc",
        "Instructor": "rwc",
        "Academic Year": "rwc",
        "Academic Term": "rwc",
        "Program": "rwc",
        "Program Enrollment": "rwc",
    },
    "Tongjianyun Teacher": {
        "Student": "r",
        "Guardian": "r",
        "Student Group": "r",
        "Student Attendance": "rwc",
        "Student Leave Application": "rwc",
        "Tongjianyun Daily Meal Confirmation": "rwc",
        "Tongjianyun Daily Meal Adjustment": "rwcd",
    },
    "Tongjianyun Health": {
        "Student": "r",
        "Guardian": "r",
        "Student Group": "r",
    },
    "Tongjianyun Nutrition": {
        "Student": "r",
        "Student Group": "r",
    },
    "Tongjianyun Kitchen": {
        "Student Group": "r",
    },
    "Tongjianyun Procurement": {
        "Student Group": "r",
    },
    "Tongjianyun Food Safety": {
        "Student Group": "r",
    },
}

TONGJIANYUN_ROLE_PERMISSIONS = {
    "Tongjianyun Director": {
        "Tongjianyun Child Health Profile": "r",
        "Tongjianyun Growth Measurement": "r",
        "Tongjianyun Special Diet": "r",
        "Tongjianyun Class Meal Setting": "r",
        "Tongjianyun Daily Meal Confirmation": "r",
        "Tongjianyun Daily Meal Adjustment": "r",
        "Tongjianyun Recipe": "r",
        "Tongjianyun Recipe Dish": "r",
        "Tongjianyun Recipe Ingredient": "r",
        "Tongjianyun Food Purchase": "r",
        "Tongjianyun Food Supplier": "r",
        "Tongjianyun Food Sample": "r",
        "Tongjianyun Food Trace Event": "r",
    },
    "Tongjianyun Health": {
        "Tongjianyun Child Health Profile": "rwcd",
        "Tongjianyun Growth Measurement": "rwcd",
        "Tongjianyun Special Diet": "rwcd",
    },
    "Tongjianyun Nutrition": {
        "Tongjianyun Child Health Profile": "r",
        "Tongjianyun Special Diet": "rwc",
        "Tongjianyun Class Meal Setting": "rwcd",
        "Tongjianyun Daily Meal Confirmation": "rwc",
        "Tongjianyun Daily Meal Adjustment": "rwc",
        "Tongjianyun Recipe": "rwcd",
        "Tongjianyun Recipe Dish": "rwcd",
        "Tongjianyun Recipe Ingredient": "rwcd",
    },
    "Tongjianyun Kitchen": {
        "Tongjianyun Special Diet": "r",
        "Tongjianyun Daily Meal Confirmation": "r",
        "Tongjianyun Recipe": "r",
        "Tongjianyun Recipe Dish": "r",
        "Tongjianyun Recipe Ingredient": "r",
        "Tongjianyun Food Sample": "rwc",
    },
    "Tongjianyun Procurement": {
        "Tongjianyun Food Purchase": "rwcd",
        "Tongjianyun Food Supplier": "rwcd",
    },
    "Tongjianyun Food Safety": {
        "Tongjianyun Food Purchase": "r",
        "Tongjianyun Food Supplier": "r",
        "Tongjianyun Food Sample": "rwcd",
        "Tongjianyun Food Trace Event": "rwcd",
    },
}


class TongjianyunStudent(Student):
    """Education Student without automatic ERP customer creation.

    Kindergarten children are operational master data, not selling parties.
    A Customer can still be created explicitly if fee management is enabled later.
    """

    def on_update(self):
        return None

    def validate_user(self):
        if not self.student_email_id:
            self.user = None
            return
        super().validate_user()


def before_migrate() -> None:
    for role_name in set(ROLE_PERMISSIONS) | set(TONGJIANYUN_ROLE_PERMISSIONS):
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc(
                {"doctype": "Role", "role_name": role_name, "desk_access": 1}
            ).insert(ignore_permissions=True)


def install() -> None:
    if "education" not in frappe.get_installed_apps():
        frappe.throw("Tongjianyun requires the Education app.")

    _configure_student_master()
    _install_roles_and_permissions()
    _remove_legacy_doctypes()
    frappe.clear_cache()


def _configure_student_master() -> None:
    if frappe.db.exists("DocType", "Education Settings"):
        frappe.db.set_single_value("Education Settings", "user_creation_skip", 1)

    name = "Student-student_email_id-reqd"
    if frappe.db.exists("Property Setter", name):
        setter = frappe.get_doc("Property Setter", name)
    else:
        setter = frappe.new_doc("Property Setter")
        setter.name = name
    setter.update(
        {
            "doc_type": "Student",
            "field_name": "student_email_id",
            "doctype_or_field": "DocField",
            "property": "reqd",
            "property_type": "Check",
            "value": "0",
        }
    )
    setter.save(ignore_permissions=True)


def _install_roles_and_permissions() -> None:
    before_migrate()
    all_permissions = {
        role: {**ROLE_PERMISSIONS.get(role, {}), **TONGJIANYUN_ROLE_PERMISSIONS.get(role, {})}
        for role in set(ROLE_PERMISSIONS) | set(TONGJIANYUN_ROLE_PERMISSIONS)
    }
    for role_name, permissions in all_permissions.items():
        if not frappe.db.exists("Role", role_name):
            frappe.get_doc(
                {"doctype": "Role", "role_name": role_name, "desk_access": 1}
            ).insert(ignore_permissions=True)
        for doctype, access in permissions.items():
            if not frappe.db.exists("DocType", doctype):
                continue
            _ensure_permission(doctype, role_name, access)


def _ensure_permission(doctype: str, role: str, access: str) -> None:
    filters = {"parent": doctype, "role": role, "permlevel": 0}
    if not frappe.db.exists("Custom DocPerm", filters):
        add_permission(doctype, role, 0)
    properties = {
        "read": "r" in access,
        "write": "w" in access,
        "create": "c" in access,
        "delete": "d" in access,
        "print": "r" in access,
        "report": "r" in access,
        "export": "r" in access,
    }
    for property_name, enabled in properties.items():
        update_permission_property(doctype, role, 0, property_name, int(enabled))


def _remove_legacy_doctypes() -> None:
    for doctype in LEGACY_DOCTYPES:
        if not frappe.db.exists("DocType", doctype):
            continue
        frappe.delete_doc(
            "DocType",
            doctype,
            force=True,
            ignore_permissions=True,
            ignore_missing=True,
        )


def get_student_dashboard(data=None) -> dict:
    data = data or {"fieldname": "student", "transactions": []}
    data.setdefault("fieldname", "student")
    data.setdefault("transactions", [])
    data["transactions"].append(
        {
            "label": "童健云健康",
            "items": [
                "Tongjianyun Child Health Profile",
                "Tongjianyun Growth Measurement",
                "Tongjianyun Special Diet",
            ],
        }
    )
    return data
