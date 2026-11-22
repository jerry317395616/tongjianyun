from pathlib import Path

import frappe

from tongjianyun.canteen_ops.common import ROLES


def ensure_roles():
    frappe.only_for("System Manager")
    for name in ROLES:
        if not frappe.db.exists("Role", name):
            frappe.get_doc({"doctype": "Role", "role_name": name, "desk_access": 1}).insert()


def report_names():
    folder = Path(__file__).parents[1] / "tongjianyun" / "report"
    return tuple(
        " ".join(part.capitalize() for part in path.name.split("_"))
        for path in sorted(folder.glob("tongjianyun_canteen_*")) if path.name != "tongjianyun_canteen_staffing_analysis"
    )
