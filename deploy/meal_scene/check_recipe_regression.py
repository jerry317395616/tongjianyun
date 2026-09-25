"""Recipe and canvas regression suite in a rollback-only site context."""
import os
import sys
import unittest
from pathlib import Path
import frappe

if os.environ.get('MEAL_SCENE_SOURCE'):
    sys.path.insert(0,os.environ['MEAL_SCENE_SOURCE'])
frappe.init(site='child.myyr.top', sites_path=str(Path.cwd()/'sites'))
frappe.connect()
try:
    frappe.set_user('Administrator')
    modules=['test_recipe_week','test_meal_scene','test_recipe_revision','test_recipe_deletion_links',
             'test_recipe_execution','test_recipe_item_sync','test_recipe_procurement','test_recipe_product_decisions',
             'test_meal_views','test_meal_nutrition_view','test_business_views','test_meal_chat']
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(['tongjianyun.tests.'+m for m in modules]))
finally:
    frappe.db.rollback();frappe.destroy()
raise SystemExit(0 if result.wasSuccessful() else 1)
