"""Related regression tests inside an initialized, read-only Frappe context.

Legacy health tests require bound frappe.db/flags even when methods are mocked.
Do not mistake plain-unittest context errors for application failures.
"""
import os
import unittest
from pathlib import Path
import frappe

frappe.init(site=os.environ.get("CLASSROOM_TEST_SITE", "child.myyr.top"), sites_path=str(Path.cwd() / "sites"))
frappe.connect()
try:
    frappe.set_user("Administrator")
    modules = ["test_classroom", "test_student_meals", "test_attendance_scope", "test_teacher_permissions",
               "test_health_registration", "test_director_dashboard", "test_campus_viewer"]
    suite = unittest.defaultTestLoader.loadTestsFromNames(["tongjianyun.tests." + module for module in modules])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
finally:
    frappe.db.rollback()
    frappe.destroy()
raise SystemExit(0 if result.wasSuccessful() else 1)
