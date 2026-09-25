"""Original roster + real durable scope store; no models or business writes."""
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import uuid

import frappe
from frappe import _dict
from tongjianyun import classroom
from tongjianyun import business_agent_authority as gates
from tongjianyun import business_agent_reads as reads
from tongjianyun.business_agent_tasks import BusinessTaskStore, TaskIdentity, QueueObservation, ExecutionObservation


class BusinessReadsTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.folder = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.site, self.owner = 'qa.localhost', 'teacher@example.invalid'
        self.identity = TaskIdentity(self.site, self.owner, str(uuid.uuid4()))
        self.session = SimpleNamespace(user='outer-user')
        self.stack.enter_context(patch.object(frappe, 'session', self.session))
        self.stack.enter_context(patch.object(frappe, 'has_permission', return_value=True))
        self.account = self.stack.enter_context(patch.object(gates, '_account', side_effect=self.check_actor))
        self.projection = self.stack.enter_context(patch.object(gates, '_projection'))
        self.stack.enter_context(patch('tongjianyun.scene_access.require_scene_account'))
        self.groups = {'G1': self.group('G1', ['S1', 'S2', 'S3']), 'G2': self.group('G2', ['S4'])}
        self.assigned = {'G1', 'G2'}
        self.students = {name: _dict(name=name, student_name='合成' + name, enabled=1) for name in ['S1', 'S2', 'S3', 'S4']}
        self.visible = set(self.students)
        self.scope_check = self.stack.enter_context(patch.object(gates, '_check_scope', side_effect=self.check_scope))
        self.native_scope = self.stack.enter_context(patch.object(classroom, '_scope', side_effect=self.scope))
        self.allowed = self.stack.enter_context(patch('tongjianyun.attendance_scope.allowed_groups', side_effect=lambda: sorted(self.assigned)))
        self.queries = []
        self.get_list = self.stack.enter_context(patch.object(frappe, 'get_list', side_effect=self.query))
        self.after_query = None
        def fresh(owner, callback):
            previous = self.session.user
            self.session.user = owner
            try:
                return callback()
            finally:
                self.session.user = previous
        self.adapter = gates.FrappeBusinessAuthority(self.site, run_check=fresh)
        self.store = BusinessTaskStore(self.folder, self.site, authorize=self.adapter,
            observe_queue=lambda job: QueueObservation(job, 'present'),
            observe_execution=lambda identity, claim: ExecutionObservation(claim, 'running', 0))
        self.store.create(self.owner, self.identity.task_id, '查看本班名单', {})
        ticket = self.store.take_dispatch(self.identity)
        self.store.acknowledge_dispatch(ticket)
        self.claim = self.store.claim(self.identity, ticket.job_id)
        self.reader = reads.BusinessReads(self.adapter, self.store)

    @staticmethod
    def group(name, students):
        return _dict(name=name, student_group_name='测试' + name, academic_year='2026-2027',
            students=[_dict(student=s, active=1, group_roll_number=i + 1) for i, s in enumerate(students)])

    def check_actor(self, owner, site):
        if owner != self.owner or site != self.site or self.session.user != owner:
            raise frappe.PermissionError('wrong actor')

    def scope(self, group):
        if group not in self.assigned:
            raise frappe.PermissionError('outside class')
        return self.groups[group]

    def check_scope(self, scope):
        if scope['kind'] == 'class':
            self.scope(scope['group'])
        elif scope['kind'] == 'document':
            if scope['doctype'] == 'Student Group':
                self.scope(scope['document'])
            elif scope['doctype'] == 'Student' and scope['document'] not in self.visible:
                raise frappe.PermissionError('Student source revoked')
        elif scope['kind'] == 'capability':
            self.projection(scope['name'])

    def query(self, doctype, **kwargs):
        self.assertEqual(self.session.user, self.owner)
        self.queries.append((doctype, kwargs))
        if doctype == 'Student':
            names = kwargs['filters']['name'][1]
            rows = [self.students[name] for name in names if name in self.visible and self.students[name].enabled]
            rows = rows[:kwargs['limit_page_length']] if kwargs['limit_page_length'] else rows
        else:
            self.assertEqual(doctype, 'Student Group')
            after = next((f[3] for f in kwargs['filters'] if f[1:3] == ['name', '>']), '')
            rows = [self.groups[name] for name in sorted(self.assigned) if name > after][:kwargs['limit_page_length']]
        if self.after_query:
            callback, self.after_query = self.after_query, None
            callback()
        return rows

    def call(self, tool='class_students_read', **arguments):
        return self.reader.dispatch(self.claim, tool, arguments or {'group': 'G1'})

    def scopes(self):
        return self.store.required_scopes(self.identity)

    def test_discovery_uses_native_assignment_list_permissions_and_current_actor(self):
        result = self.call('scene_bootstrap', day='2026-09-16', page_size=1)
        self.assertEqual(result['groups'], [{'group': 'G1', 'label': '测试G1', 'academic_year': '2026-2027'}])
        self.assertTrue(result['has_more'])
        self.assertIsNone(result['visible_group_count'])
        self.assertEqual(result['next_after'], 'G1')
        self.assertEqual(self.queries[0][1]['limit_page_length'], 2)
        self.assertIn(gates._read('Student Group', 'G2'), self.scopes())
        self.assertIn(gates._class('G2'), self.scopes())
        self.assertEqual(self.session.user, 'outer-user')
        self.assertNotIn('user', result)
        self.assertNotIn('user_label', result)
        self.assertNotIn('admin_project', str(result))

    def test_group_next_page_has_no_whole_school_count(self):
        result = self.call('scene_bootstrap', day='2026-09-16', after='G1')
        self.assertEqual([r['group'] for r in result['groups']], ['G2'])
        self.assertFalse(result['has_more'])
        self.assertIsNone(result['visible_group_count'])
        self.assertIn('不是全园', result['scope'])

    def test_empty_authorized_groups_is_distinct_from_no_group_permission(self):
        self.assigned.clear()
        result = self.call('scene_bootstrap', day='2026-09-16')
        self.assertEqual(result['visible_group_count'], 0)
        self.assertTrue(result['groups_available'])
        self.projection.side_effect = lambda name: (_ for _ in ()).throw(frappe.PermissionError()) if name == gates.GROUPS else None
        # A fresh task is necessary: permission loss stops the old task, as intended.
        with self.assertRaises(PermissionError):
            self.call('scene_bootstrap', day='2026-09-16')

    def test_no_group_permission_never_reports_zero_or_teacher_capability(self):
        self.projection.side_effect = lambda name: (_ for _ in ()).throw(frappe.PermissionError()) if name == gates.GROUPS else None
        result = self.call('scene_bootstrap', day='2026-09-16')
        self.assertFalse(result['groups_available'])
        self.assertIsNone(result['visible_group_count'])
        self.assertEqual(result['supported_tools'], ['scene_bootstrap'])
        self.assertEqual(self.queries, [])

    def test_discovery_omits_navigation_without_native_projection_permissions(self):
        self.projection.side_effect = lambda name: (_ for _ in ()).throw(frappe.PermissionError()) if name == gates.ATTENDANCE else None
        result = self.call('scene_bootstrap', day='2026-09-16')
        self.assertNotIn('classroom_read', result['supported_tools'])
        self.assertIn('class_students_read', result['supported_tools'])

    def test_roster_page_registers_lookahead_before_view_and_result(self):
        result = self.call(group='G1', page_size=2)
        self.assertEqual([r['student'] for r in result['students']], ['S1', 'S2'])
        self.assertEqual(result['page_count'], 2)
        self.assertIsNone(result['visible_class_count'])
        self.assertTrue(result['has_more'])
        for name in ('S1', 'S2', 'S3'):
            self.assertIn(gates._read('Student', name), self.scopes())
        self.assertEqual(len(self.queries), 1)  # No second business read to reconstruct dependencies.
        self.assertTrue(any(e['kind'] == 'view' for e in self.store.events(self.identity)))
        self.assertTrue(result['display_requested'])
        self.assertNotIn('roll_number', str(result))

    def test_roster_next_page_reuses_native_order_without_previous_student_queries(self):
        first = self.call(group='G1', page_size=2)
        self.queries.clear()
        second = self.call(group='G1', cursor=first['next_cursor'], page_size=2)
        self.assertEqual([r['student'] for r in second['students']], ['S3'])
        self.assertEqual(self.queries[0][1]['filters']['name'][1], ['S3'])
        self.assertFalse(second['has_more'])
        self.assertIsNone(second['visible_class_count'])

    def test_complete_empty_roster_is_zero_but_not_unknown_scan(self):
        self.groups['G1'].students = []
        result = self.call()
        self.assertEqual(result['visible_class_count'], 0)
        self.assertFalse(result['has_more'])
        self.assertFalse(result['scan_limited'])

    def test_missing_incomplete_or_wrong_group_source_observer_is_rejected(self):
        def broken(doc, **kwargs):
            kwargs['source_observer'](classroom.RosterPageReadSources('G1', 'a' * 64, ()))
            return {'revision': 'a' * 64, 'rows': [{'student': 'S1', 'student_name': 'MUST NOT DELIVER'}]}
        with patch.object(classroom, '_roster_page', side_effect=broken):
            with self.assertRaises(frappe.PermissionError):
                self.call()
        self.assertFalse(any(e['kind'] == 'view' for e in self.store.events(self.identity)))

    def test_complete_first_page_count_is_visible_class_not_attendance_or_school(self):
        self.visible.remove('S2')
        result = self.call()
        self.assertEqual(result['visible_class_count'], 2)
        self.assertEqual([r['student'] for r in result['students']], ['S1', 'S3'])
        self.assertFalse(result['has_more'])
        self.assertIn('不是历史、出勤、就餐或全园', result['scope'])

    def test_native_full_roster_default_semantics_and_paged_order_are_identical(self):
        self.groups['G1'].students = [
            _dict(student='S3', active=1, group_roll_number=3),
            _dict(student='S1', active=0, group_roll_number=1),
            _dict(student='S1', active=1, group_roll_number=5),
            _dict(student='S1', active=1, group_roll_number=2),
            _dict(student='S2', active=1, group_roll_number=2)]
        self.students['S2'].enabled = 0
        full = self.adapter.run_check(self.owner, lambda: classroom._roster(self.groups['G1']))
        result = self.call()
        self.assertEqual(full, [{'student': 'S1', 'student_name': '合成S1', 'roll_number': 2},
                                {'student': 'S3', 'student_name': '合成S3', 'roll_number': 3}])
        self.assertEqual([r['student'] for r in result['students']], [r['student'] for r in full])

    def test_membership_or_order_changed_invalidates_cursor(self):
        first = self.call(group='G1', page_size=1)
        self.groups['G1'].students[0].group_roll_number = 20
        with self.assertRaisesRegex(ValueError, 'Roster changed'):
            self.call(group='G1', cursor=first['next_cursor'])

    def test_cross_class_cursor_is_not_a_permission_grant(self):
        first = self.call(group='G1', page_size=1)
        with self.assertRaisesRegex(ValueError, 'Roster changed'):
            self.call(group='G2', cursor=first['next_cursor'])
        with self.assertRaises(frappe.PermissionError):
            self.call(group='OTHER')

    def test_lost_lookahead_student_authority_denies_old_history(self):
        self.call(group='G1', page_size=2)
        self.visible.remove('S3')
        with self.assertRaises(PermissionError):
            self.store.events(self.identity)

    def test_lost_class_with_another_class_still_allowed_denies_history(self):
        self.call('scene_bootstrap', day='2026-09-16', page_size=1)
        self.assigned.remove('G1')
        self.assertIn('G2', self.assigned)
        with self.assertRaises(PermissionError):
            self.store.events(self.identity)

    def test_revocation_between_query_and_registration_delivers_no_result_or_view(self):
        self.after_query = lambda: self.assigned.remove('G1')
        with self.assertRaises(frappe.PermissionError):
            self.call()
        self.assertFalse(any(s.get('document') == 'S1' for s in self.scopes()))

    def test_cancelled_task_does_not_query(self):
        self.store.cancel(self.identity)
        with self.assertRaises(frappe.PermissionError):
            self.call()
        self.assertEqual(self.queries, [])

    def test_wrong_claim_owner_site_mode_refused(self):
        for identity in (replace(self.identity, owner='Administrator'), replace(self.identity, site='other'),
                         replace(self.identity, mode='admin_project')):
            with self.assertRaises((PermissionError, frappe.PermissionError)):
                self.reader.dispatch(replace(self.claim, identity=identity), 'class_students_read', {'group': 'G1'})
        self.assertEqual(self.queries, [])

    def test_strict_arguments_reject_identity_sql_path_nonfinite_and_bad_cursor(self):
        for extra in ({'owner': 'Administrator'}, {'sql': 'select 1'}, {'ignore_permissions': True},
                      {'page_size': True}, {'page_size': 51}, {'page_size': float('nan')},
                      {'cursor': '../secret'}, {'cursor': reads._encode_cursor(-1, 'a' * 64)}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.call(group='G1', **extra)
        with self.assertRaises(ValueError):
            self.call('run_sql', sql='select 1')
        with self.assertRaises(ValueError):
            self.call('scene_bootstrap', day='2026-09-16', actor='Administrator')
        self.assertEqual(self.queries, [])

    def test_large_class_pages_stay_bounded_and_scope_exhaustion_is_not_empty(self):
        names = ['P%04d' % i for i in range(400)]
        self.groups['G1'] = self.group('G1', names)
        self.students = {n: _dict(name=n, student_name='合成', enabled=1) for n in names}
        self.visible = set(names)
        cursor = None
        results = []
        for _ in range(12):
            args = {'group': 'G1', 'page_size': 50, **({'cursor': cursor} if cursor else {})}
            result = self.call(**args)
            if not result['available']:
                break
            results.extend(r['student'] for r in result['students'])
            self.assertIsNone(result['visible_class_count'])
            self.assertLessEqual(len(self.scopes()), 256)
            cursor = result['next_cursor']
        self.assertEqual(result['error'], 'scope_budget_exhausted')
        self.assertEqual(result['retry'], 'new_task')
        self.assertNotIn('students', result)
        self.assertLess(len(results), 400)
        self.assertEqual(len(set(results)), len(results))
        self.assertTrue(all(query['limit_page_length'] <= 51 for dt, query in self.queries if dt == 'Student'))

    def test_thousand_class_discovery_never_returns_entire_school_or_total(self):
        self.groups = {'G%04d' % i: self.group('G%04d' % i, []) for i in range(1000)}
        self.assigned = set(self.groups)
        result = self.call('scene_bootstrap', day='2026-09-16', page_size=50)
        self.assertEqual(result['page_count'], 50)
        self.assertIsNone(result['visible_group_count'])
        self.assertTrue(result['has_more'])
        self.assertEqual(self.queries[0][1]['limit_page_length'], 51)
        self.assertEqual(sum(s['kind'] == 'class' for s in self.scopes()), 51)
        self.assertLess(len(self.scopes()), 256)

    def test_scan_limit_continuation_never_leaks_invisible_identifier_or_reports_empty_class(self):
        names = ['HIDDEN%04d' % i for i in range(550)] + ['VISIBLE']
        self.groups['G1'] = self.group('G1', names)
        self.students = {n: _dict(name=n, student_name=n, enabled=1) for n in names}
        self.visible = {'VISIBLE'}
        first = self.call(group='G1', page_size=5)
        self.assertEqual(first['page_count'], 0)
        self.assertIsNone(first['has_more'])
        self.assertIsNone(first['visible_class_count'])
        self.assertTrue(first['scan_limited'])
        self.assertNotIn('HIDDEN', str(first))
        second = self.call(group='G1', cursor=first['next_cursor'], page_size=5)
        self.assertEqual([r['student'] for r in second['students']], ['VISIBLE'])
        self.assertFalse(second['has_more'])
        self.assertIsNone(second['visible_class_count'])

    def test_budget_limit_never_issues_unregistered_business_query(self):
        self.store.register_authorities(self.claim, [{'kind': 'capability', 'name': 'budget:%d' % i} for i in range(256)])
        for tool, args in [('scene_bootstrap', {'day': '2026-09-16'}), ('class_students_read', {'group': 'G1'})]:
            result = self.reader.dispatch(self.claim, tool, args)
            self.assertEqual(result['error'], 'scope_budget_exhausted')
        self.assertEqual(self.queries, [])


if __name__ == '__main__':
    unittest.main()
