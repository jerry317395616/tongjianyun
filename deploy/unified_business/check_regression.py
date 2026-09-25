"""Read-only site-context regressions; explicit site/path support isolated QA.

UNIFIED_BUSINESS_SITE and UNIFIED_BUSINESS_SITES_PATH are trusted deployment
inputs, not HTTP parameters. Legacy defaults remain for compatibility, but the
connection is always database-enforced READ ONLY before any test is loaded.
"""
import os
import sys
import unittest
from pathlib import Path

if os.environ.get('UNIFIED_BUSINESS_SOURCE'):
    sys.path.insert(0, os.environ['UNIFIED_BUSINESS_SOURCE'])
import frappe

def main():
    # Python 3.14 multiprocessing may import this file as __mp_main__. Starting
    # another site connection/test suite in that child recursively runs tests
    # instead of the isolated ledger target. Keep all execution under main.
    site = os.environ.get('UNIFIED_BUSINESS_SITE', 'child.myyr.top')
    sites_path = Path(os.environ.get('UNIFIED_BUSINESS_SITES_PATH', str(Path.cwd() / 'sites'))).resolve(strict=True)
    frappe.init(site=site, sites_path=str(sites_path))
    frappe.connect()
    try:
        frappe.db.sql('SET SESSION TRANSACTION READ ONLY')
        if frappe.db.sql('SELECT @@session.tx_read_only')[0][0] != 1:
            raise RuntimeError('Regression connection is not database-enforced read-only')
        frappe.flags.read_only = True
        frappe.set_user('Administrator')
        modules = ['test_extension_policy', 'test_business_blueprints', 'test_business_blueprints_v2', 'test_business_blueprint_workflow', 'test_meal_view_tool', 'test_frappe_project_views',
               'test_business_views', 'test_meal_views', 'test_meal_nutrition_view', 'test_meal_chat',
               'test_recipe_week', 'test_recipe_revision', 'test_recipe_deletion_links', 'test_student_meals',
               'test_classroom', 'test_attendance_scope', 'test_meal_scene', 'test_scene_access', 'test_workspace_entry',
               'test_stock_operations', 'test_stock_reconciliation', 'test_payables_acceptance_runner',
               'test_asset_history', 'test_business_agent_tools', 'test_business_agent_transport',
               'test_business_agent_tasks', 'test_business_agent_events', 'test_business_agent_authority',
               'test_business_chat', 'test_business_agent_worker', 'test_business_agent_reads',
               'test_business_agent_meal_reads', 'test_business_agent_writes',
               'test_business_agent_write_adapter', 'test_business_agent_execution',
               'test_business_agent_catalog']
        result = unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(
            ['tongjianyun.tests.' + name for name in modules]))
    finally:
        frappe.db.rollback()
        frappe.destroy()
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
