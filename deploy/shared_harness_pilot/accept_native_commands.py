"""Check native session commands with two signed accounts; no business writes."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit
import frappe
from ione_core import harness_auth
from accept_live_http import request


def main():
    cookies, sessions = [], []
    stage = 'login'
    os.chdir('/home/zyd/frappe/native-bench')
    frappe.init(site='child.myyr.top', sites_path='/home/zyd/frappe/native-bench/sites')
    frappe.connect(set_admin_as_user=False)
    try:
        for user in ['Administrator', '317395616@qq.com']:
            frappe.set_user(user)
            harness_auth.launch()
            status, headers, _ = request('/employee/sso?' + urlsplit(frappe.local.response['location']).query)
            assert status == 303
            cookies.append(headers['set-cookie'].split(';', 1)[0])
            status, _, value = request('/employee/session/create', cookies[-1], {})
            assert status == 200
            sessions.append(value['sessionId'])
        stage = 'own_commands_and_cross_account_denial'
        for index, cookie in enumerate(cookies):
            for operation in ['cancel', 'rename']:
                payload = {'operation': operation, 'sessionId': sessions[index]}
                if operation == 'rename':
                    payload['title'] = '账号隔离验收'
                status, _, _ = request('/native/command', cookie, payload)
                assert status == 200
                payload['sessionId'] = sessions[1-index]
                status, _, _ = request('/native/command', cookie, payload)
                assert status == 404
        stage = 'cancel_active_employee_turn'
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(request, '/employee/session/prompt', cookies[1], {
                'sessionId': sessions[1],
                'text': '请写一篇三千字的虚构森林童话。这是对话停止功能测试，不要查询或修改任何业务数据。',
            }, timeout=95)
            running = False
            for _ in range(100):
                status, _, value = request('/employee/session/list', cookies[1], {})
                assert status == 200
                running = any(row['sessionId'] == sessions[1] and row['running'] for row in value['items'])
                if running or pending.done():
                    break
                time.sleep(0.2)
            assert running, 'no active turn observed'
            status, _, receipt = request('/native/command', cookies[1], {'operation': 'cancel', 'sessionId': sessions[1]})
            assert status == 200 and receipt['accepted'] is True
            status, _, result = pending.result(timeout=20)
            assert status == 200 and result['settled'] is True
            status, _, value = request('/employee/session/list', cookies[1], {})
            assert status == 200 and not any(row['sessionId'] == sessions[1] and row['running'] for row in value['items'])
        print(json.dumps({'passed': True, 'accounts_tested': 2, 'cross_account_commands_denied': 4,
                          'active_turn_cancelled': True, 'business_records_changed': 0}))
        return 0
    except Exception as error:
        print(json.dumps({'passed': False, 'stage': stage, 'error_type': type(error).__name__}))
        return 1
    finally:
        for cookie in cookies:
            try:
                request('/employee/logout', cookie, {})
            except Exception:
                pass  # Session expires independently; never emit login material during cleanup.
        frappe.db.rollback()
        frappe.destroy()


if __name__ == '__main__':
    raise SystemExit(main())
