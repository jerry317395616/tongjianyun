"""Local candidate HTTP acceptance; credentials and student data never emitted."""
import http.client
import json
import os
from urllib.parse import urlsplit
import frappe
from ione_core import harness_auth

def request(path, cookie=None, payload=None):
    connection = http.client.HTTPConnection('127.0.0.1',13093,timeout=35)
    headers = {'Host':'harness.myyr.top','Origin':'https://harness.myyr.top'}
    if cookie: headers['Cookie'] = cookie
    if payload is not None: headers['Content-Type'] = 'application/json'
    try:
        connection.request('GET' if payload is None else 'POST',path,
                           None if payload is None else json.dumps(payload),headers)
        response = connection.getresponse()
        raw = response.read(1048577)
        if len(raw)>1048576: raise ValueError('response too large')
        return response.status,dict(response.getheaders()),json.loads(raw) if raw else None
    finally: connection.close()

def main():
    stage = 'initialize'; cookies = []; sessions = []
    os.chdir('/home/zyd/frappe/native-bench')
    frappe.init(site='child.myyr.top',sites_path='/home/zyd/frappe/native-bench/sites')
    frappe.connect(set_admin_as_user=False)
    try:
        for user in ['harness.test.teacher.a@example.invalid','harness.test.teacher.b@example.invalid']:
            stage = 'signed_login'
            frappe.set_user(user); harness_auth.launch()
            query = urlsplit(frappe.local.response['location']).query
            status,headers,_ = request('/employee/sso?'+query)
            assert status == 303
            cookie = headers['set-cookie'].split(';',1)[0]; cookies.append(cookie)
            stage = 'status'
            status,_,body = request('/employee/status',cookie)
            assert status == 200 and body['agentExecution'] is True
            stage = 'create_session'
            status,_,body = request('/employee/session/create',cookie,{})
            assert status == 200
            sessions.append(body['sessionId'])
        stage = 'ownership_isolation'
        for index,cookie in enumerate(cookies):
            status,_,body = request('/employee/session/list',cookie,{})
            assert status == 200
            assert {row['sessionId'] for row in body['items']} == {sessions[index]}
            status,_,_ = request('/employee/session/read',cookie,{
                'sessionId':sessions[1-index],'operation':'frappe_list_documents',
                'arguments':{'doctype':'Student','fields':['name'],'limit':1}})
            assert status in (403,404)
        stage = 'scoped_read'
        status,_,body = request('/employee/session/read',cookies[0],{
            'sessionId':sessions[0],'operation':'frappe_list_documents',
            'arguments':{'doctype':'Student','fields':['name'],'limit':1}})
        if status != 200: raise RuntimeError('HTTP failure')
        assert isinstance(body.get('rows'),list) and len(body['rows']) <= 1
        visible_sample_count = len(body['rows'])
        stage = 'real_model_turn'
        status,_,body = request('/employee/session/prompt',cookies[0],{
            'sessionId':sessions[0],'text':'只回复“连接正常”，不要查询或修改任何业务数据。'})
        assert status == 200 and body.get('settled') is True
        stage = 'model_response_history'
        status,_,page = request('/employee/session/page',cookies[0],{
            'sessionId':sessions[0],'throughSeq':body['throughSeq'],'maxMessages':50})
        assert status == 200
        assert any(record.get('event',{}).get('type') == 'assistant/message' and
                   any(part.get('type') == 'text' and part.get('text','').strip()
                       for part in record['event'].get('data',{}).get('message',{}).get('content',[]))
                   for record in page.get('records',[]))
        ready = visible_sample_count > 0
        print(json.dumps({'passed':ready,'protocol_passed':True,
            'checks':['signed_login','session_ownership','cross_account_denied',
                      'permission_filtered_read','real_model_turn'],
            'visible_student_sample_count':visible_sample_count,
            'data_scope_acceptance': 'pending_no_assigned_students' if not ready else 'sample_only',
            'browser_tested':False}))
        return 0 if ready else 1
    except Exception as error:
        print(json.dumps({'passed':False,'stage':stage,'error_type':type(error).__name__,
                          'http_status':locals().get('status')}))
        return 1
    finally:
        for cookie in cookies:
            try: request('/employee/logout',cookie,{})
            except Exception: pass
        frappe.db.rollback(); frappe.destroy()

if __name__ == '__main__': raise SystemExit(main())
