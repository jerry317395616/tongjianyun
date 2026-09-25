"""Read-only installed-entry coverage, including authorization and route checks."""
import json
import os
import sys
from collections import Counter
from pathlib import Path

if os.environ.get('UNIFIED_BUSINESS_SOURCE'):
    sys.path.insert(0, os.environ['UNIFIED_BUSINESS_SOURCE'])
import frappe

frappe.init(site='child.myyr.top', sites_path=str(Path.cwd() / 'sites'))
frappe.connect()
try:
    frappe.set_user('Administrator')
    from tongjianyun.frappe_project_views import capability_inventory, entry_selection
    from tongjianyun.meal_views import get_view
    inventory = capability_inventory()
    failures, new_routes = [], 0
    for row in inventory['entries']:
        try:
            result = get_view(entry_selection(row['kind'], row['name'], {'day': '2026-09-25', 'meal': 'lunch'}))
            assert any(block['type'] == 'frappe_frame' for block in result['components'])
            if row['kind'] == 'doctype' and any(op['key'] == 'create' and op['available'] for op in row['capabilities']['operations']):
                created = get_view({'view': 'frappe_new', 'doctype': row['name'], 'day': '2026-09-25'})
                assert any(block.get('route', '').endswith('/new') for block in created['components'])
                new_routes += 1
        except Exception as error:
            failures.append({'kind': row['kind'], 'name': row['name'], 'error': str(error)[:160]})
    frappe.set_user('Guest')
    denied = []
    for choice in [{'view': 'frappe_new', 'doctype': 'UOM'}, {'view': 'business_blueprint', 'proposal_id': 'not-real'}]:
        try:
            get_view(choice)
            raise AssertionError('Guest accepted')
        except frappe.PermissionError:
            denied.append(choice['view'])
    summary = {'apps': dict(Counter(row['app'] for row in inventory['entries'])),
               'kinds': dict(Counter(row['kind'] for row in inventory['entries'])),
               'entries': inventory['entry_count'], 'new_form_routes': new_routes,
               'route_failures': failures, 'guest_denied': denied,
               'note': 'Metadata and route verification only; no record was created or workflow executed.'}
    print(json.dumps(summary, ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
