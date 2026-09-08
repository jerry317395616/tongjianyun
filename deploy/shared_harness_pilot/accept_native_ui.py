"""Native browser acceptance with an internal signed login; never print credentials."""
import http.client
import json
import os
import subprocess
import time
from urllib.parse import urlsplit
import frappe
from ione_core import harness_auth


def main():
    os.chdir('/home/zyd/frappe/native-bench')
    frappe.init(site='child.myyr.top', sites_path='/home/zyd/frappe/native-bench/sites')
    frappe.connect(set_admin_as_user=False)
    connection = http.client.HTTPConnection('127.0.0.1', 13091, timeout=30)
    cookie = None
    try:
        for _ in range(30):
            connection.request('GET', '/employee/status', headers={'Host': 'harness.myyr.top'})
            ready = connection.getresponse()
            status = ready.status
            ready.read()
            if status == 401:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError('Harness did not become ready')
        frappe.set_user('Administrator')
        harness_auth.launch()
        query = urlsplit(frappe.local.response['location']).query
        connection.request('GET', '/employee/sso?' + query, headers={'Host': 'harness.myyr.top'})
        response = connection.getresponse()
        assert response.status == 303
        cookie = response.getheader('set-cookie').split(';', 1)[0]
        response.read()
        connection.close()
        checks = []
        body = json.dumps({'sessionId': 'session-11111111-1111-1111-1111-111111111111', 'maxMessages': 10})
        for path, payload, authenticated, origin, expected in [
            ('/native/view', body, False, 'https://harness.myyr.top', 401),
            ('/native/view', body, True, 'https://invalid.example', 403),
            ('/native/view', '{}', True, 'https://harness.myyr.top', 400),
            ('/native/view', body, True, 'https://harness.myyr.top', 404),
            ('/api/rpc', '{}', True, 'https://harness.myyr.top', 404),
            ('/native/command', json.dumps({'operation':'cancel','sessionId':'session-11111111-1111-1111-1111-111111111111'}), False, 'https://harness.myyr.top', 401),
            ('/native/command', json.dumps({'operation':'cancel','sessionId':'session-11111111-1111-1111-1111-111111111111'}), True, 'https://harness.myyr.top', 404),
            ('/native/command', json.dumps({'operation':'cancel','sessionId':'session-11111111-1111-1111-1111-111111111111','user':'Administrator'}), True, 'https://harness.myyr.top', 400),
        ]:
            headers = {'Host': 'harness.myyr.top', 'Origin': origin, 'Content-Type': 'application/json'}
            if authenticated:
                headers['Cookie'] = cookie
            connection.request('POST', path, payload, headers)
            denied = connection.getresponse()
            actual = denied.status
            denied.read()
            assert actual == expected, (path, actual, expected)
            checks.append(actual)
        connection.close()
        print(json.dumps({'boundary_checks': checks}), flush=True)
        result = subprocess.run([
            '/home/zyd/.local/bin/node',
            '/home/zyd/frappe/native-bench/apps/tongjianyun/deploy/shared_harness_pilot/accept_native_browser.mjs',
        ], input=json.dumps({'cookie': cookie}), text=True, timeout=180)
        return result.returncode
    finally:
        if cookie:
            connection.request('POST', '/employee/logout', '{}', {
                'Host': 'harness.myyr.top', 'Origin': 'https://harness.myyr.top',
                'Cookie': cookie, 'Content-Type': 'application/json',
            })
            connection.getresponse().read()
        connection.close()
        frappe.db.rollback()
        frappe.destroy()


if __name__ == '__main__':
    raise SystemExit(main())
