"""Operator-only concurrent ORM probe; exact fixture and redacted failure facts."""
import json
import os
import subprocess
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
import frappe
from tongjianyun import harness_administrator_approvals as service

os.chdir('/home/zyd/frappe/native-bench')
frappe.init(site='child.myyr.top', sites_path='/home/zyd/frappe/native-bench/sites')
frappe.connect(set_admin_as_user=False)
frappe.set_user('Administrator')
frappe.conf[service.WRITE_ENABLE_KEY] = 1  # This process only; never enables public writes.
name = None
try:
    if '--worker' in sys.argv:
        value = json.load(sys.stdin)
        try:
            result = service.confirm_preview('a' * 64, value['preview_id'], value['digest'])
            print(json.dumps({key: result.get(key) for key in ['state', 'replayed', 'error_type']}))
        except Exception as error:
            print(json.dumps({'error_type': type(error).__name__, 'locations': [
                {'file': Path(frame.filename).name, 'line': frame.lineno, 'function': frame.name}
                for frame in traceback.extract_tb(error.__traceback__)]}))
    else:
        name = 'TJY-HARNESS-CONCURRENCY-' + uuid4().hex[:12]
        service.business._meta('UOM')
        assert not frappe.db.exists('UOM', name)
        frappe.get_doc({'doctype': 'UOM', 'uom_name': name, 'description': 'before'}).insert()
        frappe.db.commit()
        preview = service.create_preview('a' * 64, 'update', 'UOM', name=name, changes={'description': 'after'})
        payload = json.dumps({key: preview[key] for key in ['preview_id', 'digest']})
        def run(_):
            result = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--worker'],
                input=payload, text=True, capture_output=True, timeout=35)
            return {'exit': result.returncode, 'result': json.loads(result.stdout)}
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(run, range(2)))
        print(json.dumps(replies))
        assert all(row['exit'] == 0 and row['result'].get('state') in {'succeeded', 'outcome_unknown'} for row in replies)
        assert sum(row['result'].get('replayed') is False for row in replies) == 1
        frappe.db.rollback()
        checks = {'updated': frappe.get_doc('UOM', name).description == 'after',
            'claims': frappe.db.count(service.AUDIT, {'tool_name': service.CLAIM_PREFIX + preview['preview_id']}),
            'results': frappe.db.count(service.AUDIT, {'tool_name': service.RESULT_PREFIX + preview['preview_id']})}
        print(json.dumps(checks))
        assert checks == {'updated': True, 'claims': 1, 'results': 1}
finally:
    frappe.db.rollback()
    if name is not None:
        frappe.delete_doc('UOM', name)
        frappe.db.commit()
    frappe.destroy()
