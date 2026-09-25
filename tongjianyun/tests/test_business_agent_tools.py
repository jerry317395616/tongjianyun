"""No live business writes: task/identity gates and original-service contracts."""
import unittest
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from tongjianyun import business_agent_tools as tools, classroom, meal_views, scene_access


class BusinessAgentToolsTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.task = dict(task_id='task-1', owner='teacher@example.invalid', site='qa.localhost',
                         mode='business', status='running', cancel_requested=False)
        self.account = {'enabled': 1, 'user_type': 'System User'}
        self.db = MagicMock()
        self.db.get_value.side_effect = lambda *a, **kw: self.account
        self.cache = defaultdict(dict, {'original': {'result': 'not for teacher'}})
        self.local = SimpleNamespace(site='qa.localhost', flags={}, request_cache=self.cache)
        self.session = SimpleNamespace(user='broker')
        self.stack.enter_context(patch.object(frappe, 'local', self.local))
        self.stack.enter_context(patch.object(frappe, 'session', self.session))
        self.stack.enter_context(patch.object(frappe, 'db', self.db))
        self.stack.enter_context(patch.object(frappe, 'has_permission', return_value=True))
        self.set_user = self.stack.enter_context(patch.object(frappe, 'set_user', side_effect=self.set_actor))
        self.read_task = MagicMock(side_effect=lambda task_id: dict(self.task))
        self.publish = MagicMock()
        self.binding = tools.BusinessBinding(self.task['owner'], self.task['site'], self.task['task_id'],
                                             self.read_task, self.publish)
        self.attendance = {'group': 'G1', 'day': '2026-09-17', 'revision': 'a' * 64,
                           'counts': {'Present': 0, 'Unknown': 1},
                           'students': [{'student': 'S1', 'student_name': 'Test', 'status': 'Unknown'}]}
        self.att_args = {'group': 'G1', 'day': '2026-09-17', 'revision': 'a' * 64,
                         'changes': [{'student': 'S1', 'status': 'Present'}]}
        self.meal_args = {'group': 'G1', 'day': '2026-09-17', 'meal': 'lunch',
                          'revision': '', 'confirm': True, 'students': [{'student': 'S1', 'value': '就餐'}]}

    def set_actor(self, actor):
        self.session.user = actor

    def run_read(self):
        with patch.object(tools, '_classroom_read', return_value=self.attendance) as service:
            return tools.dispatch(self.binding, 'classroom_read', {'group': 'G1', 'day': '2026-09-17'}), service

    def executor(self, binding, call_id, digest, operation):
        self.assertEqual(self.session.user, self.task['owner'])
        self.assertEqual(call_id, 'call-1')
        self.assertRegex(digest, '^[a-f0-9]{64}$')
        result = operation()
        tools.validate_binding(binding)
        self.assertEqual(result['transaction'], 'pending_commit')
        # Mock executor's declared commit; the core must not do a DB commit.
        return tools.WriteOutcome('committed', result)

    def test_enabled_owner_runs_tool_and_restores_identity_and_request_cache(self):
        def read(args):
            self.assertEqual(self.session.user, self.task['owner'])
            self.assertIsNot(self.local.request_cache, self.cache)
            self.assertNotIn('original', self.local.request_cache)
            self.local.request_cache['teacher']['secret'] = 1
            return self.attendance
        with patch.object(tools, '_classroom_read', side_effect=read):
            result = tools.dispatch(self.binding, 'classroom_read', {'group': 'G1', 'day': '2026-09-17'})
        self.assertEqual(result, self.attendance)
        self.assertEqual(self.session.user, 'broker')
        self.assertIs(self.local.request_cache, self.cache)
        self.assertNotIn('teacher', self.cache)
        self.assertGreaterEqual(self.read_task.call_count, 3)
        self.db.get_value.assert_called_with('User', self.task['owner'], ['enabled', 'user_type'], as_dict=True)

    def test_recipe_calendar_selection_is_finite_and_not_an_old_meal_write(self):
        selection = {'view': 'recipe_week', 'day': '2026-09-24', 'meal': 'lunch'}
        self.assertEqual(tools._validate_arguments('business_view', {'selection': selection}), {'selection': selection})
        for key in ('recipe', 'revision', 'group', 'payload', 'owner', 'offset'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                tools._validate_arguments('business_view', {'selection': {**selection, key: 'x'}})
        for tool in ('recipe_read', 'recipe_save'):
            # New native recipe adapters own these operations. Legacy dispatch
            # must not silently fall through to classroom's meal service.
            with (self.subTest(tool=tool), patch.object(tools, '_meal_read') as meal_read,
                    patch.object(tools, '_write') as write, self.assertRaises(ValueError)):
                tools.dispatch(self.binding, tool, {'day': '2026-09-24'})
            meal_read.assert_not_called()
            write.assert_not_called()

    def test_original_exception_restores_actor_and_cache(self):
        with patch.object(tools, '_classroom_read', side_effect=RuntimeError('read failure')):
            with self.assertRaisesRegex(RuntimeError, 'read failure'):
                tools.dispatch(self.binding, 'classroom_read', {'group': 'G1', 'day': '2026-09-17'})
        self.assertEqual(self.session.user, 'broker')
        self.assertIs(self.local.request_cache, self.cache)

    def test_identity_switch_failure_still_attempts_restoration(self):
        def switch(user):
            if user != 'broker':
                raise RuntimeError('switch failed')
            self.session.user = user
        self.set_user.side_effect = switch
        with self.assertRaisesRegex(RuntimeError, 'switch failed'):
            self.run_read()
        self.assertEqual(self.set_user.call_args.args, ('broker',))

    def test_task_identity_site_mode_and_liveness_are_immutable(self):
        for key, value in [('owner', 'Administrator'), ('site', 'other.localhost'), ('task_id', 'task-2'),
                           ('mode', 'admin_project'), ('status', 'queued'), ('status', 'complete'),
                           ('cancel_requested', True), ('cancel_requested', '1'), ('cancel_requested', None)]:
            with self.subTest(key=key, value=value):
                original = self.task[key]
                self.task[key] = value
                try:
                    with self.assertRaises(frappe.PermissionError):
                        self.run_read()
                finally:
                    self.task[key] = original
        self.set_user.assert_not_called()

    def test_missing_cancel_field_fails_closed(self):
        self.task.pop('cancel_requested')
        with self.assertRaises(frappe.PermissionError):
            self.run_read()

    def test_write_guard_requests_current_account_row_lock_without_actor_override(self):
        tools.validate_binding(self.binding, lock_owner=True)
        self.db.get_value.assert_called_once_with('User', self.task['owner'], ['enabled', 'user_type'],
                                                  as_dict=True, for_update=True)
        self.assertEqual(self.session.user, 'broker')
        with self.assertRaises(ValueError):
            tools.validate_binding(self.binding, lock_owner='1')

    def test_current_user_snapshot_conflict_and_lock_timeout_are_fail_closed(self):
        for error in (frappe.QueryDeadlockError('snapshot changed'), frappe.QueryTimeoutError('lock timed out')):
            self.db.get_value.side_effect = error
            with self.subTest(error=type(error)), self.assertRaises(frappe.PermissionError):
                tools.validate_binding(self.binding, lock_owner=True)
        self.db.commit.assert_not_called()
        self.db.rollback.assert_not_called()

    def test_ambient_frappe_site_must_match(self):
        self.local.site = 'production.localhost'
        with self.assertRaises(frappe.PermissionError):
            self.run_read()
        self.read_task.assert_not_called()

    def test_disabled_website_guest_and_missing_account_denied(self):
        for account in (None, {}, {'enabled': 0, 'user_type': 'System User'},
                        {'enabled': 1, 'user_type': 'Website User'}):
            with self.subTest(account=account):
                self.account = account
                with self.assertRaises(frappe.PermissionError):
                    self.run_read()
        with self.assertRaises(frappe.PermissionError):
            tools.validate_binding(replace(self.binding, owner='Guest'))

    def test_permission_bypass_framework_flags_denied(self):
        for flag in ('ignore_permissions', 'in_install', 'in_migrate', 'in_patch'):
            self.local.flags = {flag: True}
            with self.subTest(flag=flag), self.assertRaises(frappe.PermissionError):
                self.run_read()

    def test_cancellation_during_read_discards_result(self):
        def read(args):
            self.task['cancel_requested'] = True
            return self.attendance
        with patch.object(tools, '_classroom_read', side_effect=read), self.assertRaises(frappe.PermissionError):
            tools.dispatch(self.binding, 'classroom_read', {'group': 'G1', 'day': '2026-09-17'})
        self.assertEqual(self.session.user, 'broker')

    def test_owner_disabled_during_read_discards_result(self):
        def read(args):
            self.account['enabled'] = 0
            return self.attendance
        with patch.object(tools, '_classroom_read', side_effect=read), self.assertRaises(frappe.PermissionError):
            tools.dispatch(self.binding, 'classroom_read', {'group': 'G1', 'day': '2026-09-17'})

    def test_read_task_failure_does_not_run_tool(self):
        self.read_task.side_effect = RuntimeError('task store unavailable')
        with patch.object(tools, '_classroom_read') as read, self.assertRaises(RuntimeError):
            tools.dispatch(self.binding, 'classroom_read', {'group': 'G1', 'day': '2026-09-17'})
        read.assert_not_called()

    def test_unknown_tool_and_identity_or_code_arguments_are_rejected_before_query(self):
        for tool in ('frappe.client.save', 'sql', 'exec', 'read_file', '', None):
            with self.subTest(tool=tool), self.assertRaises(ValueError):
                tools.dispatch(self.binding, tool, {})
        for field in ('site', 'actor', 'owner', 'user', 'method', 'sql', 'ignore_permissions', 'workspace', 'operation_id'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                tools.dispatch(self.binding, 'classroom_read', {'group': 'G1', 'day': '2026-09-17', field: 'x'})
        self.read_task.assert_not_called()

    def test_only_finite_bounded_json_objects_are_accepted(self):
        for args in (None, [], '{"group":"G1"}', {'group': float('nan'), 'day': '2026-09-17'},
                     {'group': object(), 'day': '2026-09-17'}, {'group': 'x' * 140000, 'day': '2026-09-17'}):
            with self.subTest(kind=type(args)), self.assertRaises(ValueError):
                tools.dispatch(self.binding, 'classroom_read', args)

    def test_day_group_and_meal_validation(self):
        for day in ('2026-02-30', '2026-9-17', '', 1, None):
            with self.subTest(day=day), self.assertRaises(ValueError):
                tools.dispatch(self.binding, 'classroom_read', {'group': 'G1', 'day': day})
        for group in ('', ' ', 'G\x00', 'x' * 141, ['G1'], True):
            with self.subTest(group=group), self.assertRaises(ValueError):
                tools.dispatch(self.binding, 'classroom_read', {'group': group, 'day': '2026-09-17'})
        for meal in ('Lunch', '', ['lunch'], None):
            with self.subTest(meal=meal), self.assertRaises(ValueError):
                tools.dispatch(self.binding, 'scene_bootstrap', {'day': '2026-09-17', 'meal': meal})

    def test_scene_bootstrap_does_not_return_owner_chat_or_unrelated_boot_payload(self):
        data = {'version': 1, 'day': '2026-09-17', 'meal': 'lunch', 'default_view': {'view': 'students'},
                'navigation': [], 'scope': {'group_count': 1}, 'user': 'hidden', 'chat': {'allowed': False}}
        with patch.object(scene_access, 'get_bootstrap', return_value=data) as bootstrap:
            result = tools.dispatch(self.binding, 'scene_bootstrap', {'day': '2026-09-17', 'group': 'G1'})
        bootstrap.assert_called_once_with(day='2026-09-17', group='G1')
        self.assertNotIn('user', result)
        self.assertNotIn('chat', result)

    def test_view_publishes_checked_selection_but_only_summary_returns_to_model(self):
        data = {'selection': {'view': 'students', 'presentation': 'table'}, 'title': '在园学生',
                'summary': {'student_count': 2}, 'components': [{'rows': ['private student']}],
                'document': {'password': 'must not return'}}
        with patch.object(meal_views, 'get_view', return_value=data) as read:
            result = tools.dispatch(self.binding, 'business_view', {'selection': {'view': 'students'}})
        read.assert_called_once_with({'view': 'students'})
        self.publish.assert_called_once_with(self.binding, {'kind': 'view', 'version': 1,
                                             'selection': data['selection'], 'title': '在园学生'})
        self.assertTrue(result['display_requested'])
        self.assertEqual(result['summary'], {'student_count': 2})
        self.assertNotIn('components', result)
        self.assertNotIn('document', result)
        self.assertNotIn('private student', str(result))

    def test_view_can_query_without_publishing_and_cannot_claim_displayed(self):
        with patch.object(meal_views, 'get_view', return_value={'selection': {'view': 'students'}, 'title': '学生'}):
            result = tools.dispatch(self.binding, 'business_view', {'selection': {'view': 'students'}, 'publish': False})
        self.publish.assert_not_called()
        self.assertFalse(result['display_requested'])
        self.assertNotIn('displayed', result)

    def test_view_cancelled_or_permission_denied_never_publishes(self):
        def cancelled(choice):
            self.task['status'] = 'complete'
            return {'selection': choice, 'title': '学生'}
        with patch.object(meal_views, 'get_view', side_effect=cancelled), self.assertRaises(frappe.PermissionError):
            tools.dispatch(self.binding, 'business_view', {'selection': {'view': 'students'}})
        self.publish.assert_not_called()
        self.task['status'] = 'running'
        with patch.object(meal_views, 'get_view', side_effect=frappe.PermissionError), self.assertRaises(frappe.PermissionError):
            tools.dispatch(self.binding, 'business_view', {'selection': {'view': 'students'}})
        self.publish.assert_not_called()

    def test_view_root_blueprint_report_custom_html_and_components_rejected(self):
        for choice in ({'view': 'project_catalog'}, {'view': 'business_blueprint', 'proposal_id': 'x'},
                       {'view': 'frappe_report', 'report': 'Salary'}, {'view': 'students', 'components': ['table']},
                       {'view': 'students', 'url': 'https://evil.invalid'}, {'view': 'students', 'html': '<script>'},
                       {'view': 'frappe_document', 'doctype': 'User', 'document': 'x', 'ignore_permissions': 1},
                       {'view': 'class_students', 'group': 'G1', 'offset': True}):
            with self.subTest(choice=choice), self.assertRaises(ValueError):
                tools.dispatch(self.binding, 'business_view', {'selection': choice})
        self.read_task.assert_not_called()

    def test_classroom_read_reuses_original_scope_and_omits_unrelated_sensitive_payload(self):
        rows = [{'student': 'S1', 'student_name': 'Test', 'status': 'Present', 'source': '考勤登记',
                 'leave_record': 'secret leave id', 'contact_phone': 'not requested'}]
        data = {'students': rows, 'revision': 'a' * 64, 'counts': {'Present': 1}}
        with patch.object(classroom, '_scope', return_value=SimpleNamespace(name='G1')) as scope, \
             patch.object(classroom, '_attendance', return_value=data), \
             patch.object(classroom, '_capabilities', return_value={'attendance_write': True}), \
             patch.object(classroom, 'get_overview') as overview:
            result = tools.dispatch(self.binding, 'classroom_read', {'group': 'G1', 'day': '2026-09-17'})
        scope.assert_called_once_with('G1')
        overview.assert_not_called()
        self.assertEqual(result['students'][0], {key: rows[0][key] for key in ('student', 'student_name', 'status', 'source')})
        self.assertNotIn('secret leave', str(result))

    def test_cross_class_rejected_by_real_original_scope_before_document_read(self):
        with patch.object(classroom, 'require_user'), patch.object(classroom, '_groups', return_value=['G1']), \
             patch.object(frappe, 'get_doc') as document:
            with self.assertRaises(frappe.PermissionError):
                tools.dispatch(self.binding, 'classroom_read', {'group': 'FOREIGN', 'day': '2026-09-17'})
        document.assert_not_called()

    def test_meal_read_omits_full_document_and_other_account_indices(self):
        data = {'revision': 'modified', 'record': {'owner': 'hidden', 'name': 'hidden', 'students': [
                    {'student': 'S1', 'student_name': 'Test', 'lunch': '未确认', 'lunch_expected': 1,
                     'owner': 'hidden', 'parent': 'hidden'}]}, 'meals': {'lunch': {'actual': None}},
                'groups': ['G1', 'FOREIGN']}
        with patch.object(classroom, 'get_meals', return_value=data) as read:
            result = tools.dispatch(self.binding, 'meal_read', {'group': 'G1', 'day': '2026-09-17'})
        read.assert_called_once_with('G1', '2026-09-17')
        self.assertNotIn('record', result)
        self.assertNotIn('hidden', str(result))
        self.assertNotIn('FOREIGN', str(result))
        self.assertIsNone(result['meals']['lunch']['actual'])

    def test_write_requires_trusted_executor_and_stable_call_id(self):
        with patch.object(classroom, 'save_attendance') as save:
            for binding in (self.binding, replace(self.binding, execute_write=self.executor),
                            replace(self.binding, execute_write=self.executor, call_id='../bad')):
                with self.subTest(binding=binding.call_id), self.assertRaises(ValueError):
                    tools.dispatch(binding, 'attendance_save', self.att_args)
        save.assert_not_called()

    def test_attendance_write_preserves_revision_and_original_service_then_reads_back(self):
        binding = replace(self.binding, execute_write=self.executor, call_id='call-1')
        with patch.object(classroom, 'save_attendance') as save, \
             patch.object(tools, '_classroom_read', return_value=self.attendance) as read:
            result = tools.dispatch(binding, 'attendance_save', self.att_args)
        save.assert_called_once_with('G1', '2026-09-17', self.att_args['changes'], 'a' * 64)
        self.assertEqual(read.call_count, 2)
        read.assert_called_with(self.att_args)
        self.assertTrue(result['committed'])
        self.assertEqual(result['readback'], self.attendance)
        self.assertEqual(result['selection']['view'], 'classroom_day')
        self.db.commit.assert_not_called()
        self.db.rollback.assert_not_called()
        self.publish.assert_not_called()
        self.assertEqual(self.session.user, 'broker')

    def test_single_meal_write_preserves_original_confirmation_and_change_reason(self):
        binding = replace(self.binding, execute_write=self.executor, call_id='call-1')
        args = {**self.meal_args, 'revision': '2026-09-17 10:22:33.123456', 'change_reason': '核对实际用餐'}
        with patch.object(classroom, 'save_meal') as save, patch.object(classroom, 'save_meals') as whole_day, \
             patch.object(tools, '_meal_read', return_value={'revision': 'new', 'meals': {'lunch': {'actual': 1}}}):
            result = tools.dispatch(binding, 'meal_save', args)
        save.assert_called_once_with('G1', '2026-09-17', 'lunch', args['students'], args['revision'], 1, args['change_reason'])
        whole_day.assert_not_called()
        self.assertTrue(result['committed'])
        self.assertEqual(result['selection']['meal'], 'lunch')

    def test_original_revision_lock_or_full_roster_failure_propagates_without_commit(self):
        binding = replace(self.binding, execute_write=self.executor, call_id='call-1')
        for message in ('stale revision', 'day locked', 'foreign student', 'incomplete roster', 'reason required'):
            with self.subTest(message=message), patch.object(classroom, 'save_meal', side_effect=ValueError(message)), \
                 patch.object(tools, '_meal_read') as read, self.assertRaisesRegex(ValueError, message):
                tools.dispatch(binding, 'meal_save', self.meal_args)
            read.assert_not_called()
        self.assertEqual(self.session.user, 'broker')
        self.db.commit.assert_not_called()

    def test_fresh_readback_failure_does_not_claim_success(self):
        binding = replace(self.binding, execute_write=self.executor, call_id='call-1')
        with patch.object(classroom, 'save_attendance'), \
             patch.object(tools, '_classroom_read', side_effect=RuntimeError('readback failed')), \
             self.assertRaisesRegex(RuntimeError, 'readback failed'):
            tools.dispatch(binding, 'attendance_save', self.att_args)

    def test_write_cancellation_after_original_service_prevents_committed_outcome(self):
        binding = replace(self.binding, execute_write=self.executor, call_id='call-1')
        def save(*args):
            self.task['cancel_requested'] = True
        with patch.object(classroom, 'save_attendance', side_effect=save), \
             patch.object(tools, '_classroom_read', return_value=self.attendance), self.assertRaises(frappe.PermissionError):
            tools.dispatch(binding, 'attendance_save', self.att_args)
        self.assertEqual(self.session.user, 'broker')

    def test_delayed_executor_cannot_run_operation_with_lost_actor(self):
        def execute(binding, call_id, digest, operation):
            self.session.user = 'Administrator'
            return operation()
        binding = replace(self.binding, execute_write=execute, call_id='call-1')
        with patch.object(classroom, 'save_attendance') as save, self.assertRaises(frappe.PermissionError):
            tools.dispatch(binding, 'attendance_save', self.att_args)
        save.assert_not_called()
        self.assertEqual(self.session.user, 'broker')

    def test_uncertain_outcome_does_not_repeat_or_disclose_uncommitted_snapshot(self):
        execute = MagicMock(return_value=tools.WriteOutcome('uncertain', {'readback': {'actual': 42}}))
        binding = replace(self.binding, execute_write=execute, call_id='call-1')
        with patch.object(classroom, 'save_attendance') as save:
            result = tools.dispatch(binding, 'attendance_save', self.att_args)
        save.assert_not_called()
        self.assertEqual(result['status'], 'uncertain')
        self.assertIsNone(result['committed'])
        self.assertFalse(result['retry_allowed'])
        self.assertNotIn('readback', result)

    def test_cached_committed_outcome_rechecks_scope_and_returns_only_current_authorized_snapshot(self):
        old = {'readback': self.attendance, 'selection': {'view': 'classroom_day'}, 'transaction': 'pending_commit'}
        binding = replace(self.binding, execute_write=MagicMock(return_value=tools.WriteOutcome('committed', old, True)),
                          call_id='call-1')
        current = {**self.attendance, 'revision': 'b' * 64, 'students': []}
        with patch.object(classroom, 'save_attendance') as save, patch.object(tools, '_classroom_read', return_value=current):
            result = tools.dispatch(binding, 'attendance_save', self.att_args)
        save.assert_not_called()
        self.assertTrue(result['replayed'])
        self.assertEqual(result['readback'], current)
        self.assertNotIn('S1', str(result['readback']))
        self.assertEqual(result['original_revision'], 'a' * 64)

    def test_old_receipt_cannot_bypass_revoked_class_scope_for_same_id_or_new_id(self):
        old = {'readback': self.attendance, 'selection': {'view': 'classroom_day'}, 'transaction': 'pending_commit'}
        execute = MagicMock(return_value=tools.WriteOutcome('committed', old, True))
        for call_id in ('call-1', 'new-alias-id'):
            binding = replace(self.binding, execute_write=execute, call_id=call_id)
            with self.subTest(call_id=call_id), patch.object(classroom, 'save_attendance') as save, \
                 patch.object(tools, '_classroom_read', side_effect=frappe.PermissionError), \
                 self.assertRaises(frappe.PermissionError):
                tools.dispatch(binding, 'attendance_save', self.att_args)
            save.assert_not_called()

    def test_postcommit_fresh_read_failure_does_not_claim_write_failed_or_return_old_names(self):
        old = {'readback': self.attendance, 'selection': {'view': 'classroom_day'}, 'transaction': 'pending_commit'}
        binding = replace(self.binding, execute_write=MagicMock(return_value=tools.WriteOutcome('committed', old)), call_id='call-1')
        with patch.object(tools, '_classroom_read', side_effect=RuntimeError('database unavailable')):
            result = tools.dispatch(binding, 'attendance_save', self.att_args)
        self.assertTrue(result['committed'])
        self.assertFalse(result['readback_available'])
        self.assertFalse(result['retry_allowed'])
        self.assertNotIn('readback', result)

    def test_revoked_scope_after_new_commit_cannot_return_original_names(self):
        old = {'readback': self.attendance, 'selection': {'view': 'classroom_day'}, 'transaction': 'pending_commit'}
        binding = replace(self.binding, execute_write=MagicMock(return_value=tools.WriteOutcome('committed', old)), call_id='call-1')
        with patch.object(tools, '_classroom_read', side_effect=frappe.PermissionError), self.assertRaises(frappe.PermissionError):
            tools.dispatch(binding, 'attendance_save', self.att_args)

    def test_executor_must_declare_commit_with_readback_not_just_saved_true(self):
        for outcome in ({'saved': True}, tools.WriteOutcome('success'), tools.WriteOutcome('committed', {})):
            binding = replace(self.binding, execute_write=MagicMock(return_value=outcome), call_id='call-1')
            with self.subTest(outcome=outcome), self.assertRaises(RuntimeError):
                tools.dispatch(binding, 'attendance_save', self.att_args)

    def test_digest_stable_across_key_order_but_revision_distinguishes_legitimate_edit(self):
        digests = []
        def execute(binding, call_id, digest, operation):
            digests.append(digest)
            return tools.WriteOutcome('uncertain')
        binding = replace(self.binding, execute_write=execute, call_id='call-1')
        tools.dispatch(binding, 'attendance_save', self.att_args)
        tools.dispatch(replace(binding, call_id='new-call-id'), 'attendance_save', dict(reversed(list(self.att_args.items()))))
        tools.dispatch(binding, 'attendance_save', {**self.att_args, 'revision': 'b' * 64})
        self.assertEqual(digests[0], digests[1])
        self.assertNotEqual(digests[0], digests[2])

    def test_attendance_rows_reject_hidden_fields_duplicates_unknown_and_missing_reason(self):
        for rows in ([], [{'student': 'S1', 'status': 'Present'}] * 2,
                     [{'student': 'S1', 'status': 'Unknown'}], [{'student': 'S1', 'status': 'Leave'}],
                     [{'student': 'S1', 'status': 'Present', 'ignore_permissions': True}],
                     [{'student': 'S1', 'status': 'Leave', 'leave_reason': 'x' * 1001}],
                     [{'student': f'S{x}', 'status': 'Present'} for x in range(501)]):
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError):
                tools.dispatch(self.binding, 'attendance_save', {**self.att_args, 'changes': rows})

    def test_attendance_revision_cannot_be_omitted_or_coerced(self):
        for revision in ('', None, 123, 'x' * 64, 'a' * 63):
            with self.subTest(revision=revision), self.assertRaises(ValueError):
                tools.dispatch(self.binding, 'attendance_save', {**self.att_args, 'revision': revision})

    def test_meal_tool_requires_boolean_confirmation_full_rows_and_exact_finite_fields(self):
        bad = [{**self.meal_args, 'confirm': v} for v in (0, 1, '1', None)]
        bad += [{**self.meal_args, 'students': [{'student': 'S1', 'value': '就餐', 'dinner': '就餐'}]},
                {**self.meal_args, 'students': [{'student': 'S1', 'value': '未确认'}]},
                {**self.meal_args, 'students': []}, {**self.meal_args, 'revision': None},
                {**self.meal_args, 'change_reason': 'x' * 1001}]
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ValueError):
                tools.dispatch(self.binding, 'meal_save', args)


if __name__ == '__main__':
    unittest.main()
