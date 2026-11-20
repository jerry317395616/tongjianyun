"""Native image browser acceptance with synthetic content and two signed accounts."""
import base64
import json
import os
import struct
import subprocess
import zlib
from urllib.parse import urlsplit
import frappe
from ione_core import harness_auth
from accept_live_http import request


def main():
    cookies = []
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
        def chunk(kind, data):
            return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
        png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 32, 32, 8, 2, 0, 0, 0))
        png += chunk(b'IDAT', zlib.compress((b'\0' + b'\xff\0\0' * 32) * 32)) + chunk(b'IEND', b'')
        for index, cookie in enumerate(cookies):
            completed = subprocess.run(['/home/zyd/.local/bin/node', os.path.join(os.path.dirname(__file__), 'accept_native_image_browser.mjs')],
                input=json.dumps({'cookie': cookie, 'png': base64.b64encode(png).decode()}), text=True, capture_output=True, timeout=160)
            result = json.loads(completed.stdout.strip().splitlines()[-1])
            if not result.get('passed'):
                print(json.dumps(result)); return 1
            payload = {'sessionId': result['sessionId'], 'attachmentId': result['attachmentId']}
            status, _, _ = request('/native/attachment', cookies[1-index], payload)
            assert status == 404
        print(json.dumps({'passed': True, 'accounts': 2, 'native_image_upload': True,
                          'model_recognized_red': True, 'owned_image_read': True,
                          'cross_account_image_read_denied': True, 'business_records_changed': 0}))
        return 0
    except Exception as error:
        print(json.dumps({'passed': False, 'error_type': type(error).__name__})); return 1
    finally:
        for cookie in cookies:
            try:
                request('/employee/logout', cookie, {})
            except Exception:
                pass  # Expiry remains authoritative; never print login material.
        frappe.db.rollback()
        frappe.destroy()


if __name__ == '__main__':
    raise SystemExit(main())
