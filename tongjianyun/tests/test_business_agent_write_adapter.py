"""Pure Context/DB doubles + actual ledger; never connects to any Frappe site.

The three adapter modules are loaded under private test names against a fake
Frappe module, so this suite also runs on machines without Frappe installed.
The original production modules/ambient Frappe local state are not replaced.
"""
from collections import defaultdict
from contextlib import ExitStack
from contextvars import ContextVar
from dataclasses import replace
import importlib.util
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from types import ModuleType, SimpleNamespace
from typing import NamedTuple
import unittest
from unittest.mock import MagicMock, patch
import uuid

import tongjianyun
from tongjianyun.business_agent_tasks import TaskIdentity, WorkerClaim
from tongjianyun.business_agent_writes import BusinessWriteLedger, BusinessWrites


class AttendanceSources(NamedTuple):
    group: str
    day: str
    revision: str
    students: tuple
    attendance_records: tuple
    leave_records: tuple


def load_private(stack, filename, dependencies):
    name = '_business_write_test_' + uuid.uuid4().hex
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / filename)
    module = importlib.util.module_from_spec(spec)
    stack.enter_context(patch.dict(sys.modules, {name: module}))
    with patch.dict(sys.modules, dependencies):
        spec.loader.exec_module(module)
    return module


class NativeWriteAdapterTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.site, self.owner = 'writes-test.localhost', 'teacher@example.invalid'
        self.claim = WorkerClaim(TaskIdentity(self.site, self.owner, str(uuid.uuid4())),
                                 str(uuid.uuid4()), secrets.token_urlsafe(32))
        self.account = {'enabled': 1, 'user_type': 'System User'}
        self.state = {'site': self.site, 'owner': self.owner, 'task_id': self.claim.identity.task_id,
                      'mode': 'business', 'status': 'running', 'cancel_requested': False}
        self.att_args = {'group': 'G1', 'day': '2026-09-16', 'revision': 'a' * 64,
                         'changes': [{'student': 'S1', 'status': 'Present'}]}
        self.meal_args = {'group': 'G1', 'day': '2026-09-16', 'meal': 'lunch', 'revision': '',
                          'confirm': True, 'change_reason': 'actual requested correction',
                          'students': [{'student': 'S1', 'value': '就餐'}]}
        self.outer = SimpleNamespace(site='outer.localhost', session=SimpleNamespace(user='outer-user', sid='outer-sid'),
                                     db=MagicMock(), flags={'outer_flag': True}, request_cache={'private': 'outer'})
        self.local = ContextVar('native-write-test-local', default=None)
        token = self.local.set(self.outer)
        self.addCleanup(self.local.reset, token)
        self.frappe = ModuleType('frappe')
        def missing(name):
            current = self.local.get()
            if name == 'local':
                return current
            if name in {'session', 'db'} and current is not None:
                return getattr(current, name)
            raise AttributeError(name)
        self.frappe.__getattr__ = missing
        # Frappe's real permission exception is NOT the built-in PermissionError.
        # The trusted worker boundary normalizes it for the HTTP tool transport.
        self.frappe.PermissionError = type('BusinessPermissionError', (Exception,), {})
        self.frappe.QueryDeadlockError = type('QueryDeadlockError', (RuntimeError,), {})
        self.frappe.QueryTimeoutError = type('QueryTimeoutError', (RuntimeError,), {})
        self.opened, self.destroyed, self.actors, self.saves, self.read_connections = [], [], [], [], []
        def init(site, *, sites_path):
            self.local.set(SimpleNamespace(site=site, sites_path=sites_path, session=SimpleNamespace(user='Guest'),
                                           flags={}, request_cache=defaultdict(dict), db=None))
        def connect(*, set_admin_as_user):
            self.assertIs(set_admin_as_user, False)
            db = MagicMock()
            db.get_value.side_effect = lambda *a, **kw: dict(self.account)
            db.exists.return_value = self.persisted_meal
            self.local.get().db = db
            self.opened.append(db)
        def destroy():
            current = self.local.get()
            if current and current.db is not None:
                current.db.close()
                self.destroyed.append(current.db)
            self.local.set(None)
        def set_user(owner):
            self.actors.append(owner)
            self.local.get().session.user = owner
        self.frappe.init = MagicMock(side_effect=init)
        self.frappe.connect = MagicMock(side_effect=connect)
        self.frappe.destroy = MagicMock(side_effect=destroy)
        self.frappe.set_user = MagicMock(side_effect=set_user)
        self.frappe.has_permission = MagicMock(return_value=True)
        self.document = MagicMock()
        self.frappe.get_doc = MagicMock(return_value=self.document)
        self.persisted_meal = False
        self.read_allowed, self.task_allowed = True, True
        self.capabilities = {'attendance_write': True, 'meals_write': True}
        self.classroom = ModuleType('tongjianyun.classroom')
        def scope(group):
            if group != 'G1':
                raise self.frappe.PermissionError('not assigned')
            return SimpleNamespace(name=group)
        self.classroom._scope = MagicMock(side_effect=scope)
        self.classroom._day = MagicMock(side_effect=lambda day: day)
        self.classroom._capabilities = MagicMock(side_effect=lambda day: dict(self.capabilities))
        self.classroom.AttendanceReadSources = AttendanceSources
        def save_attendance(*args):
            self.saves.append(('attendance_save', args, self.local.get().db, self.local.get().session.user))
            return {'saved': len(args[2])}
        def save_meal(*args):
            self.saves.append(('meal_save', args, self.local.get().db, self.local.get().session.user))
            return {'saved': True}
        self.classroom.save_attendance = MagicMock(side_effect=save_attendance)
        self.classroom.save_meal = MagicMock(side_effect=save_meal)
        def attendance(group, day, *, source_observer):
            self.read_connections.append(self.local.get().db)
            source_observer(AttendanceSources(group.name, day, 'b' * 64, ('S1',), ('A1', 'A0'), ('L0',)))
            return {'revision': 'b' * 64, 'counts': {'Present': 1},
                    'students': [{'student': 'S1', 'student_name': 'Synthetic', 'status': 'Present', 'source': 'record'}]}
        self.classroom._attendance = MagicMock(side_effect=attendance)
        self.meals = ModuleType('tongjianyun.student_meals')
        self.meals.DOCTYPE = 'Tongjianyun Class Meal Confirmation'
        self.meals._editor = MagicMock(side_effect=scope)
        self.meals.record_name = MagicMock(return_value='CM-test')
        # Force native imports to test doubles without loading native site code.
        self.stack.enter_context(patch.dict(sys.modules, {'frappe': self.frappe,
            'tongjianyun.classroom': self.classroom, 'tongjianyun.student_meals': self.meals}))
        self.stack.enter_context(patch.object(tongjianyun, 'classroom', self.classroom, create=True))
        self.stack.enter_context(patch.object(tongjianyun, 'student_meals', self.meals, create=True))
        self.tools = load_private(self.stack, 'business_agent_tools.py', {'frappe': self.frappe})
        self.authority = load_private(self.stack, 'business_agent_authority.py',
                                      {'frappe': self.frappe, 'tongjianyun.business_agent_tools': self.tools})
        self.module = load_private(self.stack, 'business_agent_write_adapter.py',
            {'frappe': self.frappe, 'tongjianyun.business_agent_tools': self.tools,
             'tongjianyun.business_agent_authority': self.authority})
        self.store = SimpleNamespace(site=self.site)
        def binding_state(claim):
            if not self.task_allowed or claim != self.claim:
                raise self.frappe.PermissionError('task/source revoked')
            return dict(self.state)
        self.store.binding_state = MagicMock(side_effect=binding_state)
        self.registered = []
        self.store.register_authorities = MagicMock(side_effect=lambda claim, scopes: self.registered.extend(scopes))
        self.store.required_scopes = MagicMock(side_effect=lambda identity: tuple(self.registered))
        self.adapter = self.module.FrappeWriteAdapter(self.site, self.temp, store=self.store)
        def check_scope(scope):
            if not self.read_allowed:
                raise self.frappe.PermissionError('read scope revoked')
        self.stack.enter_context(patch.object(self.authority, '_check_scope', side_effect=check_scope))
        self.stack.enter_context(patch.object(self.authority, '_projection'))
        def view_scopes(identity, selection):
            def read():
                self.authority._account(identity.owner, self.site)
                check_scope(selection)
                self.classroom._scope(selection['group'])
                return ({'kind': 'view', 'selection': selection},)
            return self.adapter.authority.run_check(identity.owner, read)
        self.adapter.authority.view_scopes = MagicMock(side_effect=view_scopes)

    def transaction(self, tool='attendance_save', args=None):
        tx = self.adapter.transaction_factory(self.claim, tool, args or (self.att_args if tool == 'attendance_save' else self.meal_args))
        self.addCleanup(tx.close)
        return tx

    def complete(self, tool='attendance_save'):
        tx = self.transaction(tool)
        tx.begin()
        receipt = tx.save()
        tx.commit()
        self.assertTrue(tx.close())
        return tx, receipt

    def ledger(self):
        directory = Path(self.temp) / 'ledger'
        directory.mkdir(mode=0o700, exist_ok=True)
        ledger = BusinessWriteLedger(directory, self.site, authorize=self.adapter.authorize)
        ledger.open_task(self.claim)
        return ledger

    def test_factory_is_detached_pure_and_never_opens_request_db(self):
        tx = self.transaction()
        self.att_args['changes'][0]['status'] = 'Absent'
        self.assertEqual(tx._arguments['changes'][0]['status'], 'Present')
        self.frappe.connect.assert_not_called()
        self.store.binding_state.assert_not_called()
        self.assertIs(self.local.get(), self.outer)

    def test_begin_save_commit_close_keep_actor_cache_connection_isolated(self):
        tx, receipt = self.complete()
        self.assertEqual(receipt, {'saved': 1})
        self.assertEqual(self.saves[0][3], self.owner)
        tx._database.commit.assert_called_once()
        tx._database.rollback.assert_not_called()
        self.assertGreaterEqual(tx._database.close.call_count, 1)
        self.assertNotIn('Administrator', self.actors)
        self.assertIs(self.local.get(), self.outer)
        self.outer.db.commit.assert_not_called()
        self.outer.db.rollback.assert_not_called()
        self.outer.db.close.assert_not_called()
        self.assertEqual(self.outer.request_cache, {'private': 'outer'})
        self.assertEqual(self.outer.session.sid, 'outer-sid')

    def test_account_current_read_is_locked_at_begin_save_and_commit(self):
        tx, _ = self.complete()
        calls = tx._database.get_value.call_args_list
        self.assertEqual(len(calls), 3)
        for call in calls:
            self.assertEqual(call.args, ('User', self.owner, ['enabled', 'user_type']))
            self.assertEqual(call.kwargs, {'as_dict': True, 'for_update': True})

    def test_original_attendance_parameters_not_rewritten_or_approved_again(self):
        args = {**self.att_args, 'changes': [{'student': 'S1', 'status': 'Leave', 'leave_reason': '用户给出的事由'}]}
        tx = self.transaction(args=args)
        tx.begin()
        self.assertEqual(tx.save(), {'saved': 1})
        self.classroom.save_attendance.assert_called_once_with('G1', args['day'], args['changes'], args['revision'])
        tx._database.commit.assert_not_called()
        self.classroom._attendance.assert_not_called()
        self.assertTrue(tx.rollback())

    def test_meal_receipt_preserves_full_roster_revision_confirm_and_reason(self):
        _, receipt = self.complete('meal_save')
        args = self.meal_args
        self.assertEqual(receipt, {'saved': True})
        self.classroom.save_meal.assert_called_once_with('G1', args['day'], 'lunch', args['students'], '', 1, args['change_reason'])
        self.classroom.save_attendance.assert_not_called()
        self.frappe.has_permission.assert_any_call(self.meals.DOCTYPE, 'create', throw=True)

    def test_meal_existing_document_rechecks_current_write_permission(self):
        self.persisted_meal = True
        self.adapter.authorize(self.claim, 'meal_save', self.meal_args)
        self.document.check_permission.assert_called_once_with('write')
        self.document.check_permission.side_effect = self.frappe.PermissionError('revoked')
        with self.assertRaises(self.frappe.PermissionError):
            self.adapter.authorize(self.claim, 'meal_save', self.meal_args)

    def test_arguments_reject_identity_methods_sql_extra_fields_and_nonfinite_json(self):
        for key, value in [('actor', 'Administrator'), ('site', 'other'), ('method', 'db.sql'),
                           ('ignore_permissions', True), ('sql', 'DELETE'), ('value', float('nan'))]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.transaction(args={**self.att_args, key: value})
        for tool in ('run_shell', 'business_view', 'save_meals', None):
            with self.assertRaises(ValueError):
                self.adapter.transaction_factory(self.claim, tool, self.att_args)
        self.frappe.connect.assert_not_called()

    def test_cross_site_mode_guest_and_admin_are_rejected_before_connection(self):
        for changed in ({'site': 'other.localhost'}, {'mode': 'admin_project'}, {'owner': 'Guest'}, {'owner': 'Administrator'}):
            claim = replace(self.claim, identity=replace(self.claim.identity, **changed))
            with self.subTest(changed=changed), self.assertRaises(self.frappe.PermissionError):
                self.adapter.transaction_factory(claim, 'attendance_save', self.att_args)
        self.frappe.connect.assert_not_called()

    def test_disabled_account_at_begin_never_calls_native_save(self):
        tx = self.transaction()
        self.account['enabled'] = 0
        with self.assertRaises(self.frappe.PermissionError):
            tx.begin()
        self.assertTrue(tx.rollback())
        self.classroom.save_attendance.assert_not_called()
        tx._database.commit.assert_not_called()

    def test_cancellation_or_scope_revocation_before_save_rolls_back(self):
        for kind in ('cancel', 'scope'):
            with self.subTest(kind=kind):
                self.state['cancel_requested'], self.read_allowed = False, True
                tx = self.transaction()
                tx.begin()
                if kind == 'cancel':
                    self.state['cancel_requested'] = True
                else:
                    self.read_allowed = False
                with self.assertRaises(self.frappe.PermissionError):
                    tx.save()
                self.assertTrue(tx.rollback())
                tx._database.commit.assert_not_called()
                self.assertTrue(tx.close())
        self.classroom.save_attendance.assert_not_called()

    def test_cross_class_and_day_write_capability_fail_before_original_save(self):
        with self.assertRaises(self.frappe.PermissionError):
            self.adapter.authorize(self.claim, 'attendance_save', {**self.att_args, 'group': 'FOREIGN'})
        for tool in ('attendance_save', 'meal_save'):
            self.capabilities['attendance_write' if tool == 'attendance_save' else 'meals_write'] = False
            with self.assertRaises(self.frappe.PermissionError):
                self.adapter.authorize(self.claim, tool, self.att_args if tool == 'attendance_save' else self.meal_args)
        self.assertEqual(self.saves, [])

    def test_original_revision_date_roster_and_reason_errors_are_not_retried(self):
        for message in ('revision changed', 'day locked', 'full roster required', 'change reason required'):
            with self.subTest(message=message):
                tx = self.transaction('meal_save')
                tx.begin()
                self.classroom.save_meal.side_effect = ValueError(message)
                before = self.classroom.save_meal.call_count
                with self.assertRaisesRegex(ValueError, message):
                    tx.save()
                self.assertEqual(self.classroom.save_meal.call_count, before + 1)
                self.assertTrue(tx.rollback())
                tx._database.commit.assert_not_called()
                self.assertTrue(tx.close())

    def test_source_payload_cannot_escape_as_a_save_receipt(self):
        for receipt in ({'saved': 1, 'students': ['private']}, {'saved': True}, None):
            tx = self.transaction()
            tx.begin()
            self.classroom.save_attendance.side_effect = lambda *args: receipt
            with self.assertRaises(RuntimeError):
                tx.save()
            self.assertTrue(tx.rollback())
            self.assertTrue(tx.close())

    def test_commit_failure_is_uncertain_and_rollback_never_claims_success(self):
        tx = self.transaction()
        tx.begin()
        tx.save()
        tx._database.commit.side_effect = RuntimeError('connection lost after server may commit')
        with self.assertRaises(RuntimeError):
            tx.commit()
        self.assertFalse(tx.rollback())
        tx._database.rollback.assert_not_called()
        self.assertEqual(tx._phase, 'uncertain')
        self.assertTrue(tx.close())
        self.assertEqual(tx._phase, 'uncertain')

    def test_successful_commit_cannot_be_rolled_back_or_saved_twice(self):
        tx = self.transaction()
        tx.begin()
        tx.save()
        with self.assertRaises(RuntimeError):
            tx.save()
        tx.commit()
        self.assertFalse(tx.rollback())
        with self.assertRaises(RuntimeError):
            tx.commit()
        self.assertEqual(len(self.saves), 1)

    def test_close_failure_is_not_drainage_and_readback_stays_blocked(self):
        tx = self.transaction()
        tx.begin()
        tx._database.close.side_effect = RuntimeError('close not confirmed')
        self.assertFalse(tx.close())
        with self.assertRaisesRegex(RuntimeError, 'drain'):
            self.adapter.fresh_read(self.claim, 'attendance_save', self.att_args)
        tx._database.close.side_effect = None
        self.assertTrue(tx.rollback())
        self.assertTrue(tx.close())

    def test_rollback_failure_does_not_invent_success(self):
        tx = self.transaction()
        tx.begin()
        tx._database.rollback.side_effect = RuntimeError('rollback response lost')
        self.assertFalse(tx.rollback())
        self.assertEqual(tx._phase, 'rollback_failed')
        self.assertTrue(tx.close())

    def test_config_guard_failure_never_connects_and_restores_caller(self):
        self.adapter.before_connect = MagicMock(side_effect=ValueError('wrong isolated config'))
        tx = self.transaction()
        with self.assertRaises(ValueError):
            tx.begin()
        self.frappe.connect.assert_not_called()
        self.assertTrue(tx.rollback())
        self.assertTrue(tx.close())
        self.assertIs(self.local.get(), self.outer)

    def test_lost_actor_or_permission_bypass_context_denied_before_save(self):
        for mutation in ('actor', 'flags', 'db'):
            tx = self.transaction()
            tx.begin()
            def tamper():
                if mutation == 'actor':
                    self.local.get().session.user = 'Administrator'
                elif mutation == 'flags':
                    self.local.get().flags['ignore_permissions'] = True
                else:
                    self.local.get().db = MagicMock()
            tx._context.run(tamper)
            with self.assertRaises(self.frappe.PermissionError):
                tx.save()
            self.assertTrue(tx.rollback())
            self.assertTrue(tx.close())
        self.classroom.save_attendance.assert_not_called()

    def test_lifecycle_does_not_jump_to_another_host_thread(self):
        tx = self.transaction()
        tx.begin()
        errors = []
        def other():
            try:
                tx.save()
            except Exception as error:
                errors.append(error)
        thread = threading.Thread(target=other)
        thread.start()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertTrue(tx.rollback())
        self.classroom.save_attendance.assert_not_called()

    def test_fresh_attendance_read_runs_after_close_on_another_connection_and_registers_all_sources(self):
        tx, _ = self.complete()
        result = self.adapter.fresh_read(self.claim, 'attendance_save', self.att_args)
        self.assertEqual(result['revision'], 'b' * 64)
        self.assertEqual(len(self.read_connections), 1)
        self.assertIsNot(self.read_connections[0], tx._database)
        self.assertIn(tx._database, self.destroyed)
        self.assertTrue({'S1', 'A1', 'A0', 'L0'} <= {scope.get('document') for scope in self.registered})
        self.assertEqual(self.saves[0][2], tx._database)
        self.assertEqual(len(self.saves), 1)

    def test_fresh_meal_read_uses_authority_reader_not_transaction_readback(self):
        self.complete('meal_save')
        result = {'group': 'G1', 'day': self.meal_args['day'], 'students': []}
        with patch.object(self.adapter.authority, 'read_meals', return_value=result) as read:
            self.assertIs(self.adapter.fresh_read(self.claim, 'meal_save', self.meal_args), result)
        read.assert_called_once_with(self.store, self.claim, group='G1', day=self.meal_args['day'])

    def test_post_commit_read_denial_cannot_undo_or_repeat_the_write(self):
        tx, _ = self.complete()
        self.read_allowed = False
        with self.assertRaises(self.frappe.PermissionError):
            self.adapter.fresh_read(self.claim, 'attendance_save', self.att_args)
        tx._database.rollback.assert_not_called()
        tx._database.commit.assert_called_once()
        self.assertEqual(len(self.saves), 1)

    def test_real_ledger_combination_commits_closes_then_registers_fresh_readback(self):
        ledger = self.ledger()
        published = MagicMock()
        writes = BusinessWrites(ledger, transaction_factory=self.adapter.transaction_factory,
                                fresh_read=self.adapter.fresh_read, publish_view=published)
        result = writes.dispatch(self.claim, 'attendance_save', self.att_args, 'one')
        self.assertEqual(result['status'], 'committed')
        self.assertTrue(result['readback_available'])
        self.assertFalse(result['host_write_active'])
        self.assertEqual(ledger.observe(self.claim.identity, self.claim.claim_id).active_writes, 0)
        self.assertTrue({'S1', 'A1', 'A0', 'L0'} <= {scope.get('document') for scope in self.registered})
        self.assertIsNot(self.read_connections[0], self.saves[0][2])
        self.assertIn(self.saves[0][2], self.destroyed)
        published.assert_called_once_with(self.claim, {'view': 'classroom_day', 'group': 'G1', 'day': self.att_args['day']})
        replay = writes.dispatch(self.claim, 'attendance_save', self.att_args, 'two')
        self.assertTrue(replay['replayed'])
        self.assertEqual(len(self.saves), 1)
        self.assertEqual(len(self.read_connections), 2)

    def test_ledger_replay_rechecks_write_capability_without_factory(self):
        ledger = self.ledger()
        kwargs = {'transaction_factory': self.adapter.transaction_factory}
        ledger.execute(self.claim, 'one', 'attendance_save', self.att_args, **kwargs)
        self.capabilities['attendance_write'] = False
        for call in ('one', 'different-call'):
            with self.assertRaises(self.frappe.PermissionError):
                ledger.execute(self.claim, call, 'attendance_save', self.att_args, **kwargs)
        self.assertEqual(len(self.saves), 1)

    def test_last_commit_guard_revocation_remains_uncertain_in_real_ledger(self):
        ledger = self.ledger()
        original = ledger._start_commit
        def start_commit(*args):
            original(*args)
            self.capabilities['attendance_write'] = False
        with patch.object(ledger, '_start_commit', side_effect=start_commit):
            outcome = ledger.execute(self.claim, 'one', 'attendance_save', self.att_args,
                                     transaction_factory=self.adapter.transaction_factory)
        self.assertEqual(outcome.status, 'uncertain')
        self.assertFalse(outcome.active)
        db = self.saves[0][2]
        db.commit.assert_not_called()
        db.rollback.assert_called_once()
        self.assertEqual(ledger.observe(self.claim.identity, self.claim.claim_id).uncertain_writes, 1)
        self.capabilities['attendance_write'] = True
        replay = ledger.execute(self.claim, 'two', 'attendance_save', self.att_args,
                                transaction_factory=self.adapter.transaction_factory)
        self.assertEqual(replay.status, 'uncertain')
        self.assertEqual(len(self.saves), 1)


if __name__ == '__main__':
    unittest.main()
