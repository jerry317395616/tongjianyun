"""Compatibility endpoints for the withdrawn experimental attendance workspaces.

Use Education Student Attendance / Student Leave Application and daily_meals.
These endpoints intentionally do not recreate the removed child DocType.
"""
import frappe


def _retired():
    raise frappe.ValidationError("This experimental workspace has been retired. Use Student Attendance and Daily Meal Confirmation.")


@frappe.whitelist()
def get_teacher_attendance_dashboard():
    return _retired()


@frappe.whitelist(methods=["POST"])
def save_student_status(changes=None):
    return _retired()


@frappe.whitelist(methods=["POST"])
def confirm_meal():
    return _retired()


@frappe.whitelist(methods=["POST"])
def close_day():
    return _retired()


@frappe.whitelist()
def get_kitchen_dashboard():
    return _retired()


@frappe.whitelist(methods=["POST"])
def confirm_prep():
    return _retired()


@frappe.whitelist()
def get_director_dashboard():
    return _retired()


@frappe.whitelist()
def get_finance_settlement(month=None):
    return _retired()


@frappe.whitelist(methods=["POST"])
def lock_month(month=None):
    return _retired()
