"""Pure, local tests. No Frappe connection, model, root operation or deployment."""
from dataclasses import replace
import json
import multiprocessing
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

from tongjianyun.business_agent_tasks import (
    BusinessTaskStore, ExecutionObservation, QueueObservation, TaskIdentity, WorkerClaim,
)
from tongjianyun.business_agent_writes import (
    BusinessWriteLedger, BusinessWrites, HostWriteObservation, combine_execution,
)


SITE = 'business-writes-test.localhost'


def claim(owner='teacher-one'):
    return WorkerClaim(TaskIdentity(SITE, owner, str(uuid.uuid4())), str(uuid.uuid4()), secrets.token_urlsafe(32))


def attendance(**changes):
    return {'group': 'group-one', 'day': '2026-09-24', 'revision': 'a' * 64,
            'changes': [{'student': 'student-one', 'status': 'Present'}], **changes}


def meal(**changes):
    return {'group': 'group-one', 'day': '2026-09-24', 'revision': '2026-09-24 08:00:00.000000',
            'meal': 'lunch', 'students': [{'student': 'student-one', 'value': '就餐'}],
            'confirm': False, **changes}


def recipe(**changes):
    return {'day': '2026-09-24', 'recipe': None, 'revision': '', 'payload': {
        'recipe': {'title': 'Synthetic weekly recipe', 'weekStart': '2026-09-21', 'weekEnd': '2026-09-25'},
        'days': [{'date': '2026-09-21', 'portions': [{'slot': 'lunch', 'dishes': ['rice'],
            'dishIngredientRows': [{'dishName': 'rice', 'ingredient': 'rice', 'amount': 25, 'unit': 'g'}]}]}]}, **changes}


class Transaction:
    def __init__(self, *, hook=None, failure=None, rollback=True, close=True):
        self.events, self.hook, self.failure = [], hook, failure
        self.rollback_result, self.close_result = rollback, close

    def step(self, name):
        self.events.append(name)
        if self.hook:
            self.hook(name)
        if self.failure == name:
            raise RuntimeError('Simulated native failure; no private data in outcome')

    def begin(self): self.step('begin')
    def save(self): self.step('save')
    def commit(self): self.step('commit')

    def rollback(self):
        self.step('rollback')
        return self.rollback_result

    def close(self):
        self.step('close')
        return self.close_result


def _process_write(directory, current, call_id, entered, release, results, crash_after_commit=False):
    """Independent host process; only a temporary ledger and fake transaction."""
    ledger = BusinessWriteLedger(Path(directory), SITE, authorize=lambda *_: True)
    def hook(name):
        if name == 'save':
            entered.set()
            if not release.wait(10):
                raise RuntimeError('Test coordination failed')
        if name == 'close' and crash_after_commit:
            os._exit(17)  # Demonstrate real process loss, not a mocked timeout.
    transaction = Transaction(hook=hook)
    outcome = ledger.execute(current, call_id, 'attendance_save', attendance(),
                             transaction_factory=lambda *_: transaction)
    results.put((call_id, outcome.status, transaction.events))


class LedgerFixture:
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name).resolve()
        if os.name == 'posix':
            self.directory.chmod(0o700)
        self.authorized, self.checked = True, []
        self.ledger = self.new_ledger()
        self.claim = claim()
        self.ledger.open_task(self.claim)
        self.tx = Transaction()
        self.factories = 0

    def tearDown(self):
        self.temp.cleanup()

    def authorize(self, current, tool, arguments):
        self.checked.append((current.identity, tool, arguments))
        return self.authorized

    def new_ledger(self):
        return BusinessWriteLedger(self.directory, SITE, authorize=self.authorize)

    def factory(self, current, tool, arguments):
        self.factories += 1
        return self.tx

    def execute(self, *, current=None, call='call-one', tool='attendance_save', args=None, ledger=None, factory=None):
        return (ledger or self.ledger).execute(current or self.claim, call, tool,
                                               attendance() if args is None else args,
                                               transaction_factory=factory or self.factory)

    def observe(self, current=None, ledger=None):
        current = current or self.claim
        return (ledger or self.ledger).observe(current.identity, current.claim_id)


class WriteLedgerTests(LedgerFixture, unittest.TestCase):
    def test_commit_is_acknowledged_and_connection_closed_before_receipt(self):
        outcome = self.execute()
        self.assertEqual(outcome.status, 'committed')
        self.assertFalse(outcome.active)
        self.assertEqual(self.tx.events, ['begin', 'save', 'commit', 'close'])
        self.assertEqual(self.observe().active_writes, 0)
        self.assertFalse(self.observe().admission_closed)
        self.assertEqual(self.observe().operations, 1)

    def test_active_is_durable_before_factory_begin_save_and_commit(self):
        observed = []
        def factory(*_):
            observed.append(self.observe(ledger=self.new_ledger()).active_writes)
            self.tx.hook = lambda _: observed.append(self.observe(ledger=self.new_ledger()).active_writes)
            return self.tx
        self.execute(factory=factory)
        self.assertEqual(observed, [1, 1, 1, 1, 1])

    def test_same_and_new_call_ids_replay_without_transaction(self):
        first = self.execute()
        for call_id in ('call-one', 'call-two'):
            again = self.execute(call=call_id)
            self.assertEqual(again.operation_id, first.operation_id)
            self.assertTrue(again.replayed)
        self.assertEqual(self.factories, 1)
        self.assertEqual(self.observe().operations, 1)

    def test_a_call_id_cannot_change_payload(self):
        self.execute()
        with self.assertRaises(ValueError):
            self.execute(args=attendance(revision='b' * 64))
        self.assertEqual(self.factories, 1)

    def test_new_task_and_other_authorized_owner_replay_site_receipt(self):
        first = self.execute()
        other = claim('teacher-two')
        ledger = self.new_ledger()
        ledger.open_task(other)
        again = self.execute(current=other, ledger=ledger)
        self.assertEqual((again.status, again.operation_id, again.replayed), ('committed', first.operation_id, True))
        self.assertEqual(self.factories, 1)

    def test_replay_revalidates_target_authority(self):
        self.execute()
        self.authorized = False
        with self.assertRaises(PermissionError):
            self.execute(call='call-two')
        self.assertEqual(self.factories, 1)

    def test_row_order_and_absent_empty_reason_are_same_operation(self):
        rows = [{'student': 'student-two', 'status': 'Present'}, {'student': 'student-one', 'status': 'Absent'}]
        first = self.execute(args=attendance(changes=rows))
        for row in rows:
            row['leave_reason'] = ''
        again = self.execute(call='new-call', args=attendance(changes=list(reversed(rows))))
        self.assertEqual(first.operation_id, again.operation_id)
        self.assertEqual(self.factories, 1)

    def test_fresh_revision_after_known_commit_is_a_new_write(self):
        first = self.execute()
        second = self.execute(call='new-call', args=attendance(revision='b' * 64))
        self.assertNotEqual(first.operation_id, second.operation_id)
        self.assertEqual(self.factories, 2)

    def test_precommit_validation_failure_with_proven_rollback_releases_resource(self):
        self.tx.failure = 'save'
        first = self.execute()
        self.assertEqual(first.status, 'rolled_back')
        self.assertEqual(self.observe().uncertain_writes, 0)
        self.tx = Transaction()
        other = claim()
        self.ledger.open_task(other)
        fixed = self.execute(current=other, args=attendance(changes=[{'student': 'student-one', 'status': 'Absent'}]))
        self.assertEqual(fixed.status, 'committed')
        self.assertEqual(self.factories, 2)
        old = self.execute(call='old-again')
        self.assertEqual(old.status, 'rolled_back')
        self.assertTrue(old.replayed)
        self.assertEqual(self.factories, 2)

    def test_unproven_rollback_is_uncertain_not_a_release(self):
        self.tx.failure, self.tx.rollback_result = 'save', None
        outcome = self.execute()
        self.assertEqual(outcome.status, 'uncertain')
        self.assertEqual(self.observe().active_writes, 0)
        self.assertEqual(self.observe().uncertain_writes, 1)
        self.assertEqual(self.execute(call='different', args=attendance(revision='b' * 64)).status, 'blocked')

    def test_commit_error_remains_uncertain_even_if_rollback_returns_true(self):
        self.tx.failure = 'commit'
        outcome = self.execute()
        self.assertEqual(outcome.status, 'uncertain')
        self.assertEqual(self.tx.events, ['begin', 'save', 'commit', 'rollback', 'close'])
        other = claim('teacher-two')
        ledger = self.new_ledger()
        ledger.open_task(other)
        self.assertEqual(self.execute(current=other, ledger=ledger, args=attendance(revision='b' * 64)).status, 'blocked')
        self.assertEqual(self.factories, 1)

    def test_uncertain_old_task_blocks_meals_other_classes_and_new_revisions_on_same_day(self):
        self.tx.failure = 'commit'
        self.execute()
        self.tx = Transaction()
        for number, args in enumerate((meal(), meal(meal='dinner'), meal(group='group-two', revision='new'))):
            outcome = self.execute(call='meal-' + str(number), tool='meal_save', args=args)
            self.assertEqual((outcome.status, outcome.operation_id), ('blocked', None))
        next_day = self.execute(call='next-day', tool='meal_save', args=meal(day='2026-09-25'))
        self.assertEqual(next_day.status, 'committed')

    def test_blocked_call_is_consumed_and_does_not_spring_to_life(self):
        entered, release, results = threading.Event(), threading.Event(), []
        def hook(name):
            if name == 'save':
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('Test synchronization failed')
        self.tx.hook = hook
        thread = threading.Thread(target=lambda: results.append(self.execute()))
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            other = claim()
            ledger = self.new_ledger()
            ledger.open_task(other)
            blocked = self.execute(current=other, ledger=ledger, args=attendance(revision='b' * 64))
            self.assertEqual(blocked.status, 'blocked')
        finally:
            release.set()
            thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0].status, 'committed')
        self.assertEqual(self.execute(current=other, ledger=ledger, args=attendance(revision='b' * 64)).status, 'blocked')

    def test_concurrent_separate_ledger_instances_execute_one_transaction(self):
        entered, release, results = threading.Event(), threading.Event(), []
        def hook(name):
            if name == 'save':
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('Test synchronization failed')
        self.tx.hook = hook
        first = threading.Thread(target=lambda: results.append(self.execute()))
        first.start()
        try:
            self.assertTrue(entered.wait(5))
            other = self.new_ledger()
            replay = self.execute(call='concurrent-call', ledger=other)
            self.assertEqual((replay.status, replay.active, replay.replayed), ('in_progress', True, True))
            self.assertEqual(self.factories, 1)
        finally:
            release.set()
            first.join(5)
        self.assertFalse(first.is_alive())
        self.assertEqual(results[0].status, 'committed')

    def test_two_real_host_processes_do_not_repeat_the_same_write(self):
        context = multiprocessing.get_context('spawn')
        entered, second_entered, release = context.Event(), context.Event(), context.Event()
        results = context.Queue()
        first = context.Process(target=_process_write, args=(str(self.directory), self.claim,
                                'process-one', entered, release, results))
        second = context.Process(target=_process_write, args=(str(self.directory), self.claim,
                                 'process-two', second_entered, release, results))
        try:
            first.start()
            self.assertTrue(entered.wait(8))
            second.start()
            second.join(8)
            self.assertEqual(second.exitcode, 0)
            self.assertFalse(second_entered.is_set())
            self.assertEqual(results.get(timeout=3), ('process-two', 'in_progress', []))
        finally:
            release.set()
            for process in (first, second):
                if process.pid is not None:
                    process.join(8)
                    if process.is_alive():
                        process.terminate()
                        process.join(3)
            results.close()
            results.join_thread()
        self.assertEqual(first.exitcode, 0)
        self.assertEqual(self.observe(ledger=self.new_ledger()).active_writes, 0)

    def test_real_process_loss_after_commit_never_clears_active_or_replays(self):
        context = multiprocessing.get_context('spawn')
        entered, release, results = context.Event(), context.Event(), context.Queue()
        release.set()
        process = context.Process(target=_process_write, args=(str(self.directory), self.claim,
                                  'crashing-process', entered, release, results, True))
        try:
            process.start()
            process.join(8)
            self.assertEqual(process.exitcode, 17)
            other = self.new_ledger()
            self.assertEqual(self.observe(ledger=other).active_writes, 1)
            self.assertEqual(self.execute(call='after-crash', ledger=other).status, 'in_progress')
            self.assertEqual(self.factories, 0)
        finally:
            if process.is_alive():
                process.terminate()
                process.join(3)
            results.close()
            results.join_thread()

    def test_cancel_before_save_rolls_back_and_late_admission_is_refused(self):
        self.tx.hook = lambda name: self.ledger.close_task(self.claim.identity, self.claim.claim_id) if name == 'begin' else None
        outcome = self.execute()
        self.assertEqual(outcome.status, 'rolled_back')
        self.assertNotIn('save', self.tx.events)
        with self.assertRaises(PermissionError):
            self.execute(call='late-call')

    def test_cancel_after_native_save_prevents_commit_and_drains_before_zero(self):
        observed = []
        def hook(name):
            if name == 'save':
                observed.append(self.ledger.close_task(self.claim.identity, self.claim.claim_id).active_writes)
        self.tx.hook = hook
        outcome = self.execute()
        self.assertEqual(observed, [1])
        self.assertEqual(outcome.status, 'rolled_back')
        self.assertNotIn('commit', self.tx.events)
        self.assertEqual(self.observe().active_writes, 0)

    def test_cancel_once_commit_has_started_cannot_pretend_rollback(self):
        self.tx.hook = lambda name: self.ledger.close_task(self.claim.identity, self.claim.claim_id) if name == 'commit' else None
        outcome = self.execute()
        self.assertEqual(outcome.status, 'committed')
        self.assertTrue(self.observe().admission_closed)
        self.assertEqual(self.observe().active_writes, 0)

    def test_closed_gate_stays_closed_across_restart(self):
        self.ledger.close_task(self.claim.identity, self.claim.claim_id)
        other = self.new_ledger()
        with self.assertRaises(PermissionError):
            other.open_task(self.claim)
        with self.assertRaises(PermissionError):
            self.execute(ledger=other)

    def test_close_before_open_persists_tombstone_for_late_worker(self):
        future = claim()
        self.ledger.close_task(future.identity, future.claim_id)
        with self.assertRaises(PermissionError):
            self.new_ledger().open_task(future)
        observation = self.observe(future)
        self.assertTrue(observation.registered and observation.admission_closed)
        self.assertEqual(observation.operations, 0)

    def test_identity_claim_and_token_mismatch_never_operate(self):
        for forged in (replace(self.claim, token=secrets.token_urlsafe(32)),
                       replace(self.claim, claim_id=str(uuid.uuid4())),
                       replace(self.claim, identity=replace(self.claim.identity, owner='teacher-two')),
                       replace(self.claim, identity=replace(self.claim.identity, site='wrong.localhost'))):
            with self.subTest(forged=forged.identity):
                with self.assertRaises(PermissionError):
                    self.execute(current=forged)
        self.assertEqual(self.factories, 0)

    def test_account_revoked_after_save_rolls_back(self):
        def hook(name):
            if name == 'save': self.authorized = False
        self.tx.hook = hook
        outcome = self.execute()
        self.assertEqual(outcome.status, 'rolled_back')
        self.assertNotIn('commit', self.tx.events)

    def test_close_requires_literal_success_and_does_not_guess_thread_drain(self):
        for value in (None, False, 1):
            with self.subTest(value=value):
                self.tx.close_result = value
                outcome = self.execute(call='close-' + str(value), args=attendance(day='2026-09-' + ('24' if value is None else '25' if value is False else '26')))
                self.assertEqual(outcome.status, 'committed')
                self.assertTrue(outcome.active)
        self.assertEqual(self.observe().active_writes, 3)

    def test_construction_only_factory_failure_is_proven_no_start_and_releases_fence(self):
        calls = []
        def fail(*_):
            calls.append('construct')
            raise RuntimeError('Pure construction failed before any begin')
        outcome = self.execute(factory=fail)
        self.assertEqual((outcome.status, outcome.active), ('rolled_back', False))
        self.assertEqual(self.observe(ledger=self.new_ledger()).active_writes, 0)
        self.assertEqual(self.observe().uncertain_writes, 0)
        replay = self.execute(call='do-not-automatically-retry', factory=fail)
        self.assertEqual((replay.status, replay.replayed), ('rolled_back', True))
        self.assertEqual(calls, ['construct'])
        self.assertEqual(self.execute(call='corrected-request', args=attendance(revision='b' * 64)).status, 'committed')

    def test_invalid_constructed_adapter_before_begin_is_also_no_start(self):
        outcome = self.execute(factory=lambda *_: None)
        self.assertEqual((outcome.status, outcome.active), ('rolled_back', False))
        self.assertEqual(self.observe().uncertain_writes, 0)

    def test_begin_failure_without_rollback_or_close_proof_keeps_uncertain_active(self):
        self.tx.failure, self.tx.rollback_result, self.tx.close_result = 'begin', False, False
        outcome = self.execute()
        self.assertEqual((outcome.status, outcome.active), ('uncertain', True))
        self.assertEqual(self.tx.events, ['begin', 'rollback', 'close'])
        self.assertEqual(self.observe(ledger=self.new_ledger()).active_writes, 1)

    def test_construction_interrupt_is_recorded_no_start_then_propagated(self):
        def interrupted(*_): raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt): self.execute(factory=interrupted)
        self.assertEqual(self.observe().active_writes, 0)
        self.assertEqual(self.execute(call='repeat-construction-interrupt').status, 'rolled_back')

    def test_receipt_failure_after_commit_preserves_active_and_fence_across_restart(self):
        with patch.object(self.ledger, '_settle', side_effect=OSError('receipt disk unavailable')):
            with self.assertRaises(OSError): self.execute()
        other = self.new_ledger()
        self.assertEqual(self.observe(ledger=other).active_writes, 1)
        replay = self.execute(call='repeat', ledger=other)
        self.assertEqual((replay.status, replay.active), ('in_progress', True))
        self.assertEqual(self.factories, 1)
        self.assertEqual(self.execute(call='new-revision', ledger=other, args=attendance(revision='b' * 64)).status, 'blocked')

    def test_keyboard_interrupt_is_recorded_then_propagated(self):
        def hook(name):
            if name == 'save': raise KeyboardInterrupt()
        self.tx.hook = hook
        with self.assertRaises(KeyboardInterrupt): self.execute()
        self.assertEqual(self.observe().active_writes, 0)
        self.assertEqual(self.execute(call='again').status, 'rolled_back')

    def test_no_names_or_arguments_or_tokens_are_stored(self):
        self.execute(args=attendance(changes=[{'student': 'private-pupil-identifier', 'status': 'Leave',
                                              'leave_reason': 'private-medical-reason'}]))
        raw = self.ledger.path.read_bytes()
        for secret in (b'private-pupil-identifier', b'private-medical-reason', self.claim.token.encode()):
            self.assertNotIn(secret, raw)

    def test_site_cannot_open_another_sites_ledger(self):
        with self.assertRaises(PermissionError):
            BusinessWriteLedger(self.directory, 'other.localhost', authorize=self.authorize)

    def test_replaced_ledger_is_not_silently_accepted(self):
        moved = self.directory / 'saved.sqlite3'
        self.ledger.path.rename(moved)
        self.ledger.path.touch(mode=0o600)
        with self.assertRaises(ValueError): self.observe()

    def test_hardlinked_sqlite_sidecars_are_rejected_before_open(self):
        original = self.directory / 'unrelated-file'
        original.touch(mode=0o600)
        for suffix in ('-journal', '-wal', '-shm'):
            sidecar = Path(str(self.ledger.path) + suffix)
            os.link(original, sidecar)
            try:
                with patch('tongjianyun.business_agent_writes.sqlite3.connect') as connect:
                    with self.assertRaises(ValueError): self.observe()
                    connect.assert_not_called()
            finally:
                sidecar.unlink()

    @unittest.skipUnless(os.name == 'posix', 'Unix mode and symbolic-link check')
    def test_public_or_symlink_journal_is_rejected_before_open(self):
        sidecar = Path(str(self.ledger.path) + '-journal')
        sidecar.touch(mode=0o644)
        # The QA runtime intentionally uses umask 077. touch(mode=0644) alone
        # would therefore create 0600 and fail to exercise the unsafe mode.
        sidecar.chmod(0o644)
        try:
            self.assertEqual(stat.S_IMODE(sidecar.lstat().st_mode), 0o644)
            with patch('tongjianyun.business_agent_writes.sqlite3.connect') as connect:
                with self.assertRaises(ValueError): self.observe()
                connect.assert_not_called()
        finally:
            sidecar.unlink()
        for target in (self.ledger.path, self.directory / 'nonexistent-journal-target'):
            sidecar.symlink_to(target)
            try:
                self.assertTrue(sidecar.is_symlink())
                with patch('tongjianyun.business_agent_writes.sqlite3.connect') as connect:
                    with self.assertRaises(ValueError): self.observe()
                    connect.assert_not_called()
            finally:
                sidecar.unlink()

    def test_unexpected_fields_bad_revisions_and_nonfinite_values_are_rejected_before_factory(self):
        malformed = [attendance(owner='Administrator'), attendance(revision=''), attendance(day='20260924'),
                     attendance(changes=[]), attendance(changes=[{'student': 'x', 'status': []}]),
                     attendance(changes=[{'student': 'x', 'status': 'Leave'}]),
                     attendance(changes=[{'student': 'x', 'status': 'Present', 'weight': float('nan')}])]
        for args in malformed:
            with self.subTest(args=args):
                with self.assertRaises(ValueError): self.execute(args=args)
        for args in (meal(confirm=1), meal(meal=[]), meal(students=[{'student': 'x', 'value': []}])):
            with self.assertRaises(ValueError): self.execute(tool='meal_save', args=args)
        self.assertEqual(self.factories, 0)


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.claim = claim()
        self.native = ExecutionObservation(self.claim.claim_id, 'exited', 0, 0, True, True)
        self.host = HostWriteObservation(self.claim.identity, self.claim.claim_id, True, True, 0, 0, 0)

    def test_closed_and_drained_host_preserves_native_success(self):
        self.assertEqual(combine_execution(self.native, self.host), self.native)

    def test_missing_or_open_admission_is_not_terminal_evidence(self):
        for host in (replace(self.host, registered=False, admission_closed=False), replace(self.host, admission_closed=False)):
            result = combine_execution(self.native, host)
            self.assertEqual(result.state, 'unknown')
            self.assertFalse(result.turn_completed)

    def test_active_host_write_blocks_native_exit_even_with_closed_lease(self):
        result = combine_execution(self.native, replace(self.host, active_writes=1, operations=1))
        self.assertEqual(result.active_writes, 1)
        self.assertEqual(result.state, 'exited')

    def test_uncertain_but_drained_can_fail_or_cancel_never_complete(self):
        result = combine_execution(self.native, replace(self.host, uncertain_writes=1, operations=1))
        self.assertEqual((result.state, result.active_writes, result.turn_completed), ('exited', 0, False))

    def test_native_unknown_and_live_lease_cannot_be_promoted_by_host(self):
        native = replace(self.native, state='unknown', exit_code=None, turn_completed=False, lease_closed=False)
        self.assertEqual(combine_execution(native, self.host), native)

    def test_no_start_seal_requires_empty_permanently_closed_host_gate(self):
        sealed = ExecutionObservation(self.claim.claim_id, 'never_started_and_sealed', 0, None, False, True)
        self.assertEqual(combine_execution(sealed, self.host), sealed)
        result = combine_execution(sealed, replace(self.host, operations=1))
        self.assertEqual(result.state, 'unknown')

    def test_wrong_claim_and_malformed_counts_are_rejected(self):
        for host in (replace(self.host, claim_id=str(uuid.uuid4())), replace(self.host, active_writes=-1),
                     replace(self.host, active_writes=True), replace(self.host, uncertain_writes=1),
                     replace(self.host, registered=False)):
            with self.assertRaises(ValueError): combine_execution(self.native, host)


class TaskTerminalTests(LedgerFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.native_state = 'exited'
        self.store = self.new_store()
        identity = self.store.create('teacher-real-core', str(uuid.uuid4()), '登记本班学生已到园')['identity']
        ticket = self.store.take_dispatch(identity)
        self.store.acknowledge_dispatch(ticket)
        self.claim = self.store.claim(identity, ticket.job_id)
        self.ledger.open_task(self.claim)
        self.store.emit(self.claim, {'kind': 'message', 'item_id': 'answer', 'text': '已返回处理结果。'})

    def new_store(self):
        def native(identity, claim_id):
            return ExecutionObservation(claim_id, self.native_state, 0, 0, True, True)
        return BusinessTaskStore(self.directory, SITE, authorize=lambda *_: True,
            observe_execution=self.new_ledger().observer(native),
            observe_queue=lambda job: QueueObservation(job, 'unknown'))

    def test_open_host_admission_blocks_finish_even_after_known_commit(self):
        self.execute()
        self.assertEqual(self.store.finish(self.claim), 'running')
        self.ledger.close_task(self.claim.identity, self.claim.claim_id)
        self.assertEqual(self.store.finish(self.claim), 'completed')

    def test_unknown_host_connection_blocks_finish_and_fresh_web_reconcile_after_cancel(self):
        self.tx.close_result = False
        self.execute()
        self.ledger.close_task(self.claim.identity, self.claim.claim_id)
        self.assertEqual(self.store.finish(self.claim), 'running')
        self.store.cancel(self.claim.identity)
        self.assertEqual(self.store.finish(self.claim), 'stopping')
        fresh = self.new_store()
        fresh.reconcile(self.claim.identity)
        self.assertEqual(fresh.task(self.claim.identity)['status'], 'stopping')

    def test_drained_uncertain_write_finishes_failed_not_completed(self):
        self.tx.failure = 'commit'
        self.execute()
        self.ledger.close_task(self.claim.identity, self.claim.claim_id)
        self.assertEqual(self.store.finish(self.claim), 'failed')
        self.assertEqual(self.observe().uncertain_writes, 1)

    def test_cancelled_uncertain_write_can_end_cancelled_but_resource_remains_fenced(self):
        self.tx.failure = 'commit'
        self.execute()
        self.store.cancel(self.claim.identity)
        self.ledger.close_task(self.claim.identity, self.claim.claim_id)
        self.assertEqual(self.store.finish(self.claim), 'cancelled')
        next_claim = claim('another-authorized-teacher')
        other = self.new_ledger()
        other.open_task(next_claim)
        self.assertEqual(self.execute(current=next_claim, ledger=other, args=attendance(revision='b' * 64)).status, 'blocked')

    def test_fresh_web_reconcile_sees_persistent_closed_drained_write_state(self):
        self.execute()
        self.ledger.close_task(self.claim.identity, self.claim.claim_id)
        # Recovery is allowed to fail/cancel, never fabricate a successful turn.
        fresh = self.new_store()
        fresh.reconcile(self.claim.identity)
        self.assertEqual(fresh.task(self.claim.identity)['status'], 'failed')


class BusinessWritesTests(LedgerFixture, unittest.TestCase):
    def adapter(self, read=None, publish=None):
        def default_read(current, tool, arguments):
            self.assertEqual(self.tx.events[-1], 'close')
            return {'group': arguments['group'], 'day': arguments['day'], 'revision': 'new', 'students': ['current-only']}
        return BusinessWrites(self.ledger, transaction_factory=self.factory, fresh_read=read or default_read,
                              publish_view=publish or (lambda *_: None))

    def test_adapter_reads_after_closed_commit_and_publishes_selection_only(self):
        views = []
        result = self.adapter(publish=lambda current, view: views.append(view)).dispatch(
            self.claim, 'attendance_save', attendance(), 'call-one')
        self.assertEqual(result['status'], 'committed')
        self.assertTrue(result['readback_available'])
        self.assertEqual(views, [{'view': 'classroom_day', 'group': 'group-one', 'day': '2026-09-24'}])

    def test_adapter_replay_uses_current_read_not_persisted_snapshot(self):
        snapshots = iter(('first-visible', 'now-visible'))
        def read(current, tool, arguments):
            return {'group': arguments['group'], 'day': arguments['day'], 'students': [next(snapshots)]}
        adapter = self.adapter(read=read)
        first = adapter.dispatch(self.claim, 'attendance_save', attendance(), 'call-one')
        again = adapter.dispatch(self.claim, 'attendance_save', attendance(), 'call-two')
        self.assertEqual(first['readback']['students'], ['first-visible'])
        self.assertEqual(again['readback']['students'], ['now-visible'])
        self.assertEqual(self.factories, 1)

    def test_adapter_read_failure_does_not_claim_rollback_or_retry(self):
        def fail(*_): raise RuntimeError('read unavailable')
        result = self.adapter(read=fail).dispatch(self.claim, 'attendance_save', attendance(), 'call-one')
        self.assertTrue(result['committed'])
        self.assertFalse(result['readback_available'])
        self.assertFalse(result['retry_allowed'])
        self.assertNotIn('readback', result)

    def test_adapter_revoked_after_read_never_publishes_or_returns_names(self):
        views = []
        def read(current, tool, arguments):
            self.authorized = False
            return {'group': arguments['group'], 'day': arguments['day'], 'students': ['private']}
        with self.assertRaises(PermissionError):
            self.adapter(read=read, publish=lambda *args: views.append(args)).dispatch(
                self.claim, 'attendance_save', attendance(), 'call-one')
        self.assertEqual(views, [])

    def test_adapter_uncertain_or_active_does_not_read_or_publish(self):
        self.tx.failure = 'commit'
        def forbidden(*_): raise AssertionError('No fresh read/view until a drained known commit')
        result = self.adapter(read=forbidden, publish=forbidden).dispatch(
            self.claim, 'attendance_save', attendance(), 'call-one')
        self.assertIsNone(result['committed'])
        self.assertFalse(result['readback_available'])

    def test_meal_business_confirmation_is_not_an_approval_roundtrip(self):
        views = []
        result = self.adapter(publish=lambda current, view: views.append(view)).dispatch(
            self.claim, 'meal_save', meal(confirm=True), 'meal-confirm')
        self.assertTrue(result['committed'])
        self.assertEqual(views[0]['meal'], 'lunch')
        self.assertEqual(self.factories, 1)


class RecipeLedgerFixture(LedgerFixture):
    def setUp(self):
        super().setUp()
        self.recipe_calls = []

    def recipe_factory(self, current, tool, arguments, *, operation_id):
        with self.ledger._connect() as db:
            persisted = db.execute('SELECT state, active FROM operations WHERE operation_id=?', (operation_id,)).fetchone()
        self.assertEqual(persisted, ('reserved', 1))
        self.assertEqual(str(uuid.UUID(operation_id)), operation_id)
        self.recipe_calls.append((current, tool, arguments, operation_id))
        self.factories += 1
        return self.tx

    def execute_recipe(self, *, args=None, **options):
        return self.execute(tool='recipe_save', args=recipe() if args is None else args,
                            factory=options.pop('factory', self.recipe_factory), **options)


class RecipeWriteLedgerTests(RecipeLedgerFixture, unittest.TestCase):
    def test_recipe_gets_reserved_operation_not_task_claim_or_call(self):
        arguments = recipe()
        original = json.loads(json.dumps(arguments))
        saved = self.execute_recipe(args=arguments, call=self.claim.identity.task_id)
        self.assertEqual(saved.status, 'committed')
        current, tool, normalized, operation_id = self.recipe_calls[0]
        self.assertEqual(current, self.claim)
        self.assertEqual(tool, 'recipe_save')
        self.assertEqual(operation_id, saved.operation_id)
        self.assertNotIn(operation_id, (self.claim.identity.task_id, self.claim.claim_id))
        self.assertEqual(normalized['payload']['days'][0]['day'], '')
        self.assertIs(type(normalized['payload']['days'][0]['portions'][0]['dishIngredientRows'][0]['amount']), float)
        self.assertEqual(arguments, original)

    def test_forged_operation_ids_and_nonfinite_recipe_schema_never_reserve(self):
        invalid = [recipe(operation_id=str(uuid.uuid4())), recipe(task_id=self.claim.identity.task_id),
                   recipe(group='unrequested'), recipe(revision='not-empty-for-create')]
        for field, value in (('recipeId', 'injected'), ('workflowStatus', '已发布')):
            item = recipe()
            item['payload']['recipe'][field] = value
            invalid.append(item)
        for amount in (True, float('nan'), float('inf'), -1):
            item = recipe()
            item['payload']['days'][0]['portions'][0]['dishIngredientRows'][0]['amount'] = amount
            invalid.append(item)
        for item in invalid:
            with self.subTest(item=item), self.assertRaises(ValueError):
                self.execute_recipe(args=item)
        self.assertEqual(self.factories, 0)
        self.assertEqual(self.observe().operations, 0)

    def test_no_three_argument_fallback_for_recipe_factory(self):
        outcome = self.execute_recipe(factory=self.factory)
        self.assertEqual(outcome.status, 'rolled_back')
        self.assertFalse(outcome.active)
        self.assertEqual(self.factories, 0)  # incompatible trusted factory never began
        self.assertEqual(self.tx.events, [])

    def test_recipe_global_intent_replay_keeps_target_across_task_owner_and_calls(self):
        from tongjianyun.business_agent_recipes import write_plan
        first = self.execute_recipe()
        other = claim('teacher-two')
        ledger = self.new_ledger()
        ledger.open_task(other)
        second = self.execute_recipe(current=other, ledger=ledger, call='new-call')
        self.assertTrue(second.replayed)
        self.assertEqual(second.operation_id, first.operation_id)
        self.assertEqual(self.factories, 1)
        self.assertEqual(write_plan(SITE, first.operation_id, recipe()).target_recipe,
                         write_plan(SITE, second.operation_id, recipe()).target_recipe)

    def test_recipe_normalization_defaults_and_meal_order_dedupe(self):
        first_args = recipe()
        portion = {'slot': 'breakfast', 'dishes': ['milk'], 'dishIngredientRows': []}
        first_args['payload']['days'][0]['portions'].append(portion)
        first = self.execute_recipe(args=first_args)
        second_args = json.loads(json.dumps(first_args))
        second_args['payload']['days'][0]['day'] = ''
        second_args['payload']['days'][0]['portions'].reverse()
        second = self.execute_recipe(args=second_args, call='again')
        self.assertTrue(second.replayed)
        self.assertEqual(first.operation_id, second.operation_id)
        self.assertEqual(self.factories, 1)

    def test_recipe_unknown_commit_fences_whole_site_week_and_existing_aggregate(self):
        self.tx.failure = 'commit'
        initial = recipe(recipe='recipe-existing', revision='original')
        first = self.execute_recipe(args=initial)
        self.assertEqual(first.status, 'uncertain')
        other = claim('teacher-two')
        ledger = self.new_ledger()
        ledger.open_task(other)
        self.tx = Transaction()
        for number, args in enumerate((recipe(day='2026-09-21'),
                                      recipe(day='2026-09-27', recipe='other-recipe', revision='other'))):
            blocked = self.execute_recipe(current=other, ledger=ledger, call='blocked-' + str(number), args=args)
            self.assertEqual(blocked.status, 'blocked')
            self.assertIsNone(blocked.operation_id)
        with self.ledger._connect() as db:
            keys = [json.loads(row[0]) for row in db.execute('SELECT resource FROM resources').fetchall()]
        self.assertCountEqual(keys, [['recipe_week', '2026-09-21'], ['recipe', 'recipe-existing']])
        self.assertEqual(self.factories, 1)

    def test_same_aggregate_cannot_escape_unknown_fence_by_changed_week(self):
        self.tx.failure = 'commit'
        self.execute_recipe(args=recipe(recipe='recipe-existing', revision='original'))
        next_week = recipe(recipe='recipe-existing', revision='new', day='2026-09-28')
        next_week['payload']['recipe'].update(weekStart='2026-09-28', weekEnd='2026-10-02')
        next_week['payload']['days'][0]['date'] = '2026-09-28'
        self.tx = Transaction()
        blocked = self.execute_recipe(args=next_week, call='move-week')
        self.assertEqual(blocked.status, 'blocked')
        self.assertEqual(self.factories, 1)

    def test_recipe_fence_does_not_block_independent_week_or_attendance(self):
        self.tx.failure = 'commit'
        self.execute_recipe()
        self.tx = Transaction()
        self.assertEqual(self.execute(call='attendance').status, 'committed')
        next_week = recipe(day='2026-09-28')
        next_week['payload']['recipe'].update(weekStart='2026-09-28', weekEnd='2026-10-02')
        next_week['payload']['days'][0]['date'] = '2026-09-28'
        self.assertEqual(self.execute_recipe(args=next_week, call='next-week').status, 'committed')

    def test_proven_recipe_rollback_releases_week_but_does_not_retry_same_intent(self):
        self.tx.failure = 'save'
        first = self.execute_recipe()
        self.assertEqual(first.status, 'rolled_back')
        self.tx = Transaction()
        repeated = self.execute_recipe(call='repeat')
        self.assertEqual(repeated.status, 'rolled_back')
        self.assertTrue(repeated.replayed)
        corrected = recipe()
        corrected['payload']['recipe']['title'] = 'Corrected original intent'
        self.assertEqual(self.execute_recipe(args=corrected, call='corrected').status, 'committed')
        self.assertEqual(self.factories, 2)

    def test_recipe_closed_gate_or_revoked_authority_blocks_receipt_replay(self):
        self.execute_recipe()
        self.authorized = False
        with self.assertRaises(PermissionError):
            self.execute_recipe(call='revoked')
        self.authorized = True
        self.ledger.close_task(self.claim.identity, self.claim.claim_id)
        with self.assertRaises(PermissionError):
            self.execute_recipe(call='closed')
        self.assertEqual(self.factories, 1)

    def test_concurrent_different_recipe_intent_same_week_is_fenced_before_factory(self):
        entered, release = threading.Event(), threading.Event()
        outcomes = []
        def hook(name):
            if name == 'save':
                entered.set()
                if not release.wait(10):
                    raise RuntimeError('coordination failed')
        self.tx.hook = hook
        thread = threading.Thread(target=lambda: outcomes.append(self.execute_recipe()))
        thread.start()
        try:
            self.assertTrue(entered.wait(5))
            other = claim('teacher-two')
            ledger = self.new_ledger()
            ledger.open_task(other)
            changed = recipe(day='2026-09-27')
            changed['payload']['recipe']['title'] = 'Another concurrent request'
            self.assertEqual(self.execute_recipe(current=other, ledger=ledger, args=changed).status, 'blocked')
            self.assertEqual(self.factories, 1)
        finally:
            release.set()
            thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(outcomes[0].status, 'committed')


class RecipeBusinessWritesTests(RecipeLedgerFixture, unittest.TestCase):
    def readback(self, current, tool, args, *, operation_id):
        from tongjianyun.business_agent_recipes import write_plan, week_bounds
        self.assertEqual(self.tx.events[-1], 'close')
        plan = write_plan(SITE, operation_id, args)
        start, end = week_bounds(args['day'])
        return {'recipe': plan.target_recipe, 'operation_id': operation_id, 'day': args['day'],
                'calendar_week_start': start, 'calendar_week_end': end,
                'week_start': args['payload']['recipe']['weekStart'], 'week_end': args['payload']['recipe']['weekEnd'],
                'visible_recipe_found': True, 'dishes': [{'dish': 'current-snapshot'}],
                'page_count': 1, 'dish_count': 1, 'offset': 0, 'has_more': False, 'next_offset': None, 'complete': True,
                'selection': {'view': 'recipe_week', 'day': args['day'], 'meal': 'lunch'}}

    def adapter(self, read=None):
        def no_duplicate(*_):
            raise AssertionError('Recipe native reader already published the authorized view')
        return BusinessWrites(self.ledger, transaction_factory=self.recipe_factory,
                              fresh_read=read or self.readback, publish_view=no_duplicate)

    def test_recipe_readback_uses_same_persisted_id_and_does_not_republish(self):
        result = self.adapter().dispatch(self.claim, 'recipe_save', recipe(), 'save')
        self.assertTrue(result['committed'])
        self.assertTrue(result['readback_available'])
        self.assertTrue(result['readback_complete'])
        self.assertEqual(result['operation_id'], self.recipe_calls[0][3])
        self.assertEqual(result['operation_id'], result['readback']['operation_id'])
        self.assertNotIn('group', result['selection'])

    def test_recipe_partial_fresh_page_is_not_complete_week_proof(self):
        def page(*args, **kwargs):
            return {**self.readback(*args, **kwargs), 'has_more': True, 'next_offset': 1,
                    'complete': False, 'dish_count': 20}
        result = self.adapter(page).dispatch(self.claim, 'recipe_save', recipe(), 'save')
        self.assertTrue(result['committed'])
        self.assertTrue(result['readback_available'])
        self.assertFalse(result['readback_complete'])
        self.assertFalse(result['readback']['complete'])

    def test_recipe_replay_uses_new_snapshot_same_operation_and_no_new_transaction(self):
        observed = []
        def read(*args, **kwargs):
            value = self.readback(*args, **kwargs)
            observed.append(value['operation_id'])
            value['dishes'][0]['dish'] = str(len(observed))
            return value
        adapter = self.adapter(read)
        first = adapter.dispatch(self.claim, 'recipe_save', recipe(), 'first')
        other = claim('teacher-two')
        self.ledger.open_task(other)
        second = adapter.dispatch(other, 'recipe_save', recipe(), 'second')
        self.assertTrue(second['replayed'])
        self.assertEqual(observed, [first['operation_id'], first['operation_id']])
        self.assertEqual(second['readback']['dishes'][0]['dish'], '2')
        self.assertEqual(self.factories, 1)

    def test_recipe_target_scope_or_page_mismatch_never_delivered_or_rewritten(self):
        patches = ({'recipe': 'other-recipe'}, {'operation_id': str(uuid.uuid4())}, {'day': '2026-09-25'},
                   {'calendar_week_start': '2026-09-28'}, {'calendar_week_end': '2026-10-04'},
                   {'week_start': '2026-09-22'}, {'week_end': '2026-09-24'}, {'visible_recipe_found': False},
                   {'selection': {'view': 'recipe_week', 'day': '2026-09-24', 'meal': 'lunch', 'recipe': 'injected'}},
                   {'complete': False}, {'has_more': True}, {'complete': 1}, {'page_count': True},
                   {'offset': 1}, {'next_offset': 1}, {'dish_count': 2})
        for number, changes in enumerate(patches):
            def read(*args, **kwargs):
                return {**self.readback(*args, **kwargs), **changes}
            with self.subTest(changes=changes):
                result = self.adapter(read).dispatch(self.claim, 'recipe_save', recipe(), 'call-' + str(number))
                self.assertTrue(result['committed'])
                self.assertFalse(result['readback_available'])
                self.assertFalse(result['readback_complete'])
                self.assertNotIn('readback', result)
                self.assertNotIn('selection', result)
                self.assertFalse(result['retry_allowed'])
        self.assertEqual(self.factories, 1)

    def test_recipe_missing_keyword_fresh_read_contract_preserves_receipt_no_fallback(self):
        def legacy(current, tool, args):
            raise AssertionError('Three-argument callback must not be retried')
        result = self.adapter(legacy).dispatch(self.claim, 'recipe_save', recipe(), 'save')
        self.assertTrue(result['committed'])
        self.assertFalse(result['readback_available'])
        self.assertFalse(result['readback_complete'])

    def test_recipe_unknown_commit_or_undrained_connection_never_reads(self):
        def forbidden(*args, **kwargs):
            raise AssertionError('Uncertain commit is not fresh read permission')
        self.tx.failure = 'commit'
        result = self.adapter(forbidden).dispatch(self.claim, 'recipe_save', recipe(), 'save')
        self.assertEqual(result['status'], 'uncertain')
        self.assertIsNone(result['committed'])
        self.assertFalse(result['readback_complete'])
        self.assertFalse(result['readback_available'])

    def test_recipe_revocation_after_readback_blocks_all_content_delivery(self):
        def revoked(*args, **kwargs):
            value = self.readback(*args, **kwargs)
            self.authorized = False
            return value
        with self.assertRaises(PermissionError):
            self.adapter(revoked).dispatch(self.claim, 'recipe_save', recipe(), 'save')
        self.assertEqual(self.factories, 1)


class RecipeNativeLedgerIntegrationTests(unittest.TestCase):
    def test_real_ledger_native_adapter_reader_source_registration_and_fresh_replay(self):
        # Real ledger/transaction/reader implementations, explicit Frappe/DB
        # doubles from the existing native fixture. Not a live recipe save.
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from tongjianyun import business_agent_recipes as recipes
        from tongjianyun.tests.test_business_agent_recipes import RecipeNativeTransactionTests
        fixture = RecipeNativeTransactionTests('test_factory_requires_trusted_operation_and_opens_no_connection')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        base = fixture.base
        base.state['cancel_requested'] = '0'
        registered = []
        fixture.stack.enter_context(patch.object(base.authority, 'ReadSet',
            side_effect=lambda scopes: SimpleNamespace(scopes=scopes)))
        fixture.adapter.authority.register_read = MagicMock(side_effect=lambda store, claim, sources: registered.extend(sources.scopes))
        base.store.emit = MagicMock()
        ledger = BusinessWriteLedger(Path(base.temp), base.site, authorize=fixture.adapter.authorize)
        ledger.open_task(base.claim)
        def no_duplicate(*_):
            raise AssertionError('Native recipe reader publishes exactly once')
        adapter = BusinessWrites(ledger, transaction_factory=fixture.adapter.transaction_factory,
            fresh_read=fixture.adapter.fresh_read, publish_view=no_duplicate)
        result = adapter.dispatch(base.claim, 'recipe_save', fixture.args, 'native-recipe')
        self.assertTrue(result['committed'])
        self.assertTrue(result['readback_available'])
        self.assertTrue(result['readback_complete'])
        target = recipes.write_plan(base.site, result['operation_id'], fixture.args).target_recipe
        self.assertEqual(fixture.saved[0][0]['recipe']['recipeId'], target)
        self.assertIn(recipes.source_scope(target), registered)
        self.assertEqual(result['readback']['dishes'][1]['ingredients'][0]['unit'], 'ml')
        self.assertEqual(ledger.observe(base.claim.identity, base.claim.claim_id).active_writes, 0)
        writer = fixture.saved[0][1]
        self.assertTrue(fixture.contexts)
        self.assertTrue(all(connection is not writer and connection is not base.outer.db for connection in fixture.contexts))
        base.store.emit.assert_called_once()
        self.assertEqual(base.store.emit.call_args.args[1]['selection'], result['selection'])
        # Fresh adapter has no in-memory transaction/receipt: immutable SQLite
        # operation identity must still select the same committed target.
        fresh = recipes.RecipeWriteAdapter(base.site, base.temp, store=base.store)
        fresh.authority.register_read = MagicMock(side_effect=lambda store, claim, sources: registered.extend(sources.scopes))
        again = BusinessWrites(ledger, transaction_factory=fresh.transaction_factory,
            fresh_read=fresh.fresh_read, publish_view=no_duplicate).dispatch(
                base.claim, 'recipe_save', fixture.args, 'fresh-adapter-replay')
        self.assertTrue(again['replayed'])
        self.assertTrue(again['readback_available'])
        self.assertEqual(result['operation_id'], again['operation_id'])
        self.assertEqual(again['readback']['recipe'], target)
        self.assertEqual(len(fixture.saved), 1)
        self.assertIs(base.local.get(), base.outer)


if __name__ == '__main__':
    unittest.main()
