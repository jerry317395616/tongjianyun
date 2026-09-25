"""Pure QA harness guards; no model, real sites, Redis, DB or server starts."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

SPEC = importlib.util.spec_from_file_location('business_browser_qa', Path(__file__).with_name('serve_business_browser.py'))
web = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(web)
ID = '2956b36d-fd31-4c9c-8d12-a95d4d23fdbe'
OTHER = '16f14f90-df72-4369-bad6-cfdd60f27c77'


def send():
    return {'request_id': ID, 'message': '请只读查询本班人数并显示出勤视图。',
        'day': web.fixture.DAY, 'meal': web.fixture.MEAL, 'stream': 1,
        'view_context': {'view': 'classroom_day', 'day': web.fixture.DAY, 'meal': web.fixture.MEAL,
                         'group': web.fixture.GROUP}}


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(web, 'verified_sources', return_value={})
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, command, method='GET', values=None, *, path=None, extra=None, original=False):
        values = values or {}
        body = json.dumps(values).encode() if method != 'GET' else b''
        environ = {'HTTP_HOST': f'{web.qa.SITE}:{web.qa.PORT}', 'PATH_INFO': path or '/api/method/' + command,
            'REQUEST_METHOD': method, 'QUERY_STRING': urlencode(values) if method == 'GET' else '',
            'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(body)), 'wsgi.input': io.BytesIO(body)}
        environ.update(extra or {})
        app, response = Mock(return_value=[b'native']), Mock()
        boundary = web.qa.QAFirewall(app) if original else web.BrowserBoundary(app)
        with patch.object(web.qa, 'config_guard', return_value={'unified_browser_acceptance': 1, 'maintenance_mode': 0}):
            result = boundary(environ, response)
        return app, response, result, environ

    def test_original_harness_still_blocks_every_business_rpc(self):
        for name, method in web.BUSINESS.items():
            app, response, _, _ = self.call(web.API + name, method, send() if name == 'send_message' else {}, original=True)
            app.assert_not_called()
            self.assertEqual(response.call_args.args[0], '403 Forbidden')

    def test_exact_frontend_business_protocol_passes_to_native(self):
        for name, method, data in (
            ('send_message', 'POST', send()), ('get_conversation', 'GET', {}),
            ('get_conversation', 'GET', {'before': ID}),
            ('get_events', 'GET', {'task_id': ID, 'after': ID + ':8'}),
            ('stream_events', 'GET', {'task_id': ID, 'after': '0'}),
            ('retry_dispatch', 'POST', {'task_id': ID}), ('cancel_task', 'POST', {'task_id': ID}),
        ):
            with self.subTest(name=name):
                app, _, _, env = self.call(web.API + name, method, data)
                app.assert_called_once()
                if method == 'POST':
                    self.assertEqual(json.loads(env['wsgi.input'].read()), data)

    def test_admin_upload_arbitrary_queue_and_business_writes_remain_blocked(self):
        for command in ('tongjianyun.meal_chat.send_message', 'tongjianyun.meal_chat.get_conversation',
            'tongjianyun.meal_chat.cancel_task', 'upload_file', web.WORKER_METHOD,
            'frappe.utils.background_jobs.enqueue', 'tongjianyun.classroom.save_attendance',
            'tongjianyun.classroom.save_meals', 'frappe.desk.form.save.savedocs',
            'tongjianyun.business_blueprints.activate'):
            for method in ('GET', 'POST'):
                app, _, _, _ = self.call(command, method)
                app.assert_not_called()

    def test_only_fixed_teacher_login_and_no_fake_session(self):
        for user, allowed in ((web.fixture.TEACHER, True), ('Administrator', False), ('other@example.invalid', False)):
            app, _, _, env = self.call('login', 'POST', {'usr': user, 'pwd': 'synthetic-test-placeholder'})
            self.assertEqual(app.called, allowed)
            self.assertNotIn('HTTP_COOKIE', env)
            self.assertNotIn('HTTP_X_FRAPPE_CSRF_TOKEN', env)

    def test_native_cookie_and_csrf_are_preserved_without_bypass(self):
        headers = {'HTTP_COOKIE': 'sid=synthetic-session', 'HTTP_X_FRAPPE_CSRF_TOKEN': 'synthetic-csrf'}
        app, _, _, env = self.call(web.API + 'send_message', 'POST', send(), extra=headers)
        app.assert_called_once()
        for key, value in headers.items():
            self.assertEqual(env[key], value)

    def test_mutating_unknown_fields_files_and_scope_are_rejected(self):
        for updates in ({'file_name': 'File'}, {'owner': 'Administrator'}, {'stream': True}, {'request_id': OTHER.upper()},
            {'day': '2026-01-01'}, {'meal': 'dinner'}, {'message': ''},
            {'view_context': {'view': 'project_catalog'}},
            {'view_context': {'view': 'classroom_day', 'group': 'foreign'}}):
            app, _, _, _ = self.call(web.API + 'send_message', 'POST', {**send(), **updates})
            app.assert_not_called()

    def test_canonical_server_view_selections_are_accepted(self):
        choices = ({**send()['view_context'], 'offset':0},
                   {'view':'class_students', 'group':web.fixture.GROUP, 'offset':0},
                   {'view':'students', 'presentation':'table'})
        for choice in choices:
            app, _, _, _ = self.call(web.API+'send_message', 'POST', {**send(),'view_context':choice})
            app.assert_called_once()
            app, _, _, _ = self.call('tongjianyun.meal_views.get_view', values={'selection_json':json.dumps(choice)})
            app.assert_called_once()
        for choice in ({**choices[0],'offset':True}, {**choices[0],'offset':1},
                       {**choices[0],'presentation':'table'}, {**choices[2],'offset':0}):
            self.assertFalse(web.selection_allowed(choice))

    def test_wrong_verbs_and_noncanonical_aliases_are_rejected(self):
        for path in ('/api/v1/method/' + web.API + 'send_message',
                     '/api/v2/method/' + web.API.replace('.', '/') + 'send_message',
                     '/api/method/tongjianyun%252ebusiness_chat%252esend_message', '/'):
            app, _, _, _ = self.call(web.API + 'send_message', 'POST', send(), path=path)
            app.assert_not_called()
        app, _, _, _ = self.call(web.API + 'send_message', 'GET', send())
        app.assert_not_called()
        app, _, _, _ = self.call(web.API + 'send_message', 'POST', {**send(), 'cmd': web.API + 'send_message'})
        app.assert_not_called()

    def test_last_event_id_must_belong_to_exact_task(self):
        for value, allowed in ((ID + ':3', True), (OTHER + ':3', False), ('0-0', False), (ID + ':0', False)):
            app, _, _, _ = self.call(web.API + 'stream_events', values={'task_id': ID}, extra={'HTTP_LAST_EVENT_ID': value})
            self.assertEqual(app.called, allowed)

    def test_paths_private_files_and_other_hosts_are_rejected(self):
        for path in ('/private/files/secret', '/backups/database.sql', '/desk', '/api/resource/Student'):
            app, _, _, _ = self.call('', path=path)
            app.assert_not_called()
        app, _, _, _ = self.call(web.API + 'get_conversation', extra={'HTTP_HOST': 'child.myyr.top'})
        app.assert_not_called()

    def test_health_describes_new_scope_truthfully(self):
        app, response, result, _ = self.call('', path='/__qa__/health')
        app.assert_not_called()
        body = json.loads(result[0])
        self.assertTrue(body['admin_execution_blocked'])
        self.assertTrue(body['uploads_blocked'])
        self.assertTrue(body['threaded'])
        self.assertNotIn('codex_execution_blocked', body)

    def test_non_boolean_policy_verdict_is_rejected(self):
        app = Mock()
        env = {'HTTP_HOST': f'{web.qa.SITE}:{web.qa.PORT}', 'PATH_INFO': '/api/method/test',
               'REQUEST_METHOD': 'GET', 'QUERY_STRING': '', 'CONTENT_LENGTH': '0'}
        for verdict in (0, 1, 'allow', {}):
            with patch.object(web.qa, 'config_guard', return_value={'unified_browser_acceptance':1}), self.assertRaises(TypeError):
                web.qa.QAFirewall(app, request_policy=lambda *args: verdict)(env, Mock())
        app.assert_not_called()


class NativeAuthTests(unittest.TestCase):
    def auth(self, user):
        return SimpleNamespace(session=SimpleNamespace(user=user), request=SimpleNamespace(path='/api/method/' + web.API + 'send_message'),
                               form_dict=send(), PermissionError=PermissionError)

    def test_native_auth_failure_precedes_reservation(self):
        native = Mock(side_effect=PermissionError('native CSRF failed'))
        with patch.object(web, 'reserve_request') as reserve, self.assertRaises(PermissionError):
            web.authenticated_guard(self.auth(web.fixture.TEACHER), native)()
        native.assert_called_once()
        reserve.assert_not_called()

    def test_guest_other_user_and_administrator_never_reserve(self):
        for user in ('Guest', 'Administrator', 'other@example.invalid'):
            with patch.object(web, 'reserve_request') as reserve, self.assertRaises(PermissionError):
                web.authenticated_guard(self.auth(user), Mock())()
            reserve.assert_not_called()

    def test_native_teacher_can_reserve_after_success(self):
        sequence = []
        with patch.object(web, 'reserve_request', side_effect=lambda _, **kwargs: sequence.append('reserve')):
            web.authenticated_guard(self.auth(web.fixture.TEACHER), lambda: sequence.append('native'))()
        self.assertEqual(sequence, ['native', 'reserve'])

    def test_native_login_guest_path_is_not_fabricated(self):
        frappe = self.auth('Guest')
        frappe.request.path = '/login'
        with patch.object(web, 'reserve_request') as reserve:
            web.authenticated_guard(frappe, Mock())()
        reserve.assert_not_called()
        self.assertEqual(frappe.session.user, 'Guest')

    def test_same_request_can_resume_but_new_request_or_payload_cannot(self):
        saved = {}
        def exclusive(path, value):
            if saved:
                raise FileExistsError
            saved.update(value)
        before = Mock(return_value='a'*64)
        marker = Mock()
        marker.exists.side_effect = lambda: bool(saved)
        with patch.object(web, 'ATTEMPT', marker), patch.object(web, 'exclusive_json', side_effect=exclusive), patch.object(web, 'verified_sources', return_value={}), patch.object(web, 'private_read', return_value=saved):
            web.reserve_request(send(), before_model=before)
            web.reserve_request(send(), before_model=before)
            for changes in ({'request_id': OTHER}, {'message': 'different request'}):
                with self.assertRaises(PermissionError):
                    web.reserve_request({**send(), **changes}, before_model=before)
        before.assert_called_once()
        self.assertEqual(saved['model_pre_digest'], 'a'*64)
        self.assertNotIn('message', saved)
        self.assertFalse(saved['automatic_retry'])


class WorkerTests(unittest.TestCase):
    def job(self):
        return SimpleNamespace(origin='qa:business_codex', timeout=-1, args=(),
            retries_left=None, _success_callback_name=None, _stopped_callback_name=None,
            _failure_callback_name='frappe.utils.background_jobs.truncate_failed_registry',
            func_name='frappe.utils.background_jobs.execute_job', kwargs={'site': web.qa.SITE,
            'user': web.fixture.TEACHER, 'method': web.WORKER_METHOD, 'event': None,
            'job_name': web.WORKER_METHOD, 'is_async': True,
            'kwargs': {'owner': web.fixture.TEACHER, 'task_id': ID}})

    def setUp(self):
        patcher = patch.object(web, 'private_read', return_value={'site': web.qa.SITE, 'owner': web.fixture.TEACHER, 'request_id': ID})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_only_exact_native_business_job_passes(self):
        web.validate_job(self.job(), 'qa:business_codex', 'qa:business_codex')

    def test_queue_job_function_timeout_and_args_are_pinned(self):
        for field, value in (('origin', 'production:business_codex'), ('func_name', 'os.system'),
                             ('timeout', 300), ('args', ('untrusted',)), ('retries_left',3),
                             ('_success_callback_name','os.system'), ('_stopped_callback_name','os.system'),
                             ('_failure_callback_name','os.system')):
            job = self.job()
            setattr(job, field, value)
            with self.assertRaises(PermissionError):
                web.validate_job(job, 'qa:business_codex', 'qa:business_codex')

    def test_admin_method_owner_site_and_unreserved_task_are_rejected(self):
        for changes in ({'site': 'child.myyr.top'}, {'user': 'Administrator'}, {'method': 'tongjianyun.meal_chat.run_task'},
            {'is_async': False}, {'kwargs': {'owner': web.fixture.TEACHER, 'task_id': OTHER}},
            {'kwargs': {'owner': 'Administrator', 'task_id': ID}}, {'retry': 5}):
            job = self.job()
            job.kwargs.update(changes)
            with self.assertRaises(PermissionError):
                web.validate_job(job, 'qa:business_codex', 'qa:business_codex')


class SourceAndRestoreTests(unittest.TestCase):
    def before(self):
        return {'business_codex_enabled': {'present': False, 'value': None},
                'workers': {'present': False}, 'queue': {'present': False, 'value': None}}

    def test_source_edits_after_process_load_are_refused(self):
        with patch.object(web, 'LOADED_SOURCE_SHA256', {name:'a' for name in web.SOURCE_FILES}), patch.object(web.qa, 'digest_file', return_value='b'):
            with self.assertRaises(PermissionError):
                web.verified_sources()

    def test_source_edits_after_preparation_are_refused(self):
        with patch.object(web, 'LOADED_SOURCE_SHA256', {name:'a' for name in web.SOURCE_FILES}), patch.object(web.qa, 'digest_file', return_value='a'), patch.object(web, 'private_read', return_value={'source_sha256':{}}):
            with self.assertRaises(PermissionError):
                web.verified_sources(prepared=True)

    def test_restore_interrupted_write_accepts_only_before_or_after(self):
        for site, common in (({}, {}), ({'business_codex_enabled':1}, {}),
                             ({}, {'workers':{web.QUEUE:{'timeout':-1}}}),
                             ({'business_codex_enabled':1}, {'workers':{web.QUEUE:{'timeout':-1}}})):
            web.restore_fields(site, common, self.before())
            self.assertEqual(site, {})
            self.assertEqual(common, {})

    def test_restore_preserves_unrelated_new_config_and_queues(self):
        site = {'business_codex_enabled':1, 'unrelated':'keep'}
        common = {'workers':{web.QUEUE:{'timeout':-1}, 'new_queue':{'timeout':300}}, 'unrelated':'keep'}
        web.restore_fields(site, common, self.before())
        self.assertEqual(site, {'unrelated':'keep'})
        self.assertEqual(common, {'workers':{'new_queue':{'timeout':300}}, 'unrelated':'keep'})

    def test_restore_existing_queue_value_and_empty_workers(self):
        old = self.before()
        old['workers']['present'] = True
        old['queue'] = {'present':True, 'value':{'timeout':600}}
        site, common = {'business_codex_enabled':1}, {'workers':{web.QUEUE:{'timeout':-1}}}
        web.restore_fields(site, common, old)
        self.assertEqual(common['workers'][web.QUEUE], {'timeout':600})

    def test_restore_foreign_changes_refused_before_any_change(self):
        for site, common in (({'business_codex_enabled':True}, {'workers':{web.QUEUE:{'timeout':100}}}),
                             ({'business_codex_enabled':2}, {'workers':{web.QUEUE:{'timeout':-1}}})):
            original = json.dumps([site,common],sort_keys=True)
            with self.assertRaises(PermissionError):
                web.restore_fields(site, common, self.before())
            self.assertEqual(json.dumps([site,common],sort_keys=True),original)

if __name__ == '__main__':
    unittest.main()
