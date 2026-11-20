"""Privileged, read-only deployment acceptance. No passwords or tickets are printed."""
import json
import os
import socket
from urllib.parse import urlsplit, parse_qs
import frappe
from ione_core import harness_auth

SOCKET = '/home/zyd/.config/ione-harness-shared/authority.sock'
USERS = ['harness.test.teacher.a@example.invalid', 'harness.test.teacher.b@example.invalid']
stage = 'initialize'

def request(operation, value):
    with socket.socket(socket.AF_UNIX) as channel:
        channel.settimeout(35)
        channel.connect(SOCKET)
        channel.sendall((json.dumps({'version':1,'operation':operation,'value':value})+'\n').encode())
        channel.shutdown(socket.SHUT_WR)
        data = bytearray()
        while block := channel.recv(16384):
            data.extend(block)
            if len(data) > 262144: raise ValueError('bounded reply exceeded')
    return json.loads(data)

def read(cookie, operation, arguments):
    reply = request('read', {'credential':cookie,'operation':operation,'arguments':arguments})
    if not reply.get('ok'): raise ValueError('read denied')
    return reply['result']

def main():
    global stage
    os.chdir('/home/zyd/frappe/native-bench')
    frappe.init(site='child.myyr.top',sites_path='/home/zyd/frappe/native-bench/sites')
    frappe.connect(set_admin_as_user=False)
    cookies = []
    try:
        names = []
        for user in USERS:
            stage = 'issue_handoff'
            frappe.set_user(user)
            harness_auth.launch()
            ticket = parse_qs(urlsplit(frappe.local.response['location']).query)['token'][0]
            stage = 'exchange_handoff'
            login = request('login',ticket)
            if not login.get('ok'): raise ValueError('login denied')
            cookie = login['result']['cookie']; cookies.append(cookie)
            if request('login',ticket).get('ok'): raise ValueError('ticket replay accepted')
            stage = 'authorize'
            principal = request('authorize',cookie)
            if principal.get('result',{}).get('user') != user: raise ValueError('wrong principal')
            stage = 'list_students'
            rows = []
            for start in range(0, 1000, 100):
                page = read(cookie,'frappe_list_documents',{'doctype':'Student','fields':['name'],'limit':100,'start':start,'order_by':'name asc'})['rows']
                rows.extend(page)
                if len(page) < 100: break
            else: raise ValueError('pilot result exceeds acceptance bound')
            names.append({row['name'] for row in rows})
        if not all(names) or names[0] & names[1]: raise ValueError('pilot scope overlap')
        for index,cookie in enumerate(cookies):
            stage = 'cross_class_read'
            peer = next(iter(names[1-index]))
            result = read(cookie,'frappe_get_document',{'doctype':'Student','name':peer,'fields':['name']})
            if result.get('document') is not None: raise ValueError('cross-class direct read accepted')
            denied = request('read',{'credential':cookie,'operation':'frappe_list_documents','arguments':{'doctype':'User'}})
            if denied.get('ok'): raise ValueError('out-of-scope doctype accepted')
            request('logout',cookie)
            if request('authorize',cookie).get('ok'): raise ValueError('logout did not revoke')
        print(json.dumps({'passed':True,'student_counts':[len(items) for items in names],
                          'checks':['signed handoff','single-use replay rejection','account pinning',
                                    'disjoint student lists','cross-class direct read rejection',
                                    'User doctype rejection','logout revocation'],
                          'browser_login_tested':False}))
    finally:
        for cookie in cookies:
            try: request('logout',cookie)
            except Exception: pass  # Best effort cleanup; no credentials emitted.
        frappe.db.rollback();frappe.destroy()

if __name__ == '__main__':
    try: main()
    except Exception as error:
        print(json.dumps({'passed':False,'stage':stage,'error_type':type(error).__name__}))
        raise SystemExit(1)
