"""Run meal-scene and related tests in the existing bound rollback-only context."""
import os
import sys
from pathlib import Path
import unittest
import frappe

source=os.environ.get('MEAL_SCENE_SOURCE')
if source:sys.path.insert(0,source)
frappe.init(site='child.myyr.top',sites_path=str(Path.cwd()/'sites'))
frappe.connect()
try:
    frappe.set_user('Administrator')
    modules=['test_meal_scene','test_workspace_entry','test_legacy_entry','test_classroom','test_student_meals',
        'test_attendance_scope','test_teacher_permissions','test_health_registration','test_director_dashboard','test_campus_viewer']
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(['tongjianyun.tests.'+m for m in modules]))
finally:
    frappe.db.rollback();frappe.destroy()
raise SystemExit(0 if result.wasSuccessful() else 1)
