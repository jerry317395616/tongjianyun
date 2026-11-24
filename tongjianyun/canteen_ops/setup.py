from pathlib import Path

import frappe

from tongjianyun.canteen_ops.common import ROLES


def ensure_roles():
    frappe.only_for("System Manager")
    for name in ROLES:
        if not frappe.db.exists("Role", name):
            frappe.get_doc({"doctype": "Role", "role_name": name, "desk_access": 1}).insert()


def install_project_fields():
    from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

    from tongjianyun.canteen_ops.term_projects import PROJECT_RESPONSIBLE

    create_custom_fields({"Project": [{
        "fieldname": PROJECT_RESPONSIBLE, "fieldtype": "Link", "options": "User",
        "label": "膳食项目负责人", "insert_after": "company", "module": "Tongjianyun",
        "read_only": 1, "no_copy": 1, "depends_on": f"eval:doc.{PROJECT_RESPONSIBLE}",
    }]})


def report_names():
    folder = Path(__file__).parents[1] / "tongjianyun" / "report"
    return tuple(
        " ".join(part.capitalize() for part in path.name.split("_"))
        for path in sorted(folder.glob("tongjianyun_canteen_*"))
        if path.name != "tongjianyun_canteen_staffing_analysis" and (path / f"{path.name}.json").is_file()
    )
