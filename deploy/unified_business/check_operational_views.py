"""Read-only production view check. No personal rows are printed or retained."""
import json
import os
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

if os.environ.get('UNIFIED_BUSINESS_SOURCE'):
    sys.path.insert(0, os.environ['UNIFIED_BUSINESS_SOURCE'])
import frappe
from frappe.utils import getdate, today

sites = Path('/home/zyd/frappe/native-bench/sites')
os.chdir(sites)
frappe.init(site='child.myyr.top', sites_path=str(sites))
frappe.connect()
try:
    frappe.set_user('Administrator')
    from tongjianyun.meal_views import get_view, _groups
    watched = ('Student Attendance', 'Student Leave Application',
               'Tongjianyun Class Meal Confirmation', 'Tongjianyun Daily Meal Confirmation')
    before = {dt: frappe.db.count(dt) for dt in watched}
    sql = frappe.db.sql

    def only_read(query, *args, **kwargs):
        assert str(query).lstrip().split(None, 1)[0].lower() in {'select', 'show', 'describe', 'explain'}, 'View attempted a write'
        return sql(query, *args, **kwargs)

    checked = []
    with patch.object(frappe.db, 'sql', side_effect=only_read), \
         patch.object(frappe.db, 'commit', side_effect=AssertionError('View attempted commit')):
        groups = _groups()
        for group in groups:
            for view, component in (('classroom_day', 'attendance_register'), ('meal_counts', 'meal_register')):
                value = get_view({'view': view, 'group': group.name, 'day': today(), 'meal': 'lunch'})
                form = next(block for block in value['components'] if block['type'] == component)
                assert form['student_group'] == group.name
                assert form['day'] == today() and isinstance(form['revision'], str)
                assert all(row.get('student_name') not in json.dumps(value['summary'], ensure_ascii=False)
                           for row in form['rows'] if row.get('student_name'))
                checked.append({'view': view, 'row_count': len(form['rows']), 'editable': form['editable']})
                future = get_view({'view': view, 'group': group.name,
                                  'day': str(getdate(today()) + timedelta(days=1)), 'meal': 'lunch'})
                assert not next(block for block in future['components'] if block['type'] == component)['editable']
        assert before == {dt: frappe.db.count(dt) for dt in watched}
    print(json.dumps({'checked': checked, 'record_counts_unchanged': True, 'view_sql_read_only': True,
                      'future_actual_forms_disabled': True, 'personal_rows_not_printed': True}, ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
