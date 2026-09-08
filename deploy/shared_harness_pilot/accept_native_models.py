"""Exercise model permissions without changing the configured provider/model."""
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
            status, _, value = request('/employee/session/create', cookies[-1], {})
            assert status == 200
            sessions.append(value['sessionId'])
        stage = 'catalog'
        status, _, catalog = request('/native/models', cookies[0])
        assert status == 200 and catalog['groups']
        baseline = catalog['default']
        status, _, ordinary = request('/native/models', cookies[1])
        assert status == 200 and ordinary['default'] == baseline
        stage = 'ordinary_denied'
        status, _, _ = request('/native/model-selection', cookies[1], {**baseline, 'sessionId': sessions[1]})
        assert status == 403
        stage = 'cross_account_denied'
        status, _, _ = request('/native/model-selection', cookies[0], {**baseline, 'sessionId': sessions[1]})
        assert status == 404
        stage = 'administrator_select_current_model'
        status, _, selected = request('/native/model-selection', cookies[0], {**baseline, 'sessionId': sessions[0]})
        assert status == 200
        assert all(selected['selected'][key] == baseline[key] for key in ['provider', 'model'])
        stage = 'global_provider_model_unchanged'
        status, _, after = request('/native/models', cookies[0])
        assert status == 200 and all(after['default'][key] == baseline[key] for key in ['provider', 'model'])
        print(json.dumps({'passed': True, 'administrator_model_selection': True,
                          'ordinary_selection_denied': True, 'cross_account_denied': True,
                          'configured_provider_model_unchanged': True, 'business_records_changed': 0}))
        return 0
    except Exception as error:
        print(json.dumps({'passed': False, 'stage': stage, 'error_type': type(error).__name__}))
        return 1
    finally:
        for cookie in cookies:
            try:
                request('/employee/logout', cookie, {})
            except Exception:
                pass  # Expiry remains effective; do not print credentials during cleanup.
        frappe.db.rollback()
        frappe.destroy()


if __name__ == '__main__':
    raise SystemExit(main())
