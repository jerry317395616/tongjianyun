from __future__ import annotations

import frappe

from tongjianyun.education_integration import remove_removed_doctypes


def execute() -> None:
    remove_removed_doctypes()
    frappe.clear_cache()
