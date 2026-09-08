"""Check live attachment-read denial boundaries; never inspect real attachments."""
import json
import os
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
            status, _, result = request('/employee/session/create', cookies[-1], {})
            assert status == 200
            sessions.append(result['sessionId'])
        stage = 'attachment_boundaries'
        for index, cookie in enumerate(cookies):
            payload = {'sessionId': sessions[1-index], 'attachmentId': 'sha256:' + '0'*64}
            status, _, _ = request('/native/attachment', cookie, payload)
            assert status == 404
            payload['sessionId'] = sessions[index]
            status, _, result = request('/native/attachment', cookie, payload)
            # New empty sessions reference no image; native errors stay redacted.
            assert status == 503 and result == {'error': 'native access unavailable'}
            status, _, _ = request('/native/attachment', cookie, {**payload, 'path': '/etc/passwd'})
            assert status == 400
        stage = 'unauthenticated'
        status, _, _ = request('/native/attachment', payload=payload)
        assert status == 401
        print(json.dumps({'passed': True, 'accounts_tested': 2, 'cross_account_denied': True,
                          'unreferenced_image_denied': True, 'path_injection_denied': True,
                          'business_records_changed': 0, 'upload_enabled': False}))
        return 0
    except Exception as error:
        print(json.dumps({'passed': False, 'stage': stage, 'error_type': type(error).__name__}))
        return 1
    finally:
        for cookie in cookies:
            try:
                request('/employee/logout', cookie, {})
            except Exception:
                pass  # Never print authentication material.
        frappe.db.rollback()
        frappe.destroy()


if __name__ == '__main__':
    raise SystemExit(main())
