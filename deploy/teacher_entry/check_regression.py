"""Run teacher/classroom unit tests with a bound Frappe context, rollback only."""
import os
from pathlib import Path
import sys
import unittest
import frappe

if os.environ.get("TEACHER_ENTRY_SOURCE"):
    sys.path.insert(0, os.environ["TEACHER_ENTRY_SOURCE"])
frappe.init(site=os.environ.get("CLASSROOM_TEST_SITE", "child.myyr.top"), sites_path=str(Path.cwd()/"sites"))
frappe.connect()
try:
    frappe.set_user("Administrator")
    modules = ["test_legacy_entry", "test_workspace_entry", "test_classroom", "test_student_meals", "test_attendance_scope", "test_teacher_permissions", "test_health_registration", "test_director_dashboard", "test_campus_viewer"]
    suite = unittest.defaultTestLoader.loadTestsFromNames(["tongjianyun.tests."+m for m in modules])
    result = unittest.TextTestRunner(verbosity=1).run(suite)
finally:
    frappe.db.rollback()
    frappe.destroy()
raise SystemExit(0 if result.wasSuccessful() else 1)
