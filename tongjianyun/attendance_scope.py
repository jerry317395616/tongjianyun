"""Attendance scope is derived from the authenticated Frappe user, never request data."""
import frappe

MANAGERS = {"System Manager", "Education Manager", "Tongjianyun Business Operator", "Tongjianyun Business Operator"}


def is_manager():
    return frappe.session.user == "Administrator" or bool(MANAGERS.intersection(frappe.get_roles()))


def require_manager():
    if frappe.session.user == "Guest" or not is_manager():
        raise frappe.PermissionError("Whole-school confirmation requires an attendance manager")


def allowed_groups():
    """Intersect teacher assignment with Frappe's readable Student Groups."""
    if frappe.session.user == "Guest":
        raise frappe.PermissionError("Login required")
    filters = {"disabled": 0}
    if not is_manager():
        # Read only the current user's identity links; do not expose employee records.
        employees = frappe.get_all("Employee", filters={"user_id": frappe.session.user, "status": "Active"}, pluck="name")
        if not employees:
            return []
        instructors = frappe.get_all("Instructor", filters={"employee": ["in", employees], "status": "Active"}, pluck="name")
        if not instructors:
            return []
        groups = frappe.get_all("Student Group Instructor", filters={"instructor": ["in", instructors], "parenttype": "Student Group", "parentfield": "instructors"}, pluck="parent")
        if not groups:
            return []
        filters["name"] = ["in", sorted(set(groups))]
    return frappe.get_list("Student Group", filters=filters, pluck="name", limit_page_length=0)


def require_group(group, allowed):
    if group not in allowed:
        raise frappe.PermissionError("Student Group is outside your attendance scope")


def visible_confirmation(doc, allowed):
    """Do not return whole-school totals or experimental child data to teachers."""
    if is_manager():
        return doc.as_dict()
    return {
        "name": doc.name, "doctype": doc.doctype,
        "meal_date": doc.meal_date, "status": doc.status,
        "details": [row.as_dict() for row in doc.get("details", []) if row.student_group in allowed],
    }
