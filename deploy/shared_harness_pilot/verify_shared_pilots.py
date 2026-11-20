"""Read-only pilot account and ORM isolation checks; emit counts, never student data."""
import json
import os
import frappe
from tongjianyun.teacher_permissions import assignment, is_scoped_teacher

os.chdir('/home/zyd/frappe/native-bench')
frappe.init(site='child.myyr.top', sites_path='/home/zyd/frappe/native-bench/sites')
frappe.connect(set_admin_as_user=False)
try:
    rows = []
    for account in ['harness.test.teacher.a@example.invalid', 'harness.test.teacher.b@example.invalid']:
        user = frappe.db.get_value('User', account, ['enabled', 'user_type'], as_dict=True)
        if not user:
            rows.append({'account': account, 'exists': False})
            continue
        frappe.set_user(account)
        groups, students = assignment(account)
        visible = frappe.get_list('Student', fields=['name'], limit_page_length=0)
        rows.append({'account': account, 'exists': True, 'enabled': user.enabled,
                     'user_type': user.user_type, 'teacher_scoped': is_scoped_teacher(account),
                     'groups': groups, 'assigned_students': len(students),
                     'visible_students': len(visible),
                     'out_of_scope_visible': len({r.name for r in visible} - set(students))})
    print(json.dumps(rows, ensure_ascii=False))
finally:
    frappe.db.rollback()
    frappe.destroy()
