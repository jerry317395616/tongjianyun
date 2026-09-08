"""Production acceptance on one isolated UOM, deleted afterwards; retain audit evidence.

No existing student, meal or finance record is modified. Output contains only
check results. Cookies and signed handoffs stay in process memory/private pipes.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from uuid import uuid4

import frappe
from frappe.installer import update_site_config
from ione_core import harness_auth
from tongjianyun import harness_administrator_approvals as approval
from accept_live_http import request


def main():
    os.chdir('/home/zyd/frappe/native-bench')
    frappe.init(site='child.myyr.top', sites_path='/home/zyd/frappe/native-bench/sites')
    frappe.connect(set_admin_as_user=False)
    frappe.set_user('Administrator')
    name = 'TJY-HARNESS-VERIFY-' + uuid4().hex[:12]
    cookies, sessions = [], []
    created, passed = False, False
    stage = 'schema_and_target_preview'
    previous_gate = frappe.conf.get(approval.WRITE_ENABLE_KEY)
    try:
        approval.business._meta('UOM')
        assert not frappe.db.exists('UOM', name)
        # Only this named, unreferenced fixture record is in the mutation scope.
        frappe.get_doc({'doctype': 'UOM', 'uom_name': name, 'description': 'synthetic-before'}).insert()
        frappe.db.commit()
        created = True
        update_site_config(approval.WRITE_ENABLE_KEY, 1)
        frappe.conf[approval.WRITE_ENABLE_KEY] = 1
        for user in ['Administrator', '317395616@qq.com']:
            stage = 'signed_login'
            frappe.set_user(user)
            harness_auth.launch()
            status, headers, _ = request('/employee/sso?' + urlsplit(frappe.local.response['location']).query)
            assert status == 303
            cookies.append(headers['set-cookie'].split(';', 1)[0])
            status, _, body = request('/employee/session/create', cookies[-1], {})
            assert status == 200
            sessions.append(body['sessionId'])
        frappe.set_user('Administrator')
        stage = 'capabilities'
        for index, expected in [(0, True), (1, False)]:
            status, _, body = request('/employee/session/capabilities', cookies[index], {'sessionId': sessions[index]})
            assert status == 200 and body == {'previews': expected}
        stage = 'real_model_preview'
        status, _, body = request('/employee/session/prompt', cookies[0], {'sessionId': sessions[0],
            'text': '先查询 UOM 元数据，然后为 UOM 编号 ' + name +
            ' 生成修改预览：仅将 description 改成 synthetic-browser-confirmed。请调用 employee_application_preview，operation=update，arguments 包含 doctype、name、changes。只生成一次预览，不执行。'}, timeout=105)
        assert status == 200 and body.get('settled') is True
        stage = 'review_model_preview'
        status, _, body = request('/employee/session/review', cookies[0], {'sessionId': sessions[0]})
        assert status == 200 and len(body['items']) == 1
        preview = body['items'][0]
        assert preview['plan']['doctype'] == 'UOM' and preview['plan']['name'] == name
        assert preview['plan']['changes'] == {'description': 'synthetic-browser-confirmed'}
        frappe.db.rollback()
        assert frappe.get_doc('UOM', name).description == 'synthetic-before'
        confirm = {'sessionId': sessions[0], 'preview_id': preview['preview_id'], 'digest': preview['digest']}
        stage = 'employee_and_session_denial'
        status, _, _ = request('/employee/session/confirm', cookies[1], {**confirm, 'sessionId': sessions[1]})
        assert status in (401, 403)
        status, _, _ = request('/employee/session/confirm', cookies[0], {**confirm, 'sessionId': sessions[1]})
        assert status == 404
        stage = 'browser_confirmation'
        browser = subprocess.run(['/home/zyd/.local/bin/node', str(Path(__file__).with_name('accept_application_browser.mjs'))],
            input=json.dumps({'cookie': cookies[0], 'sessionId': sessions[0], 'preview_id': preview['preview_id']}),
            text=True, capture_output=True, timeout=100)
        browser_result = json.loads(browser.stdout) if browser.stdout else {}
        print(json.dumps({'browser_passed': browser_result.get('browser_passed'),
            'browser_stage': browser_result.get('stage'), 'browser_exit': browser.returncode,
            'browser_requests': browser_result.get('requests'), 'page_errors': browser_result.get('page_errors')}))
        assert browser.returncode == 0 and json.loads(browser.stdout)['browser_passed'] is True
        stage = 'replay_and_readback'
        status, _, receipt = request('/employee/session/confirm', cookies[0], confirm)
        assert status == 200 and receipt['state'] == 'succeeded' and receipt['replayed'] is True
        frappe.db.rollback()
        assert frappe.get_doc('UOM', name).description == 'synthetic-browser-confirmed'
        assert frappe.db.count(approval.AUDIT, {'tool_name': approval.CLAIM_PREFIX + preview['preview_id']}) == 1
        assert frappe.db.count(approval.AUDIT, {'tool_name': approval.RESULT_PREFIX + preview['preview_id']}) == 1
        stage = 'concurrent_confirmation'
        # Same binding derivation as the trusted authority, used only by this operator test.
        binding = hashlib.sha256(json.dumps([cookies[0].split('=', 1)[1], sessions[0]]).encode()).hexdigest()
        concurrent = approval.create_preview(binding, 'update', 'UOM', name=name,
            changes={'description': 'synthetic-concurrency-confirmed'})
        arguments = {'sessionId': sessions[0], 'preview_id': concurrent['preview_id'], 'digest': concurrent['digest']}
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(lambda _: request('/employee/session/confirm', cookies[0], arguments), range(2)))
        print(json.dumps({'concurrent_replies': [{'http_status': row[0], 'state': row[2].get('state'),
            'replayed': row[2].get('replayed'), 'error_type': row[2].get('error_type')} for row in replies]}))
        assert all(reply[0] == 200 for reply in replies)
        assert sum(reply[2].get('replayed') is False for reply in replies) == 1
        frappe.db.rollback()
        assert frappe.get_doc('UOM', name).description == 'synthetic-concurrency-confirmed'
        assert frappe.db.count(approval.AUDIT, {'tool_name': approval.CLAIM_PREFIX + concurrent['preview_id']}) == 1
        assert frappe.db.count(approval.AUDIT, {'tool_name': approval.RESULT_PREFIX + concurrent['preview_id']}) == 1
        stage = 'stale_preview'
        stale = approval.create_preview(binding, 'update', 'UOM', name=name, changes={'description': 'must-not-write'})
        doc = frappe.get_doc('UOM', name)
        doc.description = 'synthetic-concurrent-edit'
        doc.save()
        frappe.db.commit()
        status, _, receipt = request('/employee/session/confirm', cookies[0], {'sessionId': sessions[0],
            'preview_id': stale['preview_id'], 'digest': stale['digest']})
        assert status == 200 and receipt['state'] == 'failed'
        frappe.db.rollback()
        assert frappe.get_doc('UOM', name).description == 'synthetic-concurrent-edit'
        passed = True
        print(json.dumps({'passed': True, 'browser_tested': True, 'real_model_preview': True,
            'separate_confirmation': True, 'concurrent_execution_count': 1, 'stale_preview_rejected': True,
            'ordinary_user_denied': True, 'existing_business_records_changed': 0, 'fixture_records': 1}))
        return 0
    except Exception as error:
        if cookies and sessions:
            try:
                diagnostic_status, _, page = request('/employee/session/page', cookies[0], {
                    'sessionId': sessions[0], 'maxMessages': 50})
                print(json.dumps({'diagnostic_status': diagnostic_status,
                    'event_types': [row.get('event', {}).get('type') for row in page.get('records', [])],
                    'tool_names': [row['event']['data'].get('name') for row in page.get('records', [])
                        if row.get('event', {}).get('type') == 'tool/call']}))
            except Exception:
                pass  # Diagnostic content is never needed to preserve failure/rollback.
        print(json.dumps({'passed': False, 'stage': stage, 'error_type': type(error).__name__,
            'http_status': locals().get('status')}))
        return 1
    finally:
        frappe.set_user('Administrator')
        frappe.db.rollback()
        if not passed:
            update_site_config(approval.WRITE_ENABLE_KEY, previous_gate or 0)
        if created:
            frappe.delete_doc('UOM', name)
            frappe.db.commit()
            print(json.dumps({'fixture_removed': not frappe.db.exists('UOM', name), 'audit_evidence_retained': True}))
        for cookie in cookies:
            try:
                request('/employee/logout', cookie, {})
            except Exception:
                pass  # Best-effort test logout; never print private credentials.
        frappe.destroy()


if __name__ == '__main__':
    raise SystemExit(main())
