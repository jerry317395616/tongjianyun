"""Pure adapter contracts. No connection, role mutation, model or production data."""
from contextlib import ExitStack
from contextvars import ContextVar
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import uuid

import frappe
from tongjianyun import business_agent_authority as authority
from tongjianyun import business_agent_tasks as tasks
from tongjianyun import classroom


def sources(*, students=('S1',), attendance=('A1',), leaves=(), revision='a' * 64):
    return classroom.AttendanceReadSources('G1', '2026-09-16', revision, students, attendance, leaves)


class FrappeBusinessAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.site = 'qa.localhost'
        self.owner = 'teacher@example.invalid'
        self.identity = tasks.TaskIdentity(self.site, self.owner, str(uuid.uuid4()))
        self.session = SimpleNamespace(user='outer-broker', sid='outer-sid')
        self.local = SimpleNamespace(site=self.site, flags={})
        self.db = MagicMock()
        self.account = {'enabled': 1, 'user_type': 'System User'}
        self.session_record = {'user': self.owner, 'status': 'Active', 'lastupdate': datetime(2026, 9, 25, 12),
                               'sessiondata': json.dumps({'last_updated': '2026-09-25 12:00:00', 'session_expiry': '01:00:00'})}
        self.db.get_value.side_effect = lambda dt, *a, **kw: self.account if dt == 'User' else self.session_record
        self.cache = MagicMock()
        self.cache.hget.return_value = None
        for key, value in (('local', self.local), ('session', self.session), ('db', self.db), ('cache', self.cache)):
            self.stack.enter_context(patch.object(frappe, key, value))
        self.stack.enter_context(patch.object(frappe, 'has_permission', return_value=True))
        self.scope = self.stack.enter_context(patch('tongjianyun.classroom._scope', return_value=SimpleNamespace(name='G1')))
        self.meta = SimpleNamespace(issingle=False, name='Student')
        self.native_doctype = self.stack.enter_context(patch('tongjianyun.frappe_project_views._doctype', return_value=self.meta))
        self.modules = self.stack.enter_context(patch('tongjianyun.frappe_project_views.module_apps', return_value={'Education': 'education'}))
        self.stack.enter_context(patch.object(frappe, 'get_installed_apps', return_value=['education', 'tongjianyun']))
        self.doc = MagicMock()
        self.stack.enter_context(patch.object(frappe, 'get_doc', return_value=self.doc))
        self.visible = {'S1', 'A1', 'L1', 'G1', 'G2'}
        self.stack.enter_context(patch.object(frappe, 'get_list', side_effect=lambda dt, **kw: [kw['filters']['name']] if kw['filters']['name'] in self.visible else []))
        self.fields = self.stack.enter_context(patch('tongjianyun.business_agent_authority._fields'))
        self.stack.enter_context(patch('tongjianyun.business_agent_authority._table_field',
            side_effect=lambda dt, field: 'Student Group Student' if dt == 'Student Group' else 'Tongjianyun Student Meal Row'))
        self.stack.enter_context(patch('tongjianyun.business_agent_authority._session_row', side_effect=lambda sid: self.session_record))
        self.scene_gate = self.stack.enter_context(patch('tongjianyun.scene_access.require_scene_account'))
        self.view_gate = self.stack.enter_context(patch('tongjianyun.scene_access.require_view_access'))
        self.stack.enter_context(patch('tongjianyun.meal_scene.today', return_value='2026-09-25'))
        self.context_actors = []
        def fresh(owner, callback):
            self.context_actors.append(owner)
            previous = self.session.user
            self.session.user = owner
            try:
                return callback()
            finally:
                self.session.user = previous
        self.run_check = MagicMock(side_effect=fresh)
        self.run_check.site = self.site
        self.adapter = authority.FrappeBusinessAuthority(self.site, run_check=self.run_check)

    def authorized(self, *scopes):
        return self.adapter(self.identity, scopes)

    def test_enabled_system_account_uses_bound_owner_and_restores_outer_actor(self):
        self.assertTrue(self.authorized())
        self.assertEqual(self.context_actors, [self.owner])
        self.assertEqual(self.session.user, 'outer-broker')
        self.db.get_value.assert_called_once_with('User', self.owner, ['enabled', 'user_type'], as_dict=True)
        self.db.commit.assert_not_called()
        self.db.rollback.assert_not_called()

    def test_guest_cross_site_mode_and_noncanonical_task_are_rejected_before_context(self):
        for identity in (replace(self.identity, site='other.localhost'), replace(self.identity, mode='admin_project'),
                         replace(self.identity, owner='Guest'), replace(self.identity, task_id='task1'),
                         {'owner': self.owner, 'site': self.site}):
            with self.subTest(identity=identity):
                self.assertFalse(self.adapter(identity, []))
        self.run_check.assert_not_called()

    def test_disabled_website_missing_account_and_wrong_framework_context_fail_closed(self):
        for account in (None, {'enabled': 0, 'user_type': 'System User'}, {'enabled': 1, 'user_type': 'Website User'}):
            self.account = account
            self.assertFalse(self.authorized())
        self.account = {'enabled': 1, 'user_type': 'System User'}
        self.local.site = 'other.localhost'
        self.assertFalse(self.authorized())
        self.local.site = self.site
        self.local.flags = {'ignore_permissions': True}
        self.assertFalse(self.authorized())

    def test_every_call_rechecks_account_without_returning_database_error(self):
        self.assertTrue(self.authorized())
        self.account['enabled'] = 0
        self.assertFalse(self.authorized())
        self.db.get_value.side_effect = RuntimeError('private database secret')
        self.assertFalse(self.authorized())
        self.assertEqual(self.run_check.call_count, 3)

    def test_class_scope_uses_original_assignment_and_document_gate(self):
        self.assertTrue(self.authorized(authority._class('G1')))
        self.scope.assert_called_once_with('G1')
        self.scope.side_effect = frappe.PermissionError('not assigned')
        self.assertFalse(self.authorized(authority._class('G1')))

    def test_class_read_is_not_a_generic_write_grant(self):
        self.assertFalse(self.authorized({'kind': 'class', 'group': 'G1', 'actions': ['write']}))
        self.scope.assert_not_called()

    def test_document_requires_both_document_and_query_permission(self):
        scope = authority._read('Student', 'S1')
        self.assertTrue(self.authorized(scope))
        self.doc.check_permission.assert_called_with('read')
        self.visible.remove('S1')
        self.assertFalse(self.authorized(scope))
        self.visible.add('S1')
        self.doc.check_permission.side_effect = frappe.PermissionError('doc share revoked')
        self.assertFalse(self.authorized(scope))

    def test_native_module_and_doctype_actions_are_rechecked(self):
        self.assertTrue(self.authorized({'kind': 'doctype', 'doctype': 'Student', 'actions': ['create', 'read']}))
        frappe.has_permission.assert_any_call('Student', 'create')
        self.native_doctype.side_effect = frappe.PermissionError('module blocked')
        self.assertFalse(self.authorized(authority._read('Student')))

    def test_control_plane_and_unknown_capabilities_denied_even_to_admin_business_task(self):
        identity = replace(self.identity, owner='Administrator')
        for scope in (authority._read('Server Script'), authority._read('User'),
                      authority._capability('root'), authority._capability('shell'),
                      authority._capability('tongjianyun.meal_chat.run_task')):
            self.assertFalse(self.adapter(identity, [scope]))

    def test_single_document_has_exact_singleton_identity(self):
        self.meta.issingle = True
        self.assertTrue(self.authorized(authority._read('Education Settings', 'Education Settings')))
        self.assertFalse(self.authorized(authority._read('Education Settings', 'wrong')))
        frappe.get_list.assert_not_called()

    def test_view_admission_registers_group_and_finite_projection(self):
        scopes = self.adapter.view_scopes(self.identity, {'view': 'classroom_day', 'day': '2026-09-16', 'group': 'G1'})
        self.assertIn(authority._class('G1'), scopes)
        self.assertIn(authority._capability(authority.ATTENDANCE), scopes)
        self.assertTrue(self.adapter(self.identity, scopes))
        self.assertNotIn('owner', scopes[0]['selection'])

    def test_unknown_admin_view_or_payload_identity_never_calls_admin_fallback(self):
        for choice in ({'view': 'project_catalog'}, {'view': 'business_blueprint', 'proposal_id': 'anything'},
                       {'view': 'students', 'owner': 'Administrator'}, {'view': 'frappe_report', 'report': 'anything'}):
            self.assertFalse(self.authorized({'kind': 'view', 'selection': choice}))
        self.view_gate.assert_not_called()

    def test_native_document_and_create_views_resolve_exact_permissions(self):
        scope = self.adapter.view_scopes(self.identity, {'view': 'frappe_document', 'doctype': 'Student', 'document': 'S1'})
        self.assertIn(authority._read('Student', 'S1'), scope)
        create = self.adapter.view_scopes(self.identity, {'view': 'frappe_new', 'doctype': 'Student'})
        self.assertIn({'kind': 'doctype', 'doctype': 'Student', 'actions': ['create', 'read']}, create)
        with patch.object(frappe, 'has_permission', side_effect=lambda dt, action: action != 'create'):
            self.assertFalse(self.adapter(self.identity, create))

    def test_catalog_cannot_open_report_or_wrong_app_module(self):
        for selection in ({'view': 'frappe_catalog', 'kind': 'report'},
                          {'view': 'frappe_catalog', 'app': 'not_installed'},
                          {'view': 'frappe_catalog', 'module': 'Hidden'},
                          {'view': 'frappe_catalog', 'app': 'tongjianyun', 'module': 'Education'}):
            self.assertFalse(self.authorized({'kind': 'view', 'selection': selection}))
        self.assertTrue(self.authorized({'kind': 'view', 'selection': {'view': 'frappe_catalog', 'app': 'education', 'module': 'Education'}}))

    def test_field_permission_revocation_blocks_old_projection(self):
        self.assertTrue(self.authorized(authority._capability(authority.ATTENDANCE)))
        self.fields.side_effect = frappe.PermissionError('field no longer visible')
        self.assertFalse(self.authorized(authority._capability(authority.ATTENDANCE)))

    def test_finite_json_schema_and_max_scope_limits(self):
        for scopes in ([{'kind': 'class', 'group': 'G1', 'actions': ['read'], 'actor': 'Administrator'}],
                       [authority._class('G1')] * 257, ['anything']):
            self.assertFalse(self.adapter(self.identity, scopes))

    def test_attendance_readset_contains_actual_pupil_and_source_docs_not_names(self):
        read_set = authority.attendance_read_set(sources(students=('S1', 'S2'), leaves=('L1',)))
        for scope in (authority._class('G1'), authority._read('Student', 'S1'), authority._read('Student', 'S2'),
                      authority._read('Student Attendance', 'A1'), authority._read('Student Leave Application', 'L1')):
            self.assertIn(scope, read_set.scopes)
        self.assertNotIn('Secret Child', repr(read_set))

    def test_raw_or_model_latest_rows_cannot_be_claimed_a_complete_attendance_readset(self):
        for rows in ([{'student': 'S1', 'status': 'Present'}],
                     [{'student': 'S1', 'attendance_record': 'A1', 'leave_record': None}]):
            with self.assertRaisesRegex(ValueError, 'same-query'):
                authority.attendance_read_set({'students': rows})

    def original_attendance_sources(self):
        roster = [{'student': 'S1', 'student_name': 'Child', 'roll_number': 1}]
        records = [{'name': 'A1', 'student': 'S1', 'status': 'Present', 'modified': '2026-09-16 12:00:00'},
                   {'name': 'A0', 'student': 'S1', 'status': 'Absent', 'modified': '2026-09-16 09:00:00'}]
        leaves = [{'name': 'L1', 'student': 'S1', 'modified': '2026-09-16 12:00:00'},
                  {'name': 'L0', 'student': 'S1', 'modified': '2026-09-16 09:00:00'}]
        captured = []
        with patch.object(classroom, '_roster', return_value=roster), patch.object(classroom, '_can', return_value=True), \
                patch.object(frappe, 'get_list', side_effect=[records, leaves]) as reads:
            raw = classroom._attendance(SimpleNamespace(name='G1'), classroom._day('2026-09-16'), source_observer=captured.append)
        self.assertEqual(reads.call_count, 2)  # Same queries, no dependency re-query.
        self.assertEqual(len(captured), 1)
        return raw, captured[0]

    def test_same_student_older_attendance_and_leave_rows_are_not_dropped(self):
        raw, source = self.original_attendance_sources()
        self.assertEqual(raw['students'][0]['attendance_record'], 'A1')
        self.assertEqual(raw['students'][0]['leave_record'], 'L1')
        self.assertEqual(source.revision, raw['revision'])
        read_set = authority.attendance_read_set(source)
        for dt, names in (('Student Attendance', ('A1', 'A0')), ('Student Leave Application', ('L1', 'L0'))):
            for name in names:
                self.assertIn(authority._read(dt, name), read_set.scopes)
        self.assertNotIn('A0', str(raw))  # Existing public result shape is unchanged.
        self.assertNotIn('L0', str(raw))

    def test_older_revision_source_revocation_denies_history_despite_latest_still_visible(self):
        _, source = self.original_attendance_sources()
        for removed in ('A0', 'L0'):
            with self.subTest(removed=removed):
                self.identity = replace(self.identity, task_id=str(uuid.uuid4()))
                self.visible.update({'A0', 'A1', 'L0', 'L1'})
                store, claim = self.make_store()
                self.adapter.register_read(store, claim, authority.attendance_read_set(source))
                store.emit(claim, {'kind': 'message', 'item_id': 'attendance', 'text': '已读取出勤与版本'})
                self.visible.remove(removed)
                self.assertTrue(self.authorized(authority._read('Student Attendance', 'A1')))
                self.assertTrue(self.authorized(authority._read('Student Leave Application', 'L1')))
                with self.assertRaises(PermissionError):
                    store.events(self.identity)

    def make_store(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = tasks.BusinessTaskStore(temp.name, self.site, authorize=self.adapter,
            observe_execution=lambda *a: tasks.ExecutionObservation('none', 'unknown', 0),
            observe_queue=lambda *a: tasks.QueueObservation('none', 'unknown'))
        store.create(self.owner, self.identity.task_id, '本班点名', authority_scopes=[authority._class('G1')])
        ticket = store.take_dispatch(self.identity)
        store.acknowledge_dispatch(ticket)
        claim = store.claim(self.identity, ticket.job_id)
        return store, claim

    def test_real_task_core_registration_and_scope_revocation_stop_replay(self):
        assigned = {'G1', 'G2'}
        def group_guard(group):
            if group not in assigned:
                raise frappe.PermissionError('assignment revoked')
        self.scope.side_effect = group_guard
        store, claim = self.make_store()
        read_set = authority.attendance_read_set(sources())
        self.adapter.register_read(store, claim, read_set)
        store.emit(claim, {'kind': 'message', 'item_id': 'answer', 'text': '本班 1 人'})
        self.assertTrue(store.events(self.identity))
        assigned.remove('G1')  # Still teaches G2, but may not replay the old G1 answer.
        self.assertTrue(self.authorized(authority._class('G2')))
        with self.assertRaises(PermissionError):
            store.events(self.identity)
        with self.assertRaises(PermissionError):
            store.history(self.owner)
        # Inspect persistence through trusted store, not unauthorized task().
        with store._transaction() as db:
            self.assertEqual(db.execute('SELECT status FROM tasks').fetchone()['status'], 'stopping')

    def test_pupil_transfer_or_source_record_revocation_blocks_prior_text(self):
        for removed in ('S1', 'A1'):
            with self.subTest(removed=removed):
                self.identity = replace(self.identity, task_id=str(uuid.uuid4()))
                self.visible.update({'S1', 'A1'})
                store, claim = self.make_store()
                self.adapter.register_read(store, claim, authority.attendance_read_set(sources()))
                store.emit(claim, {'kind': 'message', 'item_id': 'a', 'text': '登记了出勤'})
                self.visible.remove(removed)
                with self.assertRaises(PermissionError):
                    store.events(self.identity)

    def test_denied_new_readset_is_not_registered_or_delivered(self):
        store, claim = self.make_store()
        prior = store.required_scopes(self.identity)
        with self.assertRaises(frappe.PermissionError):
            self.adapter.register_read(store, claim, authority.ReadSet((authority._read('Student', 'OUTSIDE'),)))
        self.assertEqual(store.required_scopes(self.identity), prior)

    def test_worker_claim_and_cancel_are_required_before_data_release(self):
        store, claim = self.make_store()
        with self.assertRaises(frappe.PermissionError):
            self.adapter.register_read(store, {'identity': self.identity}, authority.ReadSet(()))
        store.cancel(self.identity)
        with self.assertRaises(PermissionError):
            self.adapter.register_read(store, claim, authority.ReadSet((authority._class('G1'),)))

    def test_executable_attendance_reader_registers_raw_source_before_delivery(self):
        store, claim = self.make_store()
        raw = {'revision': 'a' * 64, 'counts': {'Present': 1}, 'students': [
            {'student': 'S1', 'student_name': 'Child', 'status': 'Present', 'source': '考勤登记',
             'attendance_record': 'A1', 'leave_record': None}]}
        def read(doc, day, *, source_observer):
            source_observer(sources())
            return raw
        with patch('tongjianyun.classroom._attendance', side_effect=read) as reader, \
                patch('tongjianyun.classroom._capabilities', return_value={'attendance_write': True}):
            result = self.adapter.read_attendance(store, claim, group='G1', day='2026-09-16')
        self.assertEqual(result['students'][0]['status'], 'Present')
        self.assertNotIn('attendance_record', result['students'][0])
        self.assertIn(authority._read('Student Attendance', 'A1'), store.required_scopes(self.identity))
        reader.assert_called_once()

    def test_executable_attendance_reader_never_delivers_a_revoked_source(self):
        store, claim = self.make_store()
        raw = {'revision': 'a' * 64, 'counts': {}, 'students': [
            {'student': 'S1', 'attendance_record': 'not_visible', 'leave_record': None}]}
        def read(doc, day, *, source_observer):
            source_observer(sources(attendance=('not_visible',)))
            return raw
        with patch('tongjianyun.classroom._attendance', side_effect=read), \
                patch('tongjianyun.classroom._capabilities', return_value={'attendance_write': True}):
            with self.assertRaises(frappe.PermissionError):
                self.adapter.read_attendance(store, claim, group='G1', day='2026-09-16')

    def test_executable_reader_requires_exactly_one_matching_source_observation(self):
        for observations in ([], [sources(revision='b' * 64)], [sources(), sources()]):
            with self.subTest(count=len(observations)):
                self.identity = replace(self.identity, task_id=str(uuid.uuid4()))
                store, claim = self.make_store()
                def read(doc, day, *, source_observer):
                    for observation in observations:
                        source_observer(observation)
                    return {'revision': 'a' * 64}
                with patch('tongjianyun.classroom._attendance', side_effect=read):
                    with self.assertRaises(frappe.PermissionError):
                        self.adapter.read_attendance(store, claim, group='G1', day='2026-09-16')

    def test_private_source_observer_does_not_change_public_signatures(self):
        import inspect
        for endpoint in (classroom.get_overview, classroom.save_attendance, classroom.get_meals, classroom.save_meal):
            self.assertNotIn('source_observer', inspect.signature(endpoint).parameters)
        with self.assertRaises(TypeError):
            classroom._attendance(SimpleNamespace(name='G1'), '2026-09-16', source_observer='model-method')

    def viewer(self):
        return authority.Viewer(self.site, self.owner, 'private-sid-' + 'a' * 32)

    def session_clock(self):
        self.stack.enter_context(patch('frappe.utils.now_datetime', return_value=datetime(2026, 9, 25, 12, 10)))
        self.stack.enter_context(patch('frappe.sessions.get_expiry_in_seconds', return_value=3600))

    def test_viewer_capture_uses_native_session_not_supplied_owner_or_worker_impersonation(self):
        self.session_clock()
        self.session.user, self.session.sid = self.owner, self.viewer().sid
        captured = self.adapter.capture_viewer()
        self.assertEqual(captured.owner, self.owner)
        self.assertNotIn(captured.sid, repr(captured))
        self.session.sid = self.owner  # frappe.set_user is NOT a browser login.
        with self.assertRaises(frappe.PermissionError):
            self.adapter.capture_viewer()

    def test_viewer_cross_owner_site_or_no_db_session_rejected_even_if_cached(self):
        self.session_clock()
        self.assertTrue(self.adapter.viewer_active(self.viewer(), self.identity))
        self.assertFalse(self.adapter.viewer_active(self.viewer(), replace(self.identity, owner='other@example.invalid')))
        self.assertFalse(self.adapter.viewer_active(replace(self.viewer(), site='other.localhost'), self.identity))
        self.cache.hget.return_value = {'user': self.owner, 'data': {'last_updated': '2026-09-25 12:05:00'}}
        self.session_record = None
        self.assertFalse(self.adapter.viewer_active(self.viewer()))

    def test_session_expiry_and_corrupt_or_mismatched_session_fail_closed(self):
        self.session_clock()
        for data in ({'last_updated': '2026-09-25 10:00:00'}, {'last_updated': '2026-09-25 14:00:00'},
                     {'user': 'Administrator'}, {'last_updated': 'not-a-time'},
                     {'last_updated': '2026-09-25 12:00:00', 'session_end': '2000-01-01T00:00:00+00:00'},
                     {'last_updated': '2026-09-25 12:00:00', 'session_end': '2099-01-01T00:00:00'}):
            self.session_record['sessiondata'] = json.dumps(data)
            self.assertFalse(self.adapter.viewer_active(self.viewer()))
        self.session_record['sessiondata'] = '{ broken'
        self.assertFalse(self.adapter.viewer_active(self.viewer()))

    def test_cached_activity_may_be_newer_but_must_have_same_owner(self):
        self.session_clock()
        self.session_record['sessiondata'] = json.dumps({'last_updated': '2026-09-25 09:00:00'})
        self.cache.hget.return_value = {'user': self.owner, 'data': {'last_updated': '2026-09-25 12:05:00'}}
        self.assertTrue(self.adapter.viewer_active(self.viewer()))
        self.cache.hget.return_value['user'] = 'Administrator'
        self.assertFalse(self.adapter.viewer_active(self.viewer()))
        self.db.commit.assert_not_called()

    def test_expired_browser_only_closes_stream_not_business_task(self):
        self.session_clock()
        store, claim = self.make_store()
        store.emit(claim, {'kind': 'message', 'item_id': 'a', 'text': '结果'})
        stream = store.stream(self.identity, authorize_viewer=lambda identity: self.adapter.viewer_active(self.viewer(), identity))
        next(stream)
        self.session_record = None
        frames = list(stream)
        self.assertTrue(any('unavailable' in frame for frame in frames))
        self.assertEqual(store.task(self.identity)['status'], 'running')


class FreshFrappeChecksTests(unittest.TestCase):
    def test_runner_uses_new_context_restores_caller_and_never_enters_as_admin(self):
        marker = ContextVar('authority-test', default='empty')
        marker.set('outer transaction')
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            init = stack.enter_context(patch.object(frappe, 'init'))
            connect = stack.enter_context(patch.object(frappe, 'connect'))
            destroy = stack.enter_context(patch.object(frappe, 'destroy'))
            stack.enter_context(patch.object(frappe, 'local', SimpleNamespace(site='qa.localhost')))
            actor = stack.enter_context(patch.object(frappe, 'set_user'))
            guard = MagicMock()
            runner = authority.FreshFrappeChecks('qa.localhost', directory, before_connect=guard)
            def callback():
                self.assertEqual(marker.get(), 'empty')
                marker.set('inner check')
                return 1
            self.assertEqual(runner('teacher@example.invalid', callback), 1)
            self.assertEqual(marker.get(), 'outer transaction')
            connect.assert_called_once_with(set_admin_as_user=False)
            actor.assert_called_once_with('teacher@example.invalid')
            guard.assert_called_once_with()
            destroy.assert_called_once_with()
            init.assert_called_once_with('qa.localhost', sites_path=str(Path(directory).resolve()))

    def test_guard_failure_never_connects_and_closes_own_context(self):
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch.object(frappe, 'init'))
            connect = stack.enter_context(patch.object(frappe, 'connect'))
            destroy = stack.enter_context(patch.object(frappe, 'destroy'))
            runner = authority.FreshFrappeChecks('qa.localhost', directory, before_connect=MagicMock(side_effect=ValueError('wrong QA DB')))
            with self.assertRaises(ValueError):
                runner('teacher@example.invalid', lambda: True)
            connect.assert_not_called()
            destroy.assert_called_once_with()

    def test_field_projection_uses_native_parent_type_permission(self):
        with patch('frappe.model.get_permitted_fields', return_value=['name', 'student']) as fields, \
                patch.object(frappe, 'session', SimpleNamespace(user='teacher@example.invalid')):
            authority._fields('Student Group Student', ['student'], parenttype='Student Group')
            fields.assert_called_once_with('Student Group Student', parenttype='Student Group',
                                           user='teacher@example.invalid', permission_type='read')
            with self.assertRaises(frappe.PermissionError):
                authority._fields('Student Group Student', ['student_name'], parenttype='Student Group')

    def test_class_discovery_and_roster_order_fields_are_explicit_projections(self):
        with patch.object(authority, '_doctype') as doctype, patch.object(authority, '_fields') as fields, \
                patch.object(authority, '_table_field', return_value='Student Group Student'):
            authority._projection(authority.GROUPS)
            doctype.assert_called_once_with('Student Group', ['read'])
            fields.assert_called_once_with('Student Group', ('student_group_name', 'academic_year', 'disabled'))
            fields.reset_mock()
            authority._projection(authority.ROSTER)
            fields.assert_any_call('Student Group Student', ('student', 'active', 'group_roll_number'),
                                   parenttype='Student Group')

    def test_table_field_permission_is_not_inferred_from_missing_sql_column(self):
        meta = MagicMock()
        meta.get_field.return_value = SimpleNamespace(fieldtype='Table', options='Child', permlevel=1)
        meta.get_permlevel_access.return_value = [0, 1]
        with patch.object(frappe, 'get_meta', return_value=meta), \
                patch.object(frappe, 'session', SimpleNamespace(user='teacher@example.invalid')):
            self.assertEqual(authority._table_field('Parent', 'rows'), 'Child')
            meta.get_permlevel_access.return_value = [0]
            with self.assertRaises(frappe.PermissionError):
                authority._table_field('Parent', 'rows')


if __name__ == '__main__':
    unittest.main()
