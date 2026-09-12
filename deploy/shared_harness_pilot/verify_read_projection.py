"""Read-only regression against the real schema; print counts, never student data."""
import os
import sys
import json

os.chdir('/home/zyd/frappe/native-bench')
sys.path.insert(0, '/home/zyd/frappe/native-bench/apps/tongjianyun/deploy/shared_harness_pilot')
import frappe
from administrator_worker import execute

frappe.init(site='child.myyr.top', sites_path='/home/zyd/frappe/native-bench/sites')
try:
    frappe.connect(set_admin_as_user=False)
    frappe.set_user('Administrator')
    def query(op, **args):
        return execute({'operation': 'frappe_' + op, 'arguments': args})
    dt = 'Tongjianyun Recipe Dish'
    catalog = query('list_doctypes', search=dt, limit=1)
    assert catalog['rows'][0]['doctype'] == dt
    assert query('list_doctypes', search='User')['rows'] == []
    assert query('list_doctypes', limit=101)['error']['code'] == 'invalid_query'
    assert query('list_doctypes', search={'sql': 'select'})['error']['code'] == 'invalid_query'
    meta = query('describe_doctype', doctype=dt)
    assert next(f for f in meta['fields'] if f['fieldname'] == 'recipe')['options'] == 'Tongjianyun Recipe'
    today = meta['query_context']['today']
    rows = query('list_documents', doctype=dt, filters={'meal_date': today}, limit=100)
    assert 'dish_name' in rows['selected_fields']
    related = set()
    for row in rows['rows']:
        detail = query('get_document', doctype=dt, name=row['name'])
        assert {'dish_name', 'meal_slot', 'meal_label', 'recipe'} <= detail['document'].keys()
        assert detail['document']['dish_name'] == row['dish_name']
        related.add(detail['document']['recipe'])
        explicit = query('get_document', doctype=dt, name=row['name'], fields=['name'])
        assert set(explicit['document']) == {'name'}
    for name in related:
        recipe = query('get_document', doctype='Tongjianyun Recipe', name=name,
                       fields=['title', 'workflow_status', 'is_deleted'])
        assert recipe['document'] is not None
    for args in [dict(fields=['password']), dict(fields=['name; SELECT 1']), dict(limit=200),
                 dict(filters={'meal_date': ['!=', today]}), dict(order_by='dish_name desc')]:
        assert query('list_documents', doctype=dt, **args)['error']['code'] == 'invalid_query'
    assert query('describe_doctype', doctype='User')['error']['code'] == 'access_denied'
    count = query('list_documents', doctype='Student', fields=['name'], limit=1)
    assert count['total_count'] == frappe.db.count('Student')
    assert count['page_count'] <= 1
    frappe.set_user('Guest')
    try:
        query('list_documents', doctype='Student')
        raise AssertionError('Guest admitted to Administrator worker')
    except PermissionError:
        pass
    print(json.dumps({'result': 'passed', 'today': today, 'dish_count': len(rows['rows']),
                      'related_recipes': len(related), 'student_total': count['total_count'],
                      'projection_and_permission_checks': 'passed'}, ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
