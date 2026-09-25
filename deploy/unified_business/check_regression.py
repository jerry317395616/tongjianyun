"""Site-context unit regressions; no schema migration or live business writes."""
import os
import sys
import unittest
from pathlib import Path

if os.environ.get('UNIFIED_BUSINESS_SOURCE'):
    sys.path.insert(0, os.environ['UNIFIED_BUSINESS_SOURCE'])
import frappe

frappe.init(site='child.myyr.top', sites_path=str(Path.cwd() / 'sites'))
frappe.connect()
try:
    frappe.set_user('Administrator')
    modules = ['test_extension_policy', 'test_business_blueprints', 'test_frappe_project_views',
               'test_business_views', 'test_meal_views', 'test_meal_nutrition_view', 'test_meal_chat',
               'test_recipe_week', 'test_recipe_revision', 'test_recipe_deletion_links', 'test_student_meals']
    result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(
        ['tongjianyun.tests.' + name for name in modules]))
finally:
    frappe.db.rollback()
    frappe.destroy()
raise SystemExit(0 if result.wasSuccessful() else 1)
