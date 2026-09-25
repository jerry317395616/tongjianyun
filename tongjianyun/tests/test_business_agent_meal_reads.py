"""Native same-query meal provenance + authority barriers; no DB/model writes."""
from contextlib import ExitStack
from dataclasses import replace
import inspect
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe import _dict
from tongjianyun import classroom, daily_meals as daily, student_meals as meals
from tongjianyun import business_agent_authority as gates
from tongjianyun.business_agent_tasks import WorkerClaim
from tongjianyun.tests import test_business_agent_authority as authority_fixture
from tongjianyun.tests import test_business_agent_reads as reads_fixture

DAY = '2026-09-16'


class MealDoc(_dict):
    def __init__(self, persisted=False):
        super().__init__(name='CM-test' if persisted else None, student_group='G1', meal_date=DAY,
                         modified='2026-09-16 12:00:00' if persisted else None,
                         status='待确认', students=[], persisted=persisted)

    def is_new(self):
        return not self.persisted

    def append(self, field, row):
        self[field].append(_dict(row))

    def check_permission(self, action):
        if action != 'read':
            raise AssertionError('Meal reader tried a mutation permission')

    def as_dict(self):
        return dict(self)


def pupil(name='S1', state='未确认'):
    return _dict(student=name, student_name='合成学生', attendance_hint='private-estimate',
                 **{meal: state for meal in meals.MEALS},
                 **{meal + '_expected': int(meal != 'dinner') for meal in meals.MEALS})


def estimate_sources(**overrides):
    values = dict(day=DAY, groups=('G1',), students=('S1',),
                  attendance_records=('A1', 'A0'), leave_records=('L1', 'L0'))
    return daily.StudentMealReadSources(**{**values, **overrides})


def new_sources(**overrides):
    values = dict(group='G1', day=DAY, revision='', record=None,
                  students=('S1',), estimates=estimate_sources())
    return meals.ClassMealReadSources(**{**values, **overrides})


def stored_sources(**overrides):
    values = dict(group='G1', day=DAY, revision='2026-09-16 12:00:00', record='CM-test', students=('S1',))
    return meals.ClassMealReadSources(**{**values, **overrides})


class NativeMealSourcesTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.queries = []
        self.db = MagicMock()
        self.db.exists.return_value = False
        self.db.get_value.return_value = '测试班级'
        self.stack.enter_context(patch.object(frappe, 'db', self.db))
        self.stack.enter_context(patch.object(frappe, 'has_permission', return_value=True))
        self.stack.enter_context(patch.object(frappe, 'new_doc', side_effect=lambda dt: MealDoc()))
        self.stack.enter_context(patch.object(frappe, 'get_all', side_effect=self.query))
        self.stack.enter_context(patch.object(meals, 'allowed_groups', return_value=['G1']))
        self.stack.enter_context(patch.object(classroom, '_scope', return_value=_dict(name='G1')))

    def query(self, doctype, **kwargs):
        self.queries.append((doctype, kwargs))
        if doctype == 'Student Group':
            return [_dict(name='G1', student_group_name='测试班级')]
        if doctype == 'Student Group Student':
            return [_dict(student='S1', student_name='', group_roll_number=1),
                    _dict(student='S2', student_name='合成第二人', group_roll_number=2)]
        if doctype == 'Student':
            return ['S1', 'S2'] if kwargs.get('pluck') else [_dict(name='S1', student_name='合成第一人')]
        if doctype == 'Student Attendance':
            return [_dict(name='A1', student='S1', status='Absent', docstatus=1),
                    _dict(name='A0', student='S1', status='Present', docstatus=1)]
        if doctype == 'Student Leave Application':
            return [_dict(name='L1', student='S2', reason='private new reason', docstatus=1),
                    _dict(name='L0', student='S2', reason='private old reason', docstatus=1)]
        raise AssertionError('Unexpected source ' + doctype)

    def test_initial_estimates_capture_all_history_without_requery(self):
        captured = []
        raw = daily._calculate_student_details(DAY, 'G1', source_observer=captured.append)
        self.assertEqual([row['attendance_status'] for row in raw], ['Absent', 'Leave'])
        self.assertEqual(captured, [daily.StudentMealReadSources(DAY, ('G1',), ('S1', 'S2'),
                                                              ('A0', 'A1'), ('L0', 'L1'))])
        self.assertEqual(sum(dt == 'Student Attendance' for dt, _ in self.queries), 1)
        self.assertEqual(sum(dt == 'Student Leave Application' for dt, _ in self.queries), 1)
        self.assertFalse(any(dt == daily.ADJUSTMENT_DOCTYPE for dt, _ in self.queries))
        self.db.commit.assert_not_called()

    def test_default_calculation_is_unchanged(self):
        original = daily.calculate_student_details(DAY, 'G1')
        captured = []
        observed = daily._calculate_student_details(DAY, 'G1', source_observer=captured.append)
        self.assertEqual(original, observed)
        self.assertEqual(observed[1]['leave_reason'], 'private new reason')

    def test_first_classroom_read_keeps_unknown_actual_and_complete_sources(self):
        captured = []
        raw = classroom._get_meals('G1', DAY, source_observer=captured.append)
        self.assertEqual(set(raw), {'record', 'revision', 'expected', 'actual', 'meals'})
        self.assertEqual(raw['revision'], '')
        self.assertTrue(all(facts['actual'] is None for facts in raw['meals'].values()))
        self.assertEqual(captured[0].students, ('S1', 'S2'))
        self.assertIsNone(captured[0].record)
        self.assertEqual(captured[0].estimates.attendance_records, ('A0', 'A1'))
        self.assertEqual(captured[0].estimates.leave_records, ('L0', 'L1'))
        self.assertEqual(captured[0].estimates.adjustment_records, ())
        self.db.commit.assert_not_called()

    def test_existing_snapshot_does_not_rederive_or_replace_original_estimates(self):
        self.db.exists.return_value = True
        doc = MealDoc(persisted=True)
        doc.students = [pupil()]
        doc.students[0].lunch = '已就餐'
        captured = []
        with patch.object(frappe, 'get_doc', return_value=doc), patch.object(meals, '_roster') as roster:
            raw = classroom._get_meals('G1', DAY, source_observer=captured.append)
        roster.assert_not_called()
        self.assertEqual(self.queries, [])
        self.assertEqual(captured, [stored_sources()])
        self.assertEqual(raw['meals']['lunch']['actual'], 1)
        self.assertIsNone(raw['meals']['breakfast']['actual'])

    def test_missing_original_estimate_capture_fails_closed(self):
        with patch.object(meals, '_roster', return_value=[]), self.assertRaises(ValueError):
            meals._load(DAY, 'G1', source_observer=lambda _: None)

    def test_public_signatures_never_accept_observer_or_actor(self):
        for function, expected in ((daily.calculate_student_details, {'meal_date', 'student_group'}),
                                   (meals.get_class_meals, {'meal_date', 'student_group'}),
                                   (classroom.get_meals, {'student_group', 'day', 'workspace'})):
            self.assertEqual(set(inspect.signature(function).parameters), expected)
        for function, args in ((daily._calculate_student_details, (DAY, 'G1')),
                               (meals._get_class_meals, (DAY, 'G1')), (meals._load, (DAY, 'G1')),
                               (classroom._get_meals, ('G1', DAY))):
            with self.subTest(function=function.__name__), self.assertRaises(TypeError):
                function(*args, source_observer={})


class MealAuthorityTests(unittest.TestCase):
    def setUp(self):
        # Reuse the existing fresh actor/DocType/list/field fixture, not its tests.
        authority_fixture.FrappeBusinessAuthorityTests.setUp(self)
        self.visible.update({'CM-test', 'A0', 'L0'})
        self.claim = WorkerClaim(self.identity, 'claim', 'token')
        self.store = MagicMock()
        self.store.binding_state.return_value = {'status': 'running', 'cancel_requested': False}
        self.sources = stored_sources()
        self.raw = {'record': {'name': 'CM-test', 'student_group': 'G1', 'meal_date': DAY,
                    'students': [pupil()], 'private_path': '/private/never-send'},
                    'revision': self.sources.revision, 'meals': meals.meal_facts([pupil()])}
        def read(group, day, *, source_observer):
            self.assertEqual((group, day, self.session.user), ('G1', DAY, self.owner))
            source_observer(self.sources)
            return self.raw
        self.read = self.stack.enter_context(patch.object(classroom, '_get_meals', side_effect=read))

    def call(self):
        return self.adapter.read_meals(self.store, self.claim, group='G1', day=DAY)

    def registered(self):
        return self.store.register_authorities.call_args.args[1]

    def test_saved_snapshot_minimal_projection_and_full_current_scope(self):
        result = self.call()
        self.assertEqual(set(result), {'group', 'day', 'scope', 'revision', 'meals', 'students'})
        self.assertIn(gates._read(meals.DOCTYPE, 'CM-test'), self.registered())
        self.assertIn(gates._read('Student', 'S1'), self.registered())
        self.assertIn(gates._read('Student Group', 'G1'), self.registered())
        self.assertNotIn('private', str(result))
        self.assertNotIn('attendance_hint', str(result))
        self.assertNotIn('record', result)
        self.assertEqual(self.session.user, 'outer-broker')
        self.db.commit.assert_not_called()
        self.read.assert_called_once()

    def test_unsaved_estimate_registers_all_historical_sources(self):
        self.sources = new_sources()
        self.raw['revision'] = ''
        self.call()
        required = self.registered()
        for dt, names in (('Student Attendance', ('A1', 'A0')), ('Student Leave Application', ('L1', 'L0'))):
            for name in names:
                self.assertIn(gates._read(dt, name), required)
        self.assertIn(gates._capability(gates.MEAL_ESTIMATES), required)
        self.assertNotIn(gates._read(meals.DOCTYPE, 'CM-test'), required)

    def test_old_history_revocation_blocks_result_not_just_latest_row(self):
        self.sources = new_sources()
        self.raw['revision'] = ''
        self.visible.remove('L0')
        with self.assertRaises(frappe.PermissionError):
            self.call()
        self.store.register_authorities.assert_not_called()

    def test_snapshot_document_and_student_revocation_block_delivery(self):
        for name in ('CM-test', 'S1'):
            with self.subTest(name=name):
                self.visible.remove(name)
                with self.assertRaises(frappe.PermissionError):
                    self.call()
                self.visible.add(name)

    def test_fresh_estimate_fields_checked_and_no_raw_leave_reason(self):
        self.sources = new_sources()
        self.raw['revision'] = ''
        def permitted(dt, fields, **kwargs):
            if dt == 'Student Leave Application' and 'reason' in fields:
                raise frappe.PermissionError('field denied')
        self.fields.side_effect = permitted
        with self.assertRaises(frappe.PermissionError):
            self.call()
        self.store.register_authorities.assert_not_called()

    def test_stored_meal_does_not_require_unrelated_attendance_source_permission(self):
        def permitted(dt, fields, **kwargs):
            if dt in {'Student Attendance', 'Student Leave Application'}:
                raise frappe.PermissionError('unrelated permission')
        self.fields.side_effect = permitted
        self.assertEqual(self.call()['revision'], self.sources.revision)

    def test_missing_or_mismatched_observer_never_registers_partial_sources(self):
        for source in (replace(self.sources, group='G2'), replace(self.sources, day='2026-09-17'),
                       replace(self.sources, revision='other'), replace(self.sources, students=('S2',)),
                       replace(self.sources, record='another')):
            with self.subTest(source=source):
                self.sources = source
                with self.assertRaises((ValueError, frappe.PermissionError)):
                    self.call()
        self.read.side_effect = lambda *args, **kwargs: self.raw
        with self.assertRaises(frappe.PermissionError):
            self.call()
        self.store.register_authorities.assert_not_called()

    def test_registration_or_final_binding_failure_cannot_deliver(self):
        self.store.register_authorities.side_effect = PermissionError('revoked')
        with self.assertRaises(PermissionError):
            self.call()
        self.store.register_authorities.side_effect = None
        self.store.binding_state.side_effect = [dict(status='running', cancel_requested=False),
                                               dict(status='stopping', cancel_requested=True)]
        with self.assertRaises(frappe.PermissionError):
            self.call()

    def test_source_budget_never_degrades_to_incomplete_meal_roster(self):
        self.sources = stored_sources(students=tuple('S%d' % i for i in range(260)))
        self.raw['record']['students'] = [pupil(name) for name in self.sources.students]
        with self.assertRaises(ValueError):
            self.call()
        self.store.register_authorities.assert_not_called()

    def test_estimate_contract_rejects_unobserved_aggregate_adjustment_claims(self):
        with self.assertRaises(ValueError):
            gates.meal_read_set(new_sources(estimates=estimate_sources(adjustment_records=('AD1',))))
        for source in ({}, new_sources(estimates=None), stored_sources(estimates=estimate_sources()),
                       new_sources(estimates=estimate_sources(students=())),
                       new_sources(estimates=estimate_sources(attendance_records=['A1']))):
            with self.subTest(source=source), self.assertRaises(ValueError):
                gates.meal_read_set(source)

    def test_repeated_student_dependencies_count_once_toward_scope_budget(self):
        names = tuple('S%d' % index for index in range(180))
        read_set = gates.meal_read_set(new_sources(students=names,
            estimates=estimate_sources(students=names, attendance_records=(), leave_records=())))
        self.assertEqual(len(read_set.scopes), 184)

    def test_preexisting_task_scope_limit_is_explicit_and_not_partial(self):
        self.store.required_scopes.return_value = [gates._read('Student', 'prior%d' % i) for i in range(255)]
        with self.assertRaises(gates.MealReadScopeLimit) as raised:
            self.call()
        self.assertFalse(raised.exception.single_read)
        self.store.register_authorities.assert_not_called()


class MealToolDispatchTests(unittest.TestCase):
    def setUp(self):
        reads_fixture.BusinessReadsTests.setUp(self)
        self.raw = {'group': 'G1', 'day': DAY, 'scope': '本班', 'revision': '',
                    'meals': meals.meal_facts([pupil()]), 'students': [pupil()]}
        self.read = self.stack.enter_context(patch.object(self.adapter, 'read_meals', return_value=self.raw))

    # Required by the reusable original fixture, without inheriting its tests.
    group = staticmethod(reads_fixture.BusinessReadsTests.group)
    check_actor = reads_fixture.BusinessReadsTests.check_actor
    scope = reads_fixture.BusinessReadsTests.scope
    check_scope = reads_fixture.BusinessReadsTests.check_scope
    query = reads_fixture.BusinessReadsTests.query

    def call(self, **arguments):
        return self.reader.dispatch(self.claim, 'meal_read', arguments or {'group': 'G1', 'day': DAY})

    def test_meal_read_calls_source_adapter_and_publishes_one_exact_view(self):
        result = self.call()
        self.assertEqual(result, self.raw)
        self.read.assert_called_once_with(self.store, self.claim, group='G1', day=DAY)
        views = [e for e in self.store.events(self.identity) if e['kind'] == 'view']
        self.assertEqual(len(views), 1)
        self.assertEqual(views[0]['selection'], {'view': 'meal_counts', 'group': 'G1', 'day': DAY, 'meal': 'lunch'})

    def test_extra_write_identity_or_meal_parameters_are_rejected(self):
        for extra in ({'confirm': True}, {'owner': self.owner}, {'meal': 'lunch'}, {'students': []}, {'page_size': 1}):
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                self.call(group='G1', day=DAY, **extra)
        self.read.assert_not_called()

    def test_view_uses_the_trusted_task_meal_and_not_model_arguments(self):
        for context in ({'meal': 'breakfast'}, {'selection': {'meal': 'breakfast'}}):
            with self.subTest(context=context), patch.object(self.store, 'task', return_value={'context': context}):
                self.call()
        views = [e for e in self.store.events(self.identity) if e['kind'] == 'view']
        self.assertEqual([event['selection']['meal'] for event in views], ['breakfast', 'breakfast'])

    def test_scope_budget_error_does_not_return_partial_roster_or_emit_view(self):
        for single_read in (True, False):
            self.read.side_effect = gates.MealReadScopeLimit(single_read=single_read)
            result = self.call()
            self.assertFalse(result['available'])
            self.assertEqual(result['error'], 'scope_budget_exhausted')
            self.assertNotIn('students', result)
            self.assertEqual(result['retry'], 'use_business_view' if single_read else 'new_task')
        self.assertFalse(any(e['kind'] == 'view' for e in self.store.events(self.identity)))

    def test_registered_source_failure_never_emits_view(self):
        self.read.side_effect = PermissionError('source revoked')
        with self.assertRaises((PermissionError, frappe.PermissionError)):
            self.call()
        self.assertFalse(any(e['kind'] == 'view' for e in self.store.events(self.identity)))

    def test_task_stop_after_read_prevents_result_and_view(self):
        def cancel(*args, **kwargs):
            self.store.cancel(self.identity)
            return self.raw
        self.read.side_effect = cancel
        with self.assertRaises((PermissionError, frappe.PermissionError)):
            self.call()
        self.assertFalse(any(e['kind'] == 'view' for e in self.store.events(self.identity)))


if __name__ == '__main__':
    unittest.main()
