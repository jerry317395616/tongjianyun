from __future__ import annotations

import frappe
from education.education.doctype.student.student import Student
from frappe.permissions import add_permission, update_permission_property
from frappe.utils import cint


REMOVED_DOCTYPES = (
    "Tongjianyun Child",
    "Tongjianyun Class",
    "Tongjianyun Data Record",
    "Tongjianyun Dish Catalog",
    "Tongjianyun Ingredient Spec",
    "Tongjianyun Food Category",
    "Tongjianyun Food Category Mapping",
    "Tongjianyun Nutrition Standard",
    "Tongjianyun Class Meal Setting",
    "Tongjianyun Special Diet",
    "Tongjianyun Growth Measurement",
    "Tongjianyun Child Health Profile",
    "Tongjianyun Food Sample",
    "Tongjianyun Food Supplier",
    "Tongjianyun Food Trace Event",
    "Tongjianyun Meal Nutrition",
)

ROLE_PERMISSIONS = {'Tongjianyun Business Operator': {'Academic Term': 'crw',
                                   'Academic Year': 'crw',
                                   'Data Import': 'crw',
                                   'Guardian': 'crw',
                                   'Instructor': 'crw',
                                   'Program': 'crw',
                                   'Program Enrollment': 'crw',
                                   'Student': 'crw',
                                   'Student Attendance': 'crw',
                                   'Student Group': 'crw',
                                   'Student Leave Application': 'crw',
                                   'Tongjianyun Daily Meal Adjustment': 'cdrw',
                                   'Tongjianyun Daily Meal Confirmation': 'crw'}}

OWNER_SCOPED_PERMISSIONS = {
    ("Tongjianyun Business Operator", "Data Import"),
}

TONGJIANYUN_ROLE_PERMISSIONS = {'Tongjianyun Business Operator': {'Tongjianyun Daily Meal Adjustment': 'crw',
                                   'Tongjianyun Daily Meal Confirmation': 'crw',
                                   'Tongjianyun Food Purchase': 'cdrw',
                                   'Tongjianyun Recipe': 'cdrw',
                                   'Tongjianyun Recipe Dish': 'cdrw',
                                   'Tongjianyun Recipe Ingredient': 'cdrw'}}


class TongjianyunStudent(Student):
    """Education Student without automatic ERP customer creation.

    Kindergarten children are operational master data, not selling parties.
    A Customer can still be created explicitly if fee management is enabled later.
    """

    def validate(self):
        super().validate()
        self._validate_id_number()

    def _validate_id_number(self):
        from tongjianyun.student_identity import validate_id_number

        error = validate_id_number(self.id_number)
        if error:
            frappe.throw(f"身份证号不合法：{error}")

    def on_update(self):
        return None

    def validate_user(self):
        if not self.student_email_id:
            self.user = None
            return
        super().validate_user()


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def fetch_students_for_group(doctype, txt, searchfield, start, page_len, filters):
    """Let kindergarten classes select enabled students directly.

    The standard Education query only returns submitted Program Enrollment
    records. Tongjianyun treats the Student Group itself as the class roster,
    so requiring a separate enrollment record makes initial class setup
    impossible after importing students.
    """
    frappe.has_permission("Student", "read", throw=True)

    filters = frappe._dict(frappe.parse_json(filters) or {})
    current_students = []
    if filters.get("student_group"):
        current_students = frappe.get_all(
            "Student Group Student",
            filters={"parent": filters.student_group},
            pluck="student",
        )

    student = frappe.qb.DocType("Student")
    search_text = f"%{txt or ''}%"
    query = (
        frappe.qb.from_(student)
        .select(student.name, student.student_name)
        .where(student.enabled == 1)
        .where(
            (student.name.like(search_text))
            | (student.student_name.like(search_text))
        )
        .orderby(student.student_name)
        .orderby(student.name)
        .limit(cint(page_len) or 20)
        .offset(cint(start))
    )
    if current_students:
        query = query.where(student.name.notin(current_students))

    return query.run()


@frappe.whitelist()
def get_unassigned_students_for_group(
    academic_year,
    group_based_on=None,
    academic_term=None,
    program=None,
    batch=None,
    student_category=None,
    course=None,
):
    """Return enabled students not assigned to another active class this year.

    Education's standard bulk action only returns students from submitted
    Program Enrollment documents. Kindergarten classes use Student Group as
    the roster itself, so the Tongjianyun action deliberately works from the
    enabled Student master instead.
    """
    frappe.has_permission("Student", "read", throw=True)
    frappe.has_permission("Student Group", "write", throw=True)

    active_groups = frappe.get_all(
        "Student Group",
        filters={"academic_year": academic_year, "disabled": 0},
        pluck="name",
    )
    assigned_students = set()
    if active_groups:
        assigned_students = set(
            frappe.get_all(
                "Student Group Student",
                filters={
                    "parent": ["in", active_groups],
                    "parenttype": "Student Group",
                    "active": 1,
                },
                pluck="student",
            )
        )

    students = frappe.get_list(
        "Student",
        filters={"enabled": 1},
        fields=["name as student", "student_name"],
        order_by="student_name asc, name asc",
        limit_page_length=0,
    )
    return [
        {**student, "active": 1}
        for student in students
        if student.student not in assigned_students
    ]


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
    remove_removed_doctypes()
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
            _ensure_permission(
                doctype,
                role_name,
                access,
                if_owner=(role_name, doctype) in OWNER_SCOPED_PERMISSIONS,
            )


def _ensure_permission(
    doctype: str, role: str, access: str, *, if_owner: bool = False
) -> None:
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
        "if_owner": if_owner,
    }
    for property_name, enabled in properties.items():
        update_permission_property(doctype, role, 0, property_name, int(enabled))


def remove_removed_doctypes() -> None:
    for doctype in REMOVED_DOCTYPES:
        if frappe.db.exists("DocType", doctype):
            frappe.delete_doc(
                "DocType",
                doctype,
                force=True,
                ignore_permissions=True,
                ignore_missing=True,
            )
        if frappe.db.table_exists(doctype, cached=False):
            frappe.db.sql_ddl(f"DROP TABLE IF EXISTS `tab{doctype}`")
