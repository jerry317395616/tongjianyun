"""Pure filesystem concurrency/state/SSE tests; no Frappe DB, queue or Codex."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
import uuid

from tongjianyun import business_agent_tasks as tasks


class BusinessTaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.allowed = True
        self.authorize = MagicMock(side_effect=lambda identity, scopes: self.allowed)
        self.observe = MagicMock(side_effect=lambda identity, claim: tasks.ExecutionObservation(claim, 'running', 0))
        self.queue = MagicMock(side_effect=lambda job: tasks.QueueObservation(job, 'unknown'))
        self.store = tasks.BusinessTaskStore(self.directory, 'qa.localhost', authorize=self.authorize,
                          observe_execution=self.observe, observe_queue=self.queue)
        self.identity = self.create()

    def create(self, owner='teacher@example.invalid', message='查看学生人数', context=None):
        result = self.store.create(owner, str(uuid.uuid4()), message, context)
        return result['identity']

    def claim(self, identity=None):
        identity = identity or self.identity
        ticket = self.store.take_dispatch(identity)
        self.assertEqual(ticket.queue, 'business_codex')
        self.store.acknowledge_dispatch(ticket)
        return self.store.claim(identity, ticket.job_id)

    def message(self, claim, text='已核对', item_id='answer'):
        return self.store.emit(claim, {'kind': 'message', 'item_id': item_id, 'text': text})

    def exited(self, claim, *, writes=0, code=0, complete=True):
        self.observe.side_effect = None
        self.observe.return_value = tasks.ExecutionObservation(claim.claim_id, 'exited', writes, code, complete)

    def test_create_is_durable_without_queueing_or_starting_model(self):
        reopened = tasks.BusinessTaskStore(self.directory, 'qa.localhost', authorize=self.authorize,
                          observe_execution=self.observe, observe_queue=self.queue)
        result = reopened.task(self.identity)
        self.assertEqual(result['status'], 'queued')
        self.assertEqual(result['mode'], 'business')
        self.assertEqual(len(reopened.events(self.identity)), 1)
        self.observe.assert_not_called()
        self.queue.assert_not_called()
        self.assertNotIn('meal-chat', self.store.job_id(self.identity))

    def test_site_directory_cannot_be_rebound(self):
        with self.assertRaises(PermissionError):
            tasks.BusinessTaskStore(self.directory, 'other.localhost', authorize=self.authorize,
                                   observe_execution=self.observe, observe_queue=self.queue)

    def test_duplicate_request_has_one_task_event_and_outbox(self):
        again = self.store.create(self.identity.owner, self.identity.task_id, '查看学生人数')
        self.assertFalse(again['created'])
        self.assertEqual(len(self.store.events(self.identity)), 1)
        self.assertIsNotNone(self.store.take_dispatch(self.identity))
        self.assertIsNone(self.store.take_dispatch(self.identity))

    def test_request_id_cannot_change_prompt_context_or_owner(self):
        with self.assertRaises(ValueError):
            self.store.create(self.identity.owner, self.identity.task_id, '改成另一项操作')
        with self.assertRaises(ValueError):
            self.store.create(self.identity.owner, self.identity.task_id, '查看学生人数', {'day': '2026-09-16'})
        with self.assertRaises(PermissionError):
            self.store.create('other@example.invalid', self.identity.task_id, '查看学生人数')

    def test_identity_and_execution_fields_cannot_be_in_context(self):
        for field in ('owner', 'site', 'mode', 'worker_token', 'sql', 'method', 'queue'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.create(context={field: 'Administrator'})
        for choice in ({'view': 'students', 'actor': 'Administrator'},
                       {'view': 'students', 'filters': {'reasoning': 'hidden'}},
                       {'view': 'students', 'filters': {'sql': 'select *'}}):
            with self.subTest(choice=choice), self.assertRaises(ValueError):
                self.create(context={'selection': choice})

    def test_canonical_id_owner_and_prompt_limits(self):
        for owner in ('Guest', '', 'bad\nowner', 'x' * 141):
            with self.subTest(owner=owner), self.assertRaises(ValueError):
                self.store.create(owner, str(uuid.uuid4()), '请求')
        for request in ('../../file', 'A' * 36, self.identity.task_id.upper(), None):
            with self.subTest(request=request), self.assertRaises(ValueError):
                self.store.create(self.identity.owner, request, '请求')
        for text in ('', ' ', 'x' * 8001, {}, None):
            with self.subTest(text_type=type(text)), self.assertRaises(ValueError):
                self.create(message=text)

    def test_current_authority_required_to_create_and_read(self):
        self.allowed = False
        with self.assertRaises(PermissionError):
            self.create()
        with self.assertRaises(PermissionError):
            self.store.task(self.identity)
        self.allowed = True
        self.assertEqual(self.store.task(self.identity)['status'], 'cancelled')

    def test_cross_owner_site_mode_are_rejected_without_revoking_victim(self):
        for identity in (replace(self.identity, owner='other@example.invalid'), replace(self.identity, site='other.localhost'),
                         replace(self.identity, mode='admin_project')):
            with self.subTest(identity=identity), self.assertRaises(PermissionError):
                self.store.events(identity)
        self.assertEqual(self.store.task(self.identity)['status'], 'queued')

    def test_atomic_dispatch_has_one_winner(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.store.take_dispatch(self.identity), range(16)))
        self.assertEqual(sum(value is not None for value in results), 1)

    def test_queue_ticket_cannot_override_queue_or_token(self):
        ticket = self.store.take_dispatch(self.identity)
        for bad in (replace(ticket, queue='meal_chat'), replace(ticket, job_id='meal-chat-root'),
                    replace(ticket, token='x' * 43), replace(ticket, identity=replace(self.identity, owner='other'))):
            with self.subTest(bad=bad.queue), self.assertRaises(PermissionError):
                self.store.acknowledge_dispatch(bad)
        self.store.acknowledge_dispatch(ticket)
        self.store.acknowledge_dispatch(ticket)

    def test_claim_requires_actual_outbox_dispatch(self):
        with self.assertRaises(PermissionError):
            self.store.claim(self.identity, self.store.job_id(self.identity))
        self.store.take_dispatch(self.identity)
        with self.assertRaises(PermissionError):
            self.store.claim(self.identity, 'other-job')

    def test_concurrent_duplicate_queue_delivery_claims_once(self):
        self.store.take_dispatch(self.identity)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.store.claim(self.identity, self.store.job_id(self.identity)), range(16)))
        self.assertEqual(sum(value is not None for value in results), 1)
        self.assertEqual(self.store.task(self.identity)['status'], 'running')

    def test_lost_dispatch_unknown_observation_never_requeues(self):
        self.store.take_dispatch(self.identity)
        self.assertEqual(self.store.recover_dispatch(self.identity), 'dispatching')
        self.assertIsNone(self.store.take_dispatch(self.identity))
        self.queue.side_effect = RuntimeError('temporary observation failure')
        with self.assertRaises(RuntimeError):
            self.store.recover_dispatch(self.identity)
        self.assertIsNone(self.store.take_dispatch(self.identity))

    def test_observed_absence_before_claim_allows_same_job_redelivery_only(self):
        first = self.store.take_dispatch(self.identity)
        self.queue.side_effect = lambda job: tasks.QueueObservation(job, 'absent')
        self.assertEqual(self.store.recover_dispatch(self.identity), 'pending')
        second = self.store.take_dispatch(self.identity)
        self.assertEqual(first.job_id, second.job_id)
        self.assertNotEqual(first.token, second.token)
        with self.assertRaises(PermissionError):
            self.store.acknowledge_dispatch(first)

    def test_acknowledged_job_loss_before_claim_allows_same_job_redelivery(self):
        first = self.store.take_dispatch(self.identity)
        self.store.acknowledge_dispatch(first)
        self.queue.side_effect = lambda job: tasks.QueueObservation(job, 'absent')
        self.assertEqual(self.store.recover_dispatch(self.identity), 'pending')
        self.queue.assert_called_once_with(first.job_id)
        second = self.store.take_dispatch(self.identity)
        self.assertEqual(second.job_id, first.job_id)
        self.assertNotEqual(second.token, first.token)
        with self.assertRaises(PermissionError):
            self.store.acknowledge_dispatch(first)
        self.store.acknowledge_dispatch(second)
        self.assertIsNotNone(self.store.claim(self.identity, second.job_id))
        self.assertIsNone(self.store.claim(self.identity, second.job_id))

    def test_observed_present_then_missing_unclaimed_job_can_be_reconciled(self):
        ticket = self.store.take_dispatch(self.identity)
        self.queue.side_effect = lambda job: tasks.QueueObservation(job, 'present')
        self.assertEqual(self.store.recover_dispatch(self.identity), 'dispatched')
        self.queue.side_effect = lambda job: tasks.QueueObservation(job, 'absent')
        self.assertEqual(self.store.recover_dispatch(self.identity), 'pending')
        self.assertEqual(self.store.take_dispatch(self.identity).job_id, ticket.job_id)

    def test_acknowledged_job_unknown_observation_never_requeues(self):
        ticket = self.store.take_dispatch(self.identity)
        self.store.acknowledge_dispatch(ticket)
        self.assertEqual(self.store.recover_dispatch(self.identity), 'dispatched')
        self.queue.assert_called_once_with(ticket.job_id)
        self.assertIsNone(self.store.take_dispatch(self.identity))

    def test_acknowledged_job_claim_during_absence_observation_never_requeues(self):
        ticket = self.store.take_dispatch(self.identity)
        self.store.acknowledge_dispatch(ticket)
        claims = []
        def observed(job):
            claims.append(self.store.claim(self.identity, job))
            return tasks.QueueObservation(job, 'absent')
        self.queue.side_effect = observed
        self.assertEqual(self.store.recover_dispatch(self.identity), 'dispatched')
        self.assertIsNotNone(claims[0])
        self.assertIsNone(self.store.take_dispatch(self.identity))
        self.assertIsNone(self.store.claim(self.identity, ticket.job_id))

    def test_stale_acknowledged_absence_cannot_reset_new_dispatch_generation(self):
        first = self.store.take_dispatch(self.identity)
        self.store.acknowledge_dispatch(first)
        newer = []
        def observed(job):
            self.queue.side_effect = lambda current: tasks.QueueObservation(current, 'absent')
            self.assertEqual(self.store.recover_dispatch(self.identity), 'pending')
            newer.append(self.store.take_dispatch(self.identity))
            return tasks.QueueObservation(job, 'absent')
        self.queue.side_effect = observed
        self.assertEqual(self.store.recover_dispatch(self.identity), 'dispatching')
        self.assertNotEqual(newer[0].token, first.token)
        self.assertIsNone(self.store.take_dispatch(self.identity))
        self.store.acknowledge_dispatch(newer[0])
        self.assertIsNotNone(self.store.claim(self.identity, newer[0].job_id))

    def test_stale_absence_cannot_reset_new_observed_present_generation(self):
        first = self.store.take_dispatch(self.identity)
        self.queue.side_effect = lambda job: tasks.QueueObservation(job, 'present')
        self.assertEqual(self.store.recover_dispatch(self.identity), 'dispatched')
        newer = []
        def observed(job):
            self.queue.side_effect = lambda current: tasks.QueueObservation(current, 'absent')
            self.assertEqual(self.store.recover_dispatch(self.identity), 'pending')
            newer.append(self.store.take_dispatch(self.identity))
            self.queue.side_effect = lambda current: tasks.QueueObservation(current, 'present')
            self.assertEqual(self.store.recover_dispatch(self.identity), 'dispatched')
            return tasks.QueueObservation(job, 'absent')
        self.queue.side_effect = observed
        self.assertEqual(self.store.recover_dispatch(self.identity), 'dispatched')
        self.assertNotEqual(newer[0].token, first.token)
        self.assertIsNone(self.store.take_dispatch(self.identity))
        self.store.acknowledge_dispatch(newer[0])
        self.assertIsNotNone(self.store.claim(self.identity, newer[0].job_id))

    def test_cancel_during_acknowledged_absence_observation_never_requeues(self):
        ticket = self.store.take_dispatch(self.identity)
        self.store.acknowledge_dispatch(ticket)
        def observed(job):
            self.assertEqual(self.store.cancel(self.identity), 'cancelled')
            return tasks.QueueObservation(job, 'absent')
        self.queue.side_effect = observed
        self.assertEqual(self.store.recover_dispatch(self.identity), 'dispatched')
        self.assertIsNone(self.store.take_dispatch(self.identity))
        self.assertIsNone(self.store.claim(self.identity, ticket.job_id))

    def test_queue_present_or_already_claimed_never_starts_second_execution(self):
        ticket = self.store.take_dispatch(self.identity)
        claim = self.store.claim(self.identity, ticket.job_id)
        self.queue.side_effect = lambda job: tasks.QueueObservation(job, 'absent')
        self.assertEqual(self.store.recover_dispatch(self.identity), 'dispatching')
        self.assertIsNone(self.store.claim(self.identity, ticket.job_id))
        self.queue.side_effect = lambda job: tasks.QueueObservation(job, 'present')
        self.assertEqual(self.store.recover_dispatch(self.identity), 'dispatched')
        self.assertEqual(self.store.binding_state(claim)['status'], 'running')

    def test_queue_observer_reentry_occurs_without_sqlite_write_lock(self):
        ticket = self.store.take_dispatch(self.identity)
        def observed(job):
            self.store.acknowledge_dispatch(ticket)
            return tasks.QueueObservation(job, 'absent')
        self.queue.side_effect = observed
        self.assertEqual(self.store.recover_dispatch(self.identity), 'dispatched')

    def test_authorizer_reentry_and_state_change_is_reread(self):
        claim = self.claim()
        def authorize(identity, scopes):
            self.store.revoke(identity)
            return True
        self.authorize.side_effect = authorize
        state = self.store.binding_state(claim)
        self.assertEqual(state['status'], 'stopping')
        self.assertEqual(state['cancel_requested'], '1')

    def test_worker_tokens_are_bound_and_never_in_public_task_or_events(self):
        claim = self.claim()
        public = json.dumps(self.store.task(self.identity)) + json.dumps(self.store.events(self.identity))
        self.assertNotIn(claim.token, public)
        self.assertNotIn(claim.claim_id, public)
        for bad in (replace(claim, token='x' * 43), replace(claim, claim_id=str(uuid.uuid4())),
                    replace(claim, identity=replace(self.identity, owner='other'))):
            with self.subTest(claim=bad.claim_id), self.assertRaises(PermissionError):
                self.message(bad)

    def test_binding_state_matches_business_tool_contract(self):
        claim = self.claim()
        self.assertEqual(self.store.binding_state(claim), {'site': self.identity.site, 'owner': self.identity.owner,
                         'task_id': self.identity.task_id, 'mode': 'business', 'status': 'running', 'cancel_requested': '0'})

    def test_public_event_allowlist_rejects_reasoning_raw_tool_output_and_terminal(self):
        claim = self.claim()
        for event in ({'kind': 'reasoning', 'text': 'hidden'}, {'kind': 'command_execution', 'stdout': 'secret'},
                      {'kind': 'message', 'item_id': 'a', 'text': 'ok', 'stderr': 'raw'},
                      {'kind': 'terminal', 'status': 'completed', 'text': 'pretend finished'}, {'kind': {}},
                      {'kind': 'progress', 'item_id': 'a', 'text': '读取', 'status': {}},
                      {'kind': 'view', 'version': True, 'title': '学生', 'selection': {'view': 'students'}}):
            with self.subTest(event=event), self.assertRaises(ValueError):
                self.store.emit(claim, event)
        self.assertEqual(len(self.store.events(self.identity)), 2)

    def test_public_event_size_and_finite_json_guards(self):
        claim = self.claim()
        for event in ({'kind': 'message', 'item_id': 'a', 'text': 'x' * 16001},
                      {'kind': 'message', 'item_id': 'a', 'text': '字' * 16000},
                      {'kind': 'view', 'version': 1, 'title': '学生', 'selection': {'view': 'students', 'offset': float('nan')}},
                      {'kind': 'message', 'item_id': 'a\ninject', 'text': 'ok'}):
            with self.subTest(kind=event['kind']), self.assertRaises(ValueError):
                self.store.emit(claim, event)

    def test_public_message_redacts_key_patterns_and_view_has_no_html(self):
        claim = self.claim()
        event_id = self.message(claim, 'sk-abcdefghijklmnop Authorization: Bearer token1234')
        self.assertNotIn('sk-', json.dumps(self.store.events(self.identity)))
        self.assertNotIn('token1234', json.dumps(self.store.events(self.identity)))
        self.assertTrue(event_id.startswith(self.identity.task_id + ':'))
        with self.assertRaises(ValueError):
            self.store.emit(claim, {'kind': 'view', 'version': 1, 'title': '学生',
                                   'selection': {'view': 'students', 'html': '<script>'}})

    def test_future_registered_business_view_is_not_hardcoded_to_attendance(self):
        claim = self.claim()
        event = {'kind': 'view', 'version': 1, 'title': '新业务',
                 'selection': {'view': 'future_business_view', 'entity': 'suppliers', 'filters': {'status': 'active'}}}
        self.store.emit(claim, event)
        self.assertEqual(self.store.events(self.identity)[-1]['selection'], event['selection'])

    def test_queued_cancel_is_terminal_and_pending_worker_cannot_start(self):
        ticket = self.store.take_dispatch(self.identity)
        self.assertEqual(self.store.cancel(self.identity), 'cancelled')
        self.store.acknowledge_dispatch(ticket)
        self.assertIsNone(self.store.claim(self.identity, ticket.job_id))
        self.assertEqual(self.store.events(self.identity)[-1]['kind'], 'terminal')

    def test_running_cancel_revokes_tools_but_waits_for_process_and_writes(self):
        claim = self.claim()
        self.assertEqual(self.store.cancel(self.identity), 'stopping')
        state = self.store.binding_state(claim)
        self.assertEqual((state['status'], state['cancel_requested']), ('stopping', '1'))
        with self.assertRaises(PermissionError):
            self.message(claim)
        self.assertEqual(self.store.finish(claim), 'stopping')
        self.exited(claim, writes=1)
        self.assertEqual(self.store.finish(claim), 'stopping')
        self.exited(claim, writes=0)
        self.assertEqual(self.store.finish(claim), 'cancelled')
        self.assertIn('不会自动撤销', self.store.events(self.identity)[-1]['text'])

    def test_cancel_and_finish_are_idempotent_single_terminal_event(self):
        claim = self.claim()
        self.store.cancel(self.identity)
        self.store.cancel(self.identity)
        self.exited(claim)
        self.store.finish(claim)
        self.store.finish(claim)
        self.store.cancel(self.identity)
        self.assertEqual(sum(row['kind'] == 'terminal' for row in self.store.events(self.identity)), 1)

    def test_completed_requires_process_exit_turn_completion_and_public_answer(self):
        for answer, code, turn, expected in ((True, 0, True, 'completed'), (False, 0, True, 'failed'),
                                            (True, 1, True, 'failed'), (True, 0, False, 'failed')):
            identity = self.create()
            claim = self.claim(identity)
            if answer:
                self.message(claim)
            self.exited(claim, code=code, complete=turn)
            with self.subTest(answer=answer, code=code, turn=turn):
                self.assertEqual(self.store.finish(claim), expected)

    def test_unknown_or_mismatched_execution_observation_never_finishes(self):
        claim = self.claim()
        self.observe.side_effect = None
        self.observe.return_value = tasks.ExecutionObservation(claim.claim_id, 'unknown', 0)
        self.assertEqual(self.store.finish(claim), 'running')
        for observation in (True, tasks.ExecutionObservation(str(uuid.uuid4()), 'exited', 0),
                            tasks.ExecutionObservation(claim.claim_id, 'missing', 0),
                            tasks.ExecutionObservation(claim.claim_id, 'exited', True)):
            self.observe.return_value = observation
            with self.subTest(observation=observation), self.assertRaises(ValueError):
                self.store.finish(claim)
        self.assertEqual(self.store.task(self.identity)['status'], 'running')
        with self.assertRaises(TypeError):
            self.store.finish(claim, status='completed')

    def test_execution_observer_can_reenter_and_request_stop_without_deadlock(self):
        claim = self.claim()
        self.message(claim)
        def observe(identity, claim_id):
            self.store.cancel(identity)
            return tasks.ExecutionObservation(claim_id, 'exited', 0, 0, True)
        self.observe.side_effect = observe
        self.assertEqual(self.store.finish(claim), 'cancelled')

    def test_revocation_at_finish_prevents_claiming_success(self):
        claim = self.claim()
        self.message(claim)
        self.exited(claim)
        self.allowed = False
        self.assertEqual(self.store.finish(claim), 'cancelled')
        with self.assertRaises(PermissionError):
            self.store.binding_state(claim)

    def test_revocation_before_worker_exit_reports_stopping_not_stale_running(self):
        claim = self.claim()
        self.allowed = False
        self.assertEqual(self.store.finish(claim), 'stopping')
        self.assertEqual(self.store._owned(self.identity)['status'], 'stopping')

    def test_reconcile_default_lease_proof_never_steals_live_worker_finish(self):
        claim = self.claim()
        self.message(claim)
        self.exited(claim)
        self.assertFalse(self.observe.return_value.lease_closed)
        self.assertEqual(self.store.reconcile(self.identity), 'running')
        self.assertEqual(self.store.finish(claim), 'completed')

    def test_reconcile_reopened_store_without_worker_token_can_only_fail(self):
        claim = self.claim()
        self.message(claim)
        claim_id = claim.claim_id
        del claim
        reopened = tasks.BusinessTaskStore(self.directory, self.identity.site, authorize=self.authorize,
                          observe_execution=self.observe, observe_queue=self.queue)
        self.observe.side_effect = None
        self.observe.return_value = tasks.ExecutionObservation(claim_id, 'exited', 0, 0, True, True)
        self.assertEqual(reopened.reconcile(self.identity), 'failed')
        self.assertIsNone(reopened.active_task(self.identity.owner))
        self.assertIsNone(reopened.claim(self.identity, reopened.job_id(self.identity)))
        self.assertIsNone(reopened.take_dispatch(self.identity))
        self.assertEqual(reopened.events(self.identity)[-1]['status'], 'failed')
        self.observe.assert_called_once_with(self.identity, claim_id)
        self.queue.assert_not_called()

    def test_reconcile_requires_exit_drained_writes_and_closed_lease(self):
        claim = self.claim()
        self.observe.side_effect = None
        for state, writes, closed in (('running', 0, True), ('unknown', 0, True),
                                      ('exited', 1, True), ('exited', 0, False)):
            with self.subTest(state=state, writes=writes, closed=closed):
                self.observe.return_value = tasks.ExecutionObservation(claim.claim_id, state, writes, 0, True, closed)
                self.assertEqual(self.store.reconcile(self.identity), 'running')
        self.assertFalse(any(event['kind'] == 'terminal' for event in self.store.events(self.identity)))

    def test_reconcile_unclaimed_and_terminal_tasks_never_inspect_runtime(self):
        self.assertEqual(self.store.reconcile(self.identity), 'queued')
        self.store.cancel(self.identity)
        self.assertEqual(self.store.reconcile(self.identity), 'cancelled')
        self.observe.assert_not_called()

    def test_reconcile_checks_exact_identity_before_observation_or_revocation(self):
        self.claim()
        for identity in (replace(self.identity, owner='other'), replace(self.identity, site='other.localhost'),
                         replace(self.identity, mode='admin_project')):
            with self.subTest(identity=identity), self.assertRaises(PermissionError):
                self.store.reconcile(identity)
        self.observe.assert_not_called()
        self.assertEqual(self.store.task(self.identity)['status'], 'running')
        with self.assertRaises(TypeError):
            self.store.reconcile(self.identity, status='completed')

    def test_reconcile_rejects_forged_mismatched_or_malformed_proof(self):
        claim = self.claim()
        valid = tasks.ExecutionObservation(claim.claim_id, 'exited', 0, 0, True, True)
        self.observe.side_effect = None
        for value in ({'state': 'exited', 'lease_closed': True}, replace(valid, claim_id=str(uuid.uuid4())),
                      replace(valid, active_writes=True), replace(valid, active_writes=-1),
                      replace(valid, lease_closed=1), replace(valid, lease_closed='true'),
                      replace(valid, turn_completed=1), replace(valid, exit_code=True),
                      replace(valid, state='missing'), replace(valid, state={})):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.observe.return_value = value
                self.store.reconcile(self.identity)
        self.assertEqual(self.store.task(self.identity)['status'], 'running')

    def test_reconcile_runtime_failure_keeps_claim_and_active_slot(self):
        claim = self.claim()
        self.observe.side_effect = ConnectionError('launcher unavailable')
        with self.assertRaises(ConnectionError):
            self.store.reconcile(self.identity)
        self.assertEqual(self.store.active_task(self.identity.owner)['task_id'], self.identity.task_id)
        self.assertIsNone(self.store.claim(self.identity, self.store.job_id(self.identity)))
        self.assertEqual(self.store._owned(self.identity)['claim_id'], claim.claim_id)

    def test_reconcile_concurrent_cancel_wins_after_observation(self):
        claim = self.claim()
        observed, resume = threading.Event(), threading.Event()
        def observe(identity, claim_id):
            observed.set()
            if not resume.wait(5):
                raise AssertionError('cancel never released runtime observer')
            return tasks.ExecutionObservation(claim_id, 'exited', 0, 0, True, True)
        self.observe.side_effect = observe
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.store.reconcile, self.identity)
            try:
                self.assertTrue(observed.wait(5))
                self.assertEqual(self.store.cancel(self.identity), 'stopping')
            finally:
                resume.set()
            self.assertEqual(future.result(timeout=5), 'cancelled')
        self.assertEqual(self.store.finish(claim), 'cancelled')
        self.assertEqual(sum(event['kind'] == 'terminal' for event in self.store.events(self.identity)), 1)

    def test_reconcile_concurrent_live_worker_finish_is_not_overwritten(self):
        claim = self.claim()
        self.message(claim)
        proof = tasks.ExecutionObservation(claim.claim_id, 'exited', 0, 0, True, True)
        def observe(identity, claim_id):
            # Simulate the worker persisting a legitimate completion while a
            # separate recovery observer is awaiting its final lease proof.
            self.observe.side_effect = None
            self.observe.return_value = replace(proof, lease_closed=False)
            self.assertEqual(self.store.finish(claim), 'completed')
            return proof
        self.observe.side_effect = observe
        self.assertEqual(self.store.reconcile(self.identity), 'completed')
        self.assertEqual(sum(event['kind'] == 'terminal' for event in self.store.events(self.identity)), 1)

    def test_reconcile_concurrent_recovery_emits_one_terminal_only(self):
        claim = self.claim()
        gate = threading.Barrier(4)
        def observe(identity, claim_id):
            gate.wait(timeout=5)
            return tasks.ExecutionObservation(claim_id, 'exited', 0, 0, True, True)
        self.observe.side_effect = observe
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.store.reconcile(self.identity), range(4)))
        self.assertEqual(results, ['failed'] * 4)
        self.assertEqual(sum(event['kind'] == 'terminal' for event in self.store.events(self.identity)), 1)

    def test_reconcile_revoked_scope_can_cancel_without_exposing_history(self):
        claim = self.claim()
        self.message(claim, 'private old-authority data')
        self.allowed = False
        self.observe.side_effect = None
        self.observe.return_value = tasks.ExecutionObservation(claim.claim_id, 'exited', 0, 0, True, True)
        self.assertEqual(self.store.reconcile(self.identity), 'cancelled')
        with self.assertRaises(PermissionError):
            self.store.events(self.identity)

    def test_reconcile_rechecks_revocation_after_blocking_observation(self):
        self.claim()
        def observe(identity, claim_id):
            self.allowed = False
            return tasks.ExecutionObservation(claim_id, 'exited', 0, 0, True, True)
        self.observe.side_effect = observe
        self.assertEqual(self.store.reconcile(self.identity), 'cancelled')

    def test_reconcile_does_not_settle_a_changed_claim_generation(self):
        self.claim()
        replacement = str(uuid.uuid4())
        def observe(identity, claim_id):
            # Synthetic corruption/concurrency fixture only; production never
            # changes a claimed task's generation or replays its execution.
            with self.store._transaction() as db:
                db.execute('UPDATE tasks SET claim_id=? WHERE task_id=?', (replacement, identity.task_id))
            return tasks.ExecutionObservation(claim_id, 'exited', 0, 0, True, True)
        self.observe.side_effect = observe
        self.assertEqual(self.store.reconcile(self.identity), 'running')
        self.assertFalse(any(event['kind'] == 'terminal' for event in self.store.events(self.identity)))

    def test_reconcile_state_and_terminal_event_commit_atomically(self):
        claim = self.claim()
        self.observe.side_effect = None
        self.observe.return_value = tasks.ExecutionObservation(claim.claim_id, 'exited', 0, 0, True, True)
        before = self.store.events(self.identity)
        with patch.object(self.store, '_event', side_effect=sqlite3.OperationalError('fixture disk failure')):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.reconcile(self.identity)
        self.assertEqual(self.store.task(self.identity)['status'], 'running')
        self.assertEqual(self.store.events(self.identity), before)

    def test_active_slot_reconciles_revoked_old_scope_before_exposing_content(self):
        claim = self.claim()
        self.message(claim, 'old class private data')
        self.allowed = False
        self.observe.side_effect = None
        self.observe.return_value = tasks.ExecutionObservation(claim.claim_id, 'exited', 0, 0, False, True)
        with patch.object(self.store, 'task', wraps=self.store.task) as exposed:
            self.assertIsNone(self.store.active_task(self.identity.owner))
        exposed.assert_not_called()
        self.assertEqual(self.store._owned(self.identity)['status'], 'cancelled')
        with self.assertRaises(PermissionError):
            self.store.events(self.identity)
        self.allowed = True  # New work has its own independently checked scope.
        new_identity = self.create(message='new authorized class request')
        self.assertEqual(self.store.active_task(self.identity.owner)['task_id'], new_identity.task_id)

    def test_active_slot_revoked_but_unknown_execution_is_not_freed(self):
        claim = self.claim()
        self.allowed = False
        with self.assertRaises(PermissionError):
            self.store.active_task(self.identity.owner)
        self.assertEqual(self.store._owned(self.identity)['status'], 'stopping')
        self.assertEqual(self.store._owned(self.identity)['claim_id'], claim.claim_id)
        with self.assertRaises(PermissionError):
            self.store.take_dispatch(self.identity)

    def test_active_slot_observation_failure_keeps_authorized_task(self):
        self.claim()
        self.observe.side_effect = ConnectionError('private launcher endpoint')
        result = self.store.active_task(self.identity.owner)
        self.assertEqual((result['task_id'], result['status']), (self.identity.task_id, 'running'))
        self.assertNotIn('private launcher endpoint', str(result))
        self.assertIsNone(self.store.claim(self.identity, self.store.job_id(self.identity)))

    def test_active_slot_observation_failure_still_denies_revoked_content(self):
        self.claim()
        self.allowed = False
        self.observe.side_effect = ConnectionError('launcher unavailable')
        with self.assertRaises(PermissionError):
            self.store.active_task(self.identity.owner)
        self.assertEqual(self.store._owned(self.identity)['status'], 'stopping')

    def test_active_slot_malformed_proof_cannot_create_capacity(self):
        claim = self.claim()
        self.observe.side_effect = None
        self.observe.return_value = tasks.ExecutionObservation(claim.claim_id, 'exited', 0, 0, True, 'true')
        self.assertEqual(self.store.active_task(self.identity.owner)['status'], 'running')
        self.assertEqual(self.store._owned(self.identity)['claim_id'], claim.claim_id)

    def test_active_slot_checks_next_persisted_task_after_exact_old_cleanup(self):
        claim = self.claim()
        next_identity = self.create()
        self.observe.side_effect = None
        self.observe.return_value = tasks.ExecutionObservation(claim.claim_id, 'exited', 0, 0, True, True)
        result = self.store.active_task(self.identity.owner)
        self.assertEqual((result['task_id'], result['status']), (next_identity.task_id, 'queued'))
        self.assertEqual(self.store.task(self.identity)['status'], 'failed')
        self.observe.assert_called_once_with(self.identity, claim.claim_id)

    def test_active_slot_other_owner_does_not_observe_or_reconcile_victim(self):
        self.claim()
        self.assertIsNone(self.store.active_task('other@example.invalid'))
        self.observe.assert_not_called()
        self.assertEqual(self.store._owned(self.identity)['status'], 'running')

    def test_before_bind_cancel_can_settle_only_from_exact_permanent_seal(self):
        claim = self.claim()
        original = self.store._owned(self.identity)
        self.store.cancel(self.identity)
        self.observe.side_effect = lambda identity, claim_id: tasks.ExecutionObservation(claim_id, 'unknown', 0)
        seal = MagicMock(return_value=tasks.ExecutionObservation(claim.claim_id, 'never_started_and_sealed',
                                                               0, None, False, True))
        self.store.seal_execution = seal
        self.assertEqual(self.store.reconcile(self.identity), 'cancelled')
        seal.assert_called_once_with(self.identity, claim.claim_id)
        current = self.store._owned(self.identity)
        self.assertEqual(current['worker_hash'], original['worker_hash'])
        self.assertEqual(current['claim_id'], original['claim_id'])
        self.assertEqual(self.store.events(self.identity)[-1]['status'], 'cancelled')
        self.assertIsNone(self.store.take_dispatch(self.identity))
        self.assertIsNone(self.store.claim(self.identity, self.store.job_id(self.identity)))
        self.assertEqual(self.store.reconcile(self.identity), 'cancelled')
        self.assertEqual(seal.call_count, 1)

    def test_before_bind_running_unknown_never_seals_by_age_or_read(self):
        self.claim()
        self.observe.side_effect = lambda identity, claim_id: tasks.ExecutionObservation(claim_id, 'unknown', 0)
        seal = self.store.seal_execution = MagicMock()
        self.store.clock = lambda: 9_999_999_999
        self.assertEqual(self.store.reconcile(self.identity), 'running')
        self.assertEqual(self.store.active_task(self.identity.owner)['status'], 'running')
        seal.assert_not_called()

    def test_before_bind_without_sealer_never_treats_missing_as_exit(self):
        self.claim()
        self.store.cancel(self.identity)
        self.observe.side_effect = lambda identity, claim_id: tasks.ExecutionObservation(claim_id, 'unknown', 0)
        self.assertIsNone(self.store.seal_execution)
        self.assertEqual(self.store.reconcile(self.identity), 'stopping')
        self.assertEqual(self.store.active_task(self.identity.owner)['status'], 'stopping')

    def test_before_bind_seal_refusal_does_not_misclassify_racing_bind(self):
        claim = self.claim()
        self.store.cancel(self.identity)
        self.observe.side_effect = lambda identity, claim_id: tasks.ExecutionObservation(claim_id, 'unknown', 0)
        for state, closed in (('running', False), ('unknown', False), ('exited', False)):
            with self.subTest(state=state):
                self.store.seal_execution = MagicMock(return_value=tasks.ExecutionObservation(
                    claim.claim_id, state, 0, 0 if state == 'exited' else None, False, closed))
                self.assertEqual(self.store.reconcile(self.identity), 'stopping')
        self.assertFalse(any(event['kind'] == 'terminal' for event in self.store.events(self.identity)))

    def test_before_bind_seal_error_keeps_same_claim_unresolved(self):
        claim = self.claim()
        self.store.cancel(self.identity)
        self.observe.side_effect = lambda identity, claim_id: tasks.ExecutionObservation(claim_id, 'unknown', 0)
        self.store.seal_execution = MagicMock(side_effect=ConnectionError('uncertain seal acknowledgement'))
        with self.assertRaises(ConnectionError):
            self.store.reconcile(self.identity)
        self.assertEqual(self.store.active_task(self.identity.owner)['status'], 'stopping')
        self.assertEqual(self.store._owned(self.identity)['claim_id'], claim.claim_id)
        self.assertIsNone(self.store.claim(self.identity, self.store.job_id(self.identity)))

    def test_before_bind_lost_seal_ack_recovers_from_persisted_proof_without_resealing(self):
        claim = self.claim()
        self.store.cancel(self.identity)
        unknown = tasks.ExecutionObservation(claim.claim_id, 'unknown', 0)
        sealed = tasks.ExecutionObservation(claim.claim_id, 'never_started_and_sealed', 0, None, False, True)
        self.observe.side_effect = None
        self.observe.return_value = unknown
        def lose_reply(*args):
            self.observe.return_value = sealed  # Synthetic fixed supervisor ledger.
            raise ConnectionError('reply lost after durable seal')
        seal = self.store.seal_execution = MagicMock(side_effect=lose_reply)
        with self.assertRaises(ConnectionError):
            self.store.reconcile(self.identity)
        reopened = tasks.BusinessTaskStore(self.directory, self.identity.site, authorize=self.authorize,
                          observe_execution=self.observe, observe_queue=self.queue, seal_execution=seal)
        self.assertEqual(reopened.reconcile(self.identity), 'cancelled')
        seal.assert_called_once_with(self.identity, claim.claim_id)

    def test_before_bind_sealed_observation_without_cancel_cannot_reconcile_task(self):
        claim = self.claim()
        self.observe.side_effect = None
        self.observe.return_value = tasks.ExecutionObservation(claim.claim_id, 'never_started_and_sealed',
                                                              0, None, False, True)
        seal = self.store.seal_execution = MagicMock()
        self.assertEqual(self.store.reconcile(self.identity), 'running')
        self.assertEqual(self.store.active_task(self.identity.owner)['status'], 'running')
        seal.assert_not_called()
        self.assertFalse(any(event['kind'] == 'terminal' for event in self.store.events(self.identity)))

    def test_original_worker_finish_permanent_seal_only_fails_or_cancels(self):
        for cancelled, expected in ((False, 'failed'), (True, 'cancelled')):
            identity = self.create()
            claim = self.claim(identity)
            self.message(claim, 'Public text alone is not completed execution')
            if cancelled:
                self.store.cancel(identity)
            self.observe.side_effect = None
            self.observe.return_value = tasks.ExecutionObservation(claim.claim_id, 'never_started_and_sealed',
                                                                  0, None, False, True)
            with self.subTest(cancelled=cancelled):
                self.assertEqual(self.store.finish(claim), expected)
                self.assertEqual(self.store.events(identity)[-1]['status'], expected)
                self.assertIsNone(self.store.claim(identity, self.store.job_id(identity)))

    def test_original_worker_finish_seal_still_requires_private_worker_capability(self):
        claim = self.claim()
        self.observe.side_effect = None
        self.observe.return_value = tasks.ExecutionObservation(claim.claim_id, 'never_started_and_sealed',
                                                              0, None, False, True)
        self.observe.reset_mock()
        for bad in (replace(claim, token='x' * 43), replace(claim, claim_id=str(uuid.uuid4())),
                    replace(claim, identity=replace(self.identity, owner='other'))):
            with self.subTest(bad=bad.claim_id), self.assertRaises(PermissionError):
                self.store.finish(bad)
        self.observe.assert_not_called()
        self.assertEqual(self.store._owned(self.identity)['status'], 'running')

    def test_original_worker_finish_rejects_seal_claiming_turn_or_exit_success(self):
        claim = self.claim()
        proof = tasks.ExecutionObservation(claim.claim_id, 'never_started_and_sealed', 0, None, False, True)
        self.observe.side_effect = None
        for invalid in (replace(proof, exit_code=0), replace(proof, turn_completed=True),
                        replace(proof, lease_closed=False), replace(proof, active_writes=1)):
            self.observe.return_value = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.store.finish(claim)
        self.assertEqual(self.store._owned(self.identity)['status'], 'running')

    def test_before_bind_rejects_seal_with_exit_code_turn_writes_or_wrong_claim(self):
        claim = self.claim()
        self.store.cancel(self.identity)
        self.observe.side_effect = lambda identity, claim_id: tasks.ExecutionObservation(claim_id, 'unknown', 0)
        sealed = tasks.ExecutionObservation(claim.claim_id, 'never_started_and_sealed', 0, None, False, True)
        for proof in (replace(sealed, exit_code=0), replace(sealed, turn_completed=True),
                      replace(sealed, active_writes=1), replace(sealed, lease_closed=False),
                      replace(sealed, claim_id=str(uuid.uuid4())), {'state': 'never_started_and_sealed'}):
            with self.subTest(proof=proof), self.assertRaises(ValueError):
                self.store.seal_execution = MagicMock(return_value=proof)
                self.store.reconcile(self.identity)
        self.assertEqual(self.store._owned(self.identity)['status'], 'stopping')

    def test_before_bind_only_unknown_cancelled_claim_requests_seal(self):
        claim = self.claim()
        self.store.cancel(self.identity)
        seal = self.store.seal_execution = MagicMock()
        self.assertEqual(self.store.reconcile(self.identity), 'stopping')  # actual running observation
        seal.assert_not_called()
        self.observe.side_effect = None
        self.observe.return_value = tasks.ExecutionObservation(claim.claim_id, 'exited', 0, 0, False, True)
        self.assertEqual(self.store.reconcile(self.identity), 'cancelled')
        seal.assert_not_called()

    def test_before_bind_cancel_racing_unknown_observation_seals_only_on_next_pass(self):
        claim = self.claim()
        def observe(identity, claim_id):
            self.store.cancel(identity)
            return tasks.ExecutionObservation(claim_id, 'unknown', 0)
        self.observe.side_effect = observe
        seal = self.store.seal_execution = MagicMock(return_value=tasks.ExecutionObservation(
            claim.claim_id, 'never_started_and_sealed', 0, None, False, True))
        self.assertEqual(self.store.reconcile(self.identity), 'stopping')
        seal.assert_not_called()
        self.assertEqual(self.store.reconcile(self.identity), 'cancelled')
        seal.assert_called_once_with(self.identity, claim.claim_id)

    def test_before_bind_concurrent_idempotent_seals_emit_one_cancel_terminal(self):
        claim = self.claim()
        self.store.cancel(self.identity)
        self.observe.side_effect = lambda identity, claim_id: tasks.ExecutionObservation(claim_id, 'unknown', 0)
        gate = threading.Barrier(4)
        def seal(identity, claim_id):
            gate.wait(timeout=5)
            return tasks.ExecutionObservation(claim_id, 'never_started_and_sealed', 0, None, False, True)
        self.store.seal_execution = seal
        with ThreadPoolExecutor(max_workers=4) as pool:
            result = list(pool.map(lambda _: self.store.reconcile(self.identity), range(4)))
        self.assertEqual(result, ['cancelled'] * 4)
        self.assertEqual(sum(event['kind'] == 'terminal' for event in self.store.events(self.identity)), 1)

    def test_before_bind_scope_revocation_can_seal_without_exposing_private_data(self):
        claim = self.claim()
        self.message(claim, 'old class private fact')
        self.allowed = False
        self.observe.side_effect = lambda identity, claim_id: tasks.ExecutionObservation(claim_id, 'unknown', 0)
        self.store.seal_execution = MagicMock(return_value=tasks.ExecutionObservation(
            claim.claim_id, 'never_started_and_sealed', 0, None, False, True))
        self.assertIsNone(self.store.active_task(self.identity.owner))
        self.assertEqual(self.store._owned(self.identity)['status'], 'cancelled')
        with self.assertRaises(PermissionError):
            self.store.events(self.identity)

    def test_before_bind_other_owner_and_unclaimed_cancel_cannot_request_seal(self):
        self.claim()
        seal = self.store.seal_execution = MagicMock()
        with self.assertRaises(PermissionError):
            self.store.reconcile(replace(self.identity, owner='other'))
        another = self.create()
        self.store.cancel(another)
        self.assertEqual(self.store.reconcile(another), 'cancelled')
        seal.assert_not_called()

    def test_before_bind_seal_must_be_trusted_callable_not_request_data(self):
        for value in (True, {}, 'seal_before_start'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                tasks.BusinessTaskStore(self.directory, self.identity.site, authorize=self.authorize,
                    observe_execution=self.observe, observe_queue=self.queue, seal_execution=value)

    def test_event_replay_cursor_is_task_bound_ordered_and_exclusive(self):
        claim = self.claim()
        first = self.message(claim, 'first')
        second = self.message(claim, 'second', 'answer2')
        rows = self.store.events(self.identity, first)
        self.assertEqual([row['id'] for row in rows], [second])
        other = self.create()
        for cursor in (other.task_id + ':1', '1', '-1', self.identity.task_id + ':999',
                       self.identity.task_id + ':01', self.identity.task_id + ':1\ndata:x'):
            with self.subTest(cursor=cursor), self.assertRaises(ValueError):
                self.store.events(self.identity, cursor)

    def test_bounded_event_pagination_never_silently_drops_events(self):
        claim = self.claim()
        for number in range(12):
            self.message(claim, str(number), 'item' + str(number))
        first = self.store.events(self.identity, limit=5)
        second = self.store.events(self.identity, after=first[-1]['id'], limit=5)
        third = self.store.events(self.identity, after=second[-1]['id'], limit=5)
        self.assertEqual(len(first + second + third), 14)
        self.assertEqual(len({row['id'] for row in first + second + third}), 14)
        for limit in (0, 101, True, '2'):
            with self.assertRaises(ValueError):
                self.store.events(self.identity, limit=limit)

    def test_event_page_rechecks_scopes_registered_after_initial_authorization(self):
        claim = self.claim()
        allowed_groups = {'G1', 'G2'}
        self.authorize.side_effect = lambda identity, scopes: all(
            scope['kind'] != 'class' or scope['group'] in allowed_groups for scope in scopes)
        original_access = self.store._access
        changed = False
        def checked_access(identity):
            nonlocal changed
            row = original_access(identity)
            if not changed:
                changed = True
                self.store.register_authority(claim, {'kind': 'class', 'group': 'G2', 'actions': ['read']})
                self.message(claim, 'G2 private fact appended after initial check')
                allowed_groups.remove('G2')
            return row
        with patch.object(self.store, '_access', side_effect=checked_access):
            with self.assertRaises(PermissionError):
                self.store.events(self.identity)
        self.assertIn('G1', allowed_groups)
        self.assertEqual(self.store._owned(self.identity)['status'], 'stopping')

    def test_stream_disconnect_does_not_cancel_restart_or_finish(self):
        claim = self.claim()
        stream = self.store.stream(self.identity, authorize_viewer=lambda identity: True, pause=lambda _: None)
        next(stream)
        next(stream)
        stream.close()
        self.assertEqual(self.store.binding_state(claim)['status'], 'running')
        self.assertIsNone(self.store.take_dispatch(self.identity))
        self.observe.assert_not_called()

    def test_stream_revocation_between_yields_drops_already_fetched_private_events(self):
        claim = self.claim()
        self.message(claim, 'must not leak after revoke')
        stream = self.store.stream(self.identity, authorize_viewer=lambda identity: True, pause=lambda _: None)
        self.assertIn('connected', next(stream))
        self.assertIn('正在准备', next(stream))
        self.allowed = False
        self.assertEqual(next(stream), 'event: unavailable\ndata: {}\n\n')
        with self.assertRaises(StopIteration):
            next(stream)
        self.allowed = True
        self.assertEqual(self.store.task(self.identity)['status'], 'stopping')

    def test_stream_account_observation_failure_fails_closed(self):
        claim = self.claim()
        stream = self.store.stream(self.identity, authorize_viewer=lambda identity: True, pause=lambda _: None)
        next(stream)
        self.authorize.side_effect = RuntimeError('authority store unavailable')
        self.assertEqual(next(stream), 'event: unavailable\ndata: {}\n\n')
        self.authorize.side_effect = lambda identity, scopes: True
        self.assertEqual(self.store.binding_state(claim)['status'], 'stopping')

    def test_stream_reconnect_after_terminal_cursor_closes_without_reexecuting(self):
        claim = self.claim()
        self.message(claim)
        self.exited(claim)
        self.store.finish(claim)
        cursor = self.store.events(self.identity)[-1]['id']
        frames = list(self.store.stream(self.identity, cursor, authorize_viewer=lambda identity: True, pause=lambda _: None))
        self.assertEqual(frames[-1], 'event: closed\ndata: {}\n\n')
        self.assertEqual(len(frames), 2)
        self.assertIsNone(self.store.claim(self.identity, self.store.job_id(self.identity)))

    def test_stream_heartbeat_has_no_job_execution_deadline(self):
        claim = self.claim()
        cursor = self.store.events(self.identity)[-1]['id']
        pause = MagicMock()
        stream = self.store.stream(self.identity, cursor, authorize_viewer=lambda identity: True, pause=pause, poll_seconds=.01)
        next(stream)
        for _ in range(3):
            self.assertEqual(next(stream), ': heartbeat\n\n')
        stream.close()
        self.assertEqual(self.store.binding_state(claim)['status'], 'running')
        self.observe.assert_not_called()

    def test_history_is_owner_filtered_rechecked_and_has_no_worker_capabilities(self):
        other = self.create(owner='other@example.invalid')
        newer = self.create()
        self.claim(newer)
        page = self.store.history(self.identity.owner, limit=1)
        self.assertEqual([row['task_id'] for row in page['tasks']], [newer.task_id])
        self.assertEqual(page['next_before'], newer.task_id)
        second = self.store.history(self.identity.owner, before=page['next_before'], limit=1)
        self.assertEqual([row['task_id'] for row in second['tasks']], [self.identity.task_id])
        self.assertNotIn('worker', str(page))
        with self.assertRaises(PermissionError):
            self.store.history(self.identity.owner, before=other.task_id)
        self.allowed = False
        with self.assertRaises(PermissionError):
            self.store.history(self.identity.owner)

    def test_context_view_scope_is_registered_durably_and_initial_scopes_are_checked(self):
        scope = {'kind': 'class', 'group': 'G1', 'actions': ['read']}
        result = self.store.create(self.identity.owner, str(uuid.uuid4()), '查看本班',
                    {'selection': {'view': 'classroom_day', 'group': 'G1'}}, authority_scopes=[scope])
        self.assertIn(scope, self.store.required_scopes(result['identity']))
        self.assertIn({'kind': 'view', 'selection': {'view': 'classroom_day', 'group': 'G1'}},
                      self.store.required_scopes(result['identity']))
        self.allowed = False
        with self.assertRaises(PermissionError):
            self.store.create(self.identity.owner, str(uuid.uuid4()), '请求', authority_scopes=[scope])

    def test_lost_g1_scope_while_g2_remains_stops_old_text_and_tool_receipt_access(self):
        allowed_groups = {'G1', 'G2'}
        self.authorize.side_effect = lambda identity, scopes: all(
            item['kind'] != 'class' or item['group'] in allowed_groups for item in scopes)
        claim = self.claim()
        self.store.register_authority(claim, {'kind': 'class', 'group': 'G1', 'actions': ['read']})
        self.message(claim, 'G1 previously authorized pupil fact')
        stream = self.store.stream(self.identity, authorize_viewer=lambda identity: True, pause=lambda _: None)
        next(stream)
        next(stream)
        allowed_groups.remove('G1')
        self.assertEqual(next(stream), 'event: unavailable\ndata: {}\n\n')
        self.assertIn('G2', allowed_groups)
        for read in (lambda: self.store.events(self.identity), lambda: self.store.history(self.identity.owner),
                     lambda: self.store.binding_state(claim)):
            with self.assertRaises(PermissionError):
                read()
        self.assertEqual(self.store._owned(self.identity)['status'], 'stopping')

    def test_failed_scope_registration_never_grants_access_or_delivers_its_data(self):
        claim = self.claim()
        self.authorize.side_effect = lambda identity, scopes: not any(scope.get('group') == 'FOREIGN' for scope in scopes)
        delivered = []
        def trusted_adapter():
            self.store.register_authority(claim, {'kind': 'class', 'group': 'FOREIGN', 'actions': ['read']})
            delivered.append('private row')
        with self.assertRaises(PermissionError):
            trusted_adapter()
        self.assertEqual(delivered, [])
        self.assertEqual(self.store.required_scopes(self.identity), [])
        self.assertEqual(self.store.task(self.identity)['status'], 'running')

    def test_scope_registration_is_worker_only_idempotent_and_cannot_clear_prior_scope(self):
        claim = self.claim()
        scope = {'kind': 'document', 'doctype': 'Student', 'document': 'S1', 'actions': ['read']}
        self.store.register_authority(claim, scope)
        self.store.register_authority(claim, scope)
        self.assertEqual(self.store.required_scopes(self.identity), [scope])
        for bad in (replace(claim, token='x' * 43), None):
            with self.assertRaises(PermissionError):
                self.store.register_authority(bad, {'kind': 'capability', 'name': 'future_app.read'})
        for descriptor in ({'kind': 'sql', 'sql': 'select'}, {'kind': 'class', 'group': 'G1', 'actions': ['read'], 'actor': 'Administrator'},
                           {'kind': 'document', 'doctype': 'Student', 'document': 'S2', 'actions': ['ignore_permissions']}):
            with self.assertRaises(ValueError):
                self.store.register_authority(claim, descriptor)
        self.store.cancel(self.identity)
        with self.assertRaises(PermissionError):
            self.store.register_authority(claim, {'kind': 'capability', 'name': 'future_app.read'})

    def test_batch_authorities_canonical_dedup_preserves_old_scopes_and_single_api(self):
        claim = self.claim()
        original = {'kind': 'class', 'group': 'G1', 'actions': ['read']}
        self.assertEqual(self.store.register_authority(claim, original), original)
        incoming = {'kind': 'document', 'doctype': 'Student', 'document': 'S1', 'actions': ['write', 'read']}
        canonical = {**incoming, 'actions': ['read', 'write']}
        self.assertEqual(self.store.register_authorities(claim, [incoming, canonical, original]), (canonical, original))
        self.assertEqual(len(self.store.required_scopes(self.identity)), 2)
        self.assertIn(original, self.store.required_scopes(self.identity))
        self.assertEqual(self.store.register_authorities(claim, ()), ())
        self.assertEqual(len(self.store.required_scopes(self.identity)), 2)

    def test_batch_authorities_validate_entire_finite_input_before_any_insert(self):
        claim = self.claim()
        valid = {'kind': 'class', 'group': 'G1', 'actions': ['read']}
        for descriptors in (None, {}, 'invalid', iter([valid]), [valid] * (tasks.MAX_SCOPES + 1),
                            [valid, {'kind': 'sql', 'sql': 'select'}]):
            with self.subTest(batch_type=type(descriptors)), self.assertRaises(ValueError):
                self.store.register_authorities(claim, descriptors)
            self.assertEqual(self.store.required_scopes(self.identity), [])

    def test_batch_authorities_require_bound_worker_even_when_empty(self):
        claim = self.claim()
        for bad in (None, replace(claim, token='x' * 43),
                    replace(claim, identity=replace(self.identity, owner='other@example.invalid'))):
            with self.subTest(claim_type=type(bad)), self.assertRaises(PermissionError):
                self.store.register_authorities(bad, ())
        self.store.cancel(self.identity)
        with self.assertRaises(PermissionError):
            self.store.register_authorities(claim, ())

    def test_batch_authorities_check_union_without_per_descriptor_authorizer_calls(self):
        claim = self.claim()
        descriptors = tuple({'kind': 'document', 'doctype': 'Student', 'document': 'S' + str(i), 'actions': ['read']}
                            for i in range(62))
        self.authorize.reset_mock()
        self.assertEqual(self.store.register_authorities(claim, descriptors), descriptors)
        self.assertEqual(self.authorize.call_count, 3)
        self.assertEqual([len(call.args[1]) for call in self.authorize.call_args_list], [0, 62, 62])

    def test_batch_denied_member_does_not_insert_partial_set_or_release_data(self):
        claim = self.claim()
        self.authorize.side_effect = lambda identity, scopes: not any(scope.get('group') == 'DENIED' for scope in scopes)
        batch = tuple({'kind': 'class', 'group': group, 'actions': ['read']} for group in ('G1', 'DENIED', 'G2'))
        delivered = []
        with self.assertRaises(PermissionError):
            self.store.register_authorities(claim, batch)
            delivered.append('private result')
        self.assertEqual(delivered, [])
        self.assertEqual(self.store.required_scopes(self.identity), [])

    def test_batch_rechecks_old_scope_revocation_without_inserting_new_scope(self):
        claim = self.claim()
        original = {'kind': 'class', 'group': 'G1', 'actions': ['read']}
        self.store.register_authority(claim, original)
        self.authorize.side_effect = lambda identity, scopes: not any(scope.get('group') == 'G1' for scope in scopes)
        with self.assertRaises(PermissionError):
            self.store.register_authorities(claim, ({'kind': 'class', 'group': 'G2', 'actions': ['read']},))
        self.assertEqual(self.store.required_scopes(self.identity), [original])
        self.assertEqual(self.store._owned(self.identity)['status'], 'stopping')

    def test_batch_post_commit_revocation_stops_task_and_never_releases_result(self):
        claim = self.claim()
        batch = tuple({'kind': 'class', 'group': group, 'actions': ['read']} for group in ('G1', 'G2'))
        checks = 0
        def authorize(identity, scopes):
            nonlocal checks
            checks += 1
            return checks < 3
        self.authorize.side_effect = authorize
        delivered = []
        with self.assertRaises(PermissionError):
            self.store.register_authorities(claim, batch)
            delivered.append('private result')
        self.assertEqual(delivered, [])
        self.assertEqual(len(self.store.required_scopes(self.identity)), 2)
        self.assertEqual(self.store._owned(self.identity)['status'], 'stopping')

    def test_batch_cancel_during_proposed_authorization_prevents_all_inserts(self):
        claim = self.claim()
        def authorize(identity, scopes):
            if scopes:
                self.store.revoke(identity)
            return True
        self.authorize.side_effect = authorize
        with self.assertRaises(PermissionError):
            self.store.register_authorities(claim, ({'kind': 'class', 'group': 'G1', 'actions': ['read']},))
        self.assertEqual(self.store.required_scopes(self.identity), [])
        self.assertEqual(self.store._owned(self.identity)['status'], 'stopping')

    def test_batch_cancel_during_post_commit_authorization_never_returns_success(self):
        claim = self.claim()
        checks = 0
        def authorize(identity, scopes):
            nonlocal checks
            checks += 1
            if checks == 3:
                self.store.revoke(identity)
            return True
        self.authorize.side_effect = authorize
        with self.assertRaises(PermissionError):
            self.store.register_authorities(claim, ({'kind': 'class', 'group': 'G1', 'actions': ['read']},))
        self.assertEqual(len(self.store.required_scopes(self.identity)), 1)
        self.assertEqual(self.store._owned(self.identity)['status'], 'stopping')

    def test_batch_sql_failure_rolls_back_every_insert_and_never_releases_result(self):
        claim = self.claim()
        with self.store._transaction() as db:
            db.execute("CREATE TRIGGER review_fail_batch BEFORE INSERT ON authorities "
                       "WHEN NEW.descriptor LIKE '%FAILINSERT%' BEGIN SELECT RAISE(ABORT, 'test insert failure'); END")
        batch = tuple({'kind': 'document', 'doctype': 'Student', 'document': name, 'actions': ['read']}
                      for name in ('S1', 'FAILINSERT', 'S2'))
        delivered = []
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.register_authorities(claim, batch)
            delivered.append('private result')
        self.assertEqual(delivered, [])
        self.assertEqual(self.store.required_scopes(self.identity), [])
        self.assertEqual(self.store.task(self.identity)['status'], 'running')

    def test_concurrent_authority_batches_atomically_preserve_both_unions(self):
        claim = self.claim()
        barrier, local = threading.Barrier(2), threading.local()
        batches = [tuple({'kind': 'class', 'group': prefix + str(i), 'actions': ['read']} for i in range(2))
                   for prefix in ('A', 'B')]
        def authorize(identity, scopes):
            if len(scopes) == 2 and not getattr(local, 'checked', False):
                local.checked = True
                barrier.wait(timeout=5)
            return True
        self.authorize.side_effect = authorize
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda batch: self.store.register_authorities(claim, batch), batches))
        self.assertEqual(results, batches)
        self.assertEqual(len(self.store.required_scopes(self.identity)), 4)

    def test_concurrent_authority_batches_cannot_exceed_union_limit(self):
        claim = self.claim()
        barrier, local = threading.Barrier(2), threading.local()
        batches = [tuple({'kind': 'class', 'group': prefix + str(i), 'actions': ['read']} for i in range(2))
                   for prefix in ('A', 'B')]
        def authorize(identity, scopes):
            if len(scopes) == 2 and not getattr(local, 'checked', False):
                local.checked = True
                barrier.wait(timeout=5)
            return True
        def register(batch):
            try:
                return self.store.register_authorities(claim, batch)
            except ValueError:
                return None
        self.authorize.side_effect = authorize
        with patch.object(tasks, 'MAX_SCOPES', 3), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(register, batches))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.store.required_scopes(self.identity)), 2)

    def test_viewer_session_expiry_stops_sse_but_does_not_cancel_background_task(self):
        claim = self.claim()
        allowed = [True]
        stream = self.store.stream(self.identity, authorize_viewer=lambda identity: allowed[0], pause=lambda _: None)
        next(stream)
        allowed[0] = False
        self.assertEqual(next(stream), 'event: unavailable\ndata: {}\n\n')
        self.assertEqual(self.store.binding_state(claim)['status'], 'running')
        self.assertEqual(self.store.binding_state(claim)['cancel_requested'], '0')
        with self.assertRaises(TypeError):
            self.store.stream(self.identity)

    def test_task_database_hardlink_is_rejected(self):
        alias = self.directory / 'external-copy'
        os.link(self.store.path, alias)
        with self.assertRaises(ValueError):
            tasks.BusinessTaskStore(self.directory, 'qa.localhost', authorize=self.authorize,
                          observe_execution=self.observe, observe_queue=self.queue)

    @unittest.skipUnless(os.name == 'posix', 'POSIX mode enforcement')
    def test_task_database_and_active_journal_are_private_and_unsafe_mode_rejected(self):
        self.assertEqual(stat.S_IMODE(self.store.path.stat().st_mode), 0o600)
        with self.store._transaction() as db:
            db.execute('UPDATE tasks SET updated=updated+1 WHERE task_id=?', (self.identity.task_id,))
            journal = Path(str(self.store.path) + '-journal')
            self.assertTrue(journal.exists())
            self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o600)
        self.store.path.chmod(0o644)
        with self.assertRaises(ValueError):
            tasks.BusinessTaskStore(self.directory, 'qa.localhost', authorize=self.authorize,
                          observe_execution=self.observe, observe_queue=self.queue)


if __name__ == '__main__':
    unittest.main()
