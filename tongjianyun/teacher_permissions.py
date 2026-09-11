"""Teacher row restrictions shared by Desk, ORM permission checks and Harness reads.

Identity links are read internally for the authenticated framework user.
No endpoint accepts a caller-selected actor, and these hooks never grant roles.
"""
import frappe

MANAGERS = {"System Manager", "Education Manager", "Tongjianyun Business Operator", "Tongjianyun Business Operator"}
TEACHERS = {"Instructor", "Tongjianyun Business Operator"}
SUPPORTED = {"Student Group", "Student", "Student Attendance", "Student Leave Application"}


def is_scoped_teacher(user):
    if user == "Administrator":
        return False
    roles = set(frappe.get_roles(user))
    return bool(roles & TEACHERS) and not bool(roles & MANAGERS)


def assignment(user):
    """Resolve active identity links without recursing into permission-filtered queries."""
    employees = frappe.get_all("Employee", filters={"user_id": user, "status": "Active"}, pluck="name")
    if not employees:
        return [], []
    instructors = frappe.get_all("Instructor", filters={"employee": ["in", employees], "status": "Active"}, pluck="name")
    if not instructors:
        return [], []
    parents = frappe.get_all("Student Group Instructor", filters={"instructor": ["in", instructors], "parenttype": "Student Group", "parentfield": "instructors"}, pluck="parent")
    if not parents:
        return [], []
    groups = frappe.get_all("Student Group", filters={"name": ["in", sorted(set(parents))], "disabled": 0}, pluck="name")
    if not groups:
        return [], []
    students = frappe.get_all("Student Group Student", filters={"parent": ["in", groups], "parenttype": "Student Group", "parentfield": "students", "active": 1}, pluck="student")
    return groups, sorted(set(students))


def query_condition(user=None, doctype=None):
    """Return a Query Builder criterion; Frappe combines it with existing permissions."""
    user = user or frappe.session.user
    if doctype not in SUPPORTED or not is_scoped_teacher(user):
        return ""
    groups, students = assignment(user)
    values = groups if doctype == "Student Group" else students
    if not values:
        return "1=0"
    table = frappe.qb.DocType(doctype)
    if doctype in {"Student", "Student Group"}:
        return table.name.isin(values)
    # A pupil can have history in another class; both identifiers must match.
    return table.student.isin(students) & table.student_group.isin(groups)


def document_permission(doc, ptype=None, user=None, **kwargs):
    """Only narrow the framework's result, including direct document reads."""
    user = user or frappe.session.user
    if doc.doctype not in SUPPORTED or not is_scoped_teacher(user):
        return True
    groups, students = assignment(user)
    if doc.doctype == "Student Group":
        return doc.name in groups
    if doc.doctype == "Student":
        return doc.name in students
    return doc.get("student") in students and doc.get("student_group") in groups
