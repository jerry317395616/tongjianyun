"""Real durable task/write stores and worker wiring; no model/business DB."""
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import uuid

from tongjianyun.business_agent_execution import BusinessExecutionRuntime
from tongjianyun.business_agent_tasks import BusinessTaskStore, TaskIdentity, QueueObservation, ExecutionObservation
from tongjianyun.business_agent_transport import TaskProxy
from tongjianyun.business_agent_worker import BusinessWorker
from tongjianyun.business_agent_writes import BusinessWriteLedger, BusinessWrites
from tongjianyun.tests.test_business_agent_worker import FakeRuntime
from tongjianyun.tests.test_business_agent_writes import Transaction, attendance


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name).resolve()
        self.site = 'qa.localhost'
        self.identity = TaskIdentity(self.site, 'teacher@example.invalid', str(uuid.uuid4()))
        self.calls, self.proxies, self.readbacks, self.transactions = [], [], [], []
        self.native = FakeRuntime(self.calls)
        self.native.seal_before_start = lambda identity, claim_id: ExecutionObservation(
            claim_id, 'never_started_and_sealed', 0, None, False, True)
        self.ledger = BusinessWriteLedger(self.directory, self.site, authorize=lambda *_: True)
        self.runtime = BusinessExecutionRuntime(self.native, self.ledger)
        self.store = BusinessTaskStore(self.directory, self.site, authorize=lambda *_: True,
            observe_execution=self.runtime.observe, seal_execution=self.runtime.seal_before_start,
            observe_queue=lambda job: QueueObservation(job, 'present'))
        self.store.create(self.identity.owner, self.identity.task_id, '请保存本班出勤', {'day': '2026-09-24'})
        self.ticket = self.store.take_dispatch(self.identity)
        self.store.acknowledge_dispatch(self.ticket)
        self.transaction = Transaction()
        def factory(*_):
            self.transactions.append(self.transaction)
            return self.transaction
        def fresh_read(claim, tool, args):
            self.assertEqual(self.transaction.events[-1], 'close')
            self.readbacks.append(claim)
            self.store.register_authority(claim, {'kind': 'class', 'group': args['group'], 'actions': ['read']})
            return {'group': args['group'], 'day': args['day'], 'revision': 'b' * 64, 'counts': {'Present': 1}}
        def publish(claim, selection):
            self.store.register_authority(claim, {'kind': 'view', 'selection': selection})
            self.store.emit(claim, {'kind': 'view', 'version': 1, 'selection': selection, 'title': '更新后的业务'})
        self.writes = BusinessWrites(self.ledger, transaction_factory=factory,
                                     fresh_read=fresh_read, publish_view=publish)
        outer = self
        class Proxy:
            # Use the real host callback admission/drain implementation, without
            # a network listener so these concurrency tests run on Windows too.
            dispatch_tool = TaskProxy.dispatch_tool
            wait_for_tools = TaskProxy.wait_for_tools
            permitted = TaskProxy.permitted
            def __init__(self, directory, token, **kwargs):
                self.path = directory / 'proxy.sock'
                self.authorize, self.tool_handler = kwargs['authorize'], kwargs['tool_handler']
                self.closed = threading.Event()
                self._tools_condition, self._active_tools = threading.Condition(), 0
                outer.proxies.append(self)
            def start(self):
                outer.calls.append('proxy_start')
            def close(self):
                with self._tools_condition:
                    self.closed.set()
                    self._tools_condition.notify_all()
                outer.calls.append('proxy_close')
        self.proxy_factory = Proxy

    def worker(self, **kwargs):
        return BusinessWorker(self.store, self.runtime, read_attendance=lambda *_: None,
            model_key=lambda: 'unused-test-only', proxy_factory=self.proxy_factory,
            write_tools=self.writes, poll_seconds=0.01, **kwargs)

    def run_worker(self):
        return self.worker().run(self.identity, self.ticket.job_id)

    def call(self, call_id='save-one', args=None):
        return self.proxies[0].dispatch_tool('attendance_save', args or attendance(), call_id)

    def test_worker_commits_then_fresh_reads_and_publishes_without_second_approval(self):
        results = []
        self.native.first_poll = lambda: results.append(self.call())
        result = self.run_worker()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.transaction.events, ['begin', 'save', 'commit', 'close'])
        self.assertTrue(results[0]['committed'])
        self.assertTrue(results[0]['readback_available'])
        self.assertEqual(len(self.readbacks), 1)
        self.assertTrue(any(e['kind'] == 'view' for e in self.store.events(self.identity)))
        self.assertTrue(self.ledger.observe(self.identity, self.native.claim.claim_id).admission_closed)
        self.assertIn('attendance_save', self.native.inputs['prompt'].decode())
        self.assertIn('不额外要求通用审批', self.native.inputs['prompt'].decode())

    def test_duplicate_tool_delivery_does_not_save_twice_but_reads_current_state(self):
        results = []
        self.native.first_poll = lambda: results.extend([self.call(), self.call('different-call')])
        self.assertEqual(self.run_worker()['status'], 'completed')
        self.assertEqual(len(self.transactions), 1)
        self.assertEqual(len(self.readbacks), 2)
        self.assertTrue(results[1]['replayed'])

    def test_draft_gate_is_opened_before_native_bind_and_drained_before_exit_observation(self):
        calls = []
        proposals = SimpleNamespace(site=self.site,
            open_task=MagicMock(side_effect=lambda claim:calls.append('draft-open')),
            close_task=MagicMock(side_effect=lambda *args:calls.append('draft-drain') or True))
        runtime = BusinessExecutionRuntime(self.native, self.ledger, proposals=proposals)
        claim = self.store.claim(self.identity, self.ticket.job_id)
        runtime.bind(claim)
        self.assertEqual(calls, ['draft-open'])
        self.native.state, self.native.code = 'exited', 0
        self.ledger.close_task(self.identity, claim.claim_id)
        observation = runtime.observe(self.identity, claim.claim_id)
        self.assertEqual(observation.state, 'exited')
        self.assertEqual(calls, ['draft-open','draft-drain'])

    def test_busy_draft_database_never_becomes_verified_task_drainage(self):
        proposals = SimpleNamespace(site=self.site,open_task=MagicMock(),close_task=MagicMock(side_effect=OSError))
        runtime = BusinessExecutionRuntime(self.native,self.ledger,proposals=proposals)
        claim = self.store.claim(self.identity, self.ticket.job_id)
        runtime.bind(claim)
        self.native.state, self.native.code = 'exited',0
        self.ledger.close_task(self.identity,claim.claim_id)
        with self.assertRaises(OSError):
            runtime.observe(self.identity,claim.claim_id)
        with self.assertRaises(OSError):
            runtime.stop(claim)
        self.assertIn('stop', self.calls, 'Draft I/O failure must not leave native model running')

    def test_nonliteral_draft_drain_receipt_is_rejected(self):
        proposals = SimpleNamespace(site=self.site,open_task=MagicMock(),close_task=MagicMock(return_value=None))
        runtime = BusinessExecutionRuntime(self.native,self.ledger,proposals=proposals)
        claim = self.store.claim(self.identity,self.ticket.job_id)
        runtime.bind(claim)
        with self.assertRaises(ValueError):
            runtime.close_admission(claim)

    def test_unknown_commit_cannot_be_promoted_by_successful_model_turn(self):
        self.transaction.failure = 'commit'
        results = []
        self.native.first_poll = lambda: results.append(self.call())
        self.assertEqual(self.run_worker()['status'], 'failed')
        self.assertEqual(results[0]['status'], 'uncertain')
        self.assertIsNone(results[0]['committed'])
        self.assertEqual(self.readbacks, [])

    def test_unverified_connection_close_keeps_task_active_after_callbacks_return(self):
        self.transaction.close_result = False
        self.native.first_poll = self.call
        result = self.run_worker()
        self.assertEqual(result['status'], 'running')
        self.assertEqual(result['error'], 'host_write_drain_unverified')
        host = self.ledger.observe(self.identity, self.native.claim.claim_id)
        self.assertEqual(host.active_writes, 1)
        self.assertTrue(host.admission_closed)
        self.assertEqual(self.readbacks, [])
        self.assertNotIn('terminal', [event['kind'] for event in self.store.events(self.identity)])

    def test_cancellation_stops_native_before_waiting_for_live_transaction(self):
        entered, release, inspected = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def hook(stage):
            if stage == 'save':
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('Test callback did not drain')
        self.transaction.hook = hook
        def background():
            try:
                self.call()
            except PermissionError:
                pass
            except BaseException as error:
                errors.append(error)
        def first_poll():
            self.callback = threading.Thread(target=background)
            self.callback.start()
            self.assertTrue(entered.wait(3))
            self.store.cancel(self.identity)
            def release_after_stop():
                try:
                    for _ in range(300):
                        if 'stop' in self.calls:
                            break
                        inspected.wait(0.01)
                    self.assertIn('stop', self.calls)
                    self.assertEqual(self.store.task(self.identity)['status'], 'stopping')
                    self.assertFalse(self.proxies[0].wait_for_tools(0))
                    self.assertEqual(self.ledger.observe(self.identity, self.native.claim.claim_id).active_writes, 1)
                except BaseException as error:
                    errors.append(error)
                finally:
                    release.set()
            self.releaser = threading.Thread(target=release_after_stop)
            self.releaser.start()
        self.native.first_poll = first_poll
        result = self.run_worker()
        self.callback.join(3)
        self.releaser.join(3)
        self.assertFalse(self.callback.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(result['status'], 'cancelled')
        self.assertEqual(self.transaction.events, ['begin', 'save', 'rollback', 'close'])
        self.assertEqual(self.readbacks, [])

    def test_failed_native_stop_still_waits_for_live_host_callback_before_release(self):
        entered, release = threading.Event(), threading.Event()
        errors = []
        def hook(stage):
            if stage == 'save':
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('Callback did not drain')
            if stage == 'close' and 'close_runtime' in self.calls:
                errors.append('Native lease closed before callback drained')
        self.transaction.hook = hook
        def background():
            try:
                self.call()
            except PermissionError:
                pass
            except BaseException as error:
                errors.append(error)
        def stop(claim):
            self.calls.append('stop')
            release.set()
            raise RuntimeError('Native stop proof unavailable')
        self.native.stop = stop
        def first_poll():
            self.callback = threading.Thread(target=background)
            self.callback.start()
            self.assertTrue(entered.wait(3))
            self.store.cancel(self.identity)
        self.native.first_poll = first_poll
        self.assertEqual(self.run_worker()['status'], 'unresolved')
        self.callback.join(3)
        self.assertFalse(self.callback.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(self.transaction.events, ['begin', 'save', 'rollback', 'close'])
        self.assertIn('close_runtime', self.calls)
        self.assertEqual(self.store.task(self.identity)['status'], 'stopping')

    def test_bind_failure_closes_host_gate_even_when_native_binding_did_not_return(self):
        captured = []
        def broken_bind(claim):
            captured.append(claim)
            self.assertTrue(self.ledger.observe(claim.identity, claim.claim_id).registered)
            raise RuntimeError('Native bind acknowledgement lost')
        self.native.bind = broken_bind
        self.assertEqual(self.run_worker()['status'], 'unresolved')
        self.assertTrue(self.ledger.observe(self.identity, captured[0].claim_id).admission_closed)
        self.assertEqual(self.proxies, [])

    def test_write_worker_rejects_native_only_store_observer(self):
        self.store.observe_execution = self.native.observe
        with self.assertRaises(ValueError):
            self.worker()

    def test_write_worker_rejects_native_only_seal(self):
        self.store.seal_execution = self.native.seal_before_start
        with self.assertRaises(ValueError):
            self.worker()

    def test_fresh_web_seals_gate_but_does_not_clear_abandoned_host_write(self):
        claim = self.store.claim(self.identity, self.ticket.job_id)
        self.runtime.bind(claim)
        tx = Transaction(close=False)
        self.ledger.execute(claim, 'write', 'attendance_save', attendance(), transaction_factory=lambda *_: tx)
        reopened = BusinessWriteLedger(self.directory, self.site, authorize=lambda *_: True)
        native = MagicMock()
        native.observe.return_value = ExecutionObservation(claim.claim_id, 'exited', 0, 0, True, True)
        fresh = BusinessExecutionRuntime(native, reopened)
        self.store.observe_execution = fresh.observe
        self.assertEqual(self.store.reconcile(self.identity), 'running')
        self.assertEqual(fresh.observe(self.identity, claim.claim_id).active_writes, 1)
        self.assertTrue(reopened.observe(self.identity, claim.claim_id).admission_closed)

    def test_web_never_started_seal_prevents_delayed_host_admission(self):
        claim = self.store.claim(self.identity, self.ticket.job_id)
        self.store.cancel(self.identity)
        self.assertEqual(self.store.reconcile(self.identity), 'cancelled')
        with self.assertRaises(PermissionError):
            self.runtime.bind(claim)
        self.assertNotIn('bind', self.calls)

    def test_ledger_close_failure_still_stops_and_closes_native(self):
        claim = self.store.claim(self.identity, self.ticket.job_id)
        self.runtime.bind(claim)
        with patch.object(self.ledger, 'close_task', side_effect=OSError):
            with self.assertRaises(OSError):
                self.runtime.stop(claim)
            with self.assertRaises(OSError):
                self.runtime.close(claim)
        self.assertIn('stop', self.calls)
        self.assertIn('close_runtime', self.calls)

    def test_proxy_drain_requires_revoked_admission_and_no_active_callback(self):
        proxy = self.proxy_factory(self.directory, 'unused', authorize=lambda: True,
                                   tool_handler=lambda *_: 'result')
        self.assertFalse(proxy.wait_for_tools(0))
        self.assertEqual(proxy.dispatch_tool('tool', {}, 'one'), 'result')
        proxy.close()
        self.assertTrue(proxy.wait_for_tools(0))
        with self.assertRaises(PermissionError):
            proxy.dispatch_tool('tool', {}, 'two')

    def test_catalog_is_claim_bound_and_rechecks_before_return(self):
        catalog = MagicMock(return_value={'entries': [], 'has_more': False})
        results = []
        self.native.first_poll = lambda: results.append(self.proxies[0].dispatch_tool(
            'business_catalog_read', {'keyword': '采购'}, 'catalog-one'))
        # Does not require the in-development catalog module for this pure wiring test.
        with patch('tongjianyun.business_agent_worker.build_prompt', return_value=b'test tools'):
            self.assertEqual(self.worker(catalog_tools=catalog).run(self.identity, self.ticket.job_id)['status'], 'completed')
        self.assertEqual(catalog.call_args.args, (self.native.claim, 'business_catalog_read', {'keyword': '采购'}))
        self.assertEqual(results, [{'entries': [], 'has_more': False}])

    def test_native_permission_error_is_normalized_without_private_error_text(self):
        class NativePermissionError(Exception):
            pass
        catalog = MagicMock(side_effect=NativePermissionError('private user/database diagnostic'))
        def first_poll():
            with self.assertRaisesRegex(PermissionError, '^Business tool authority denied$'):
                self.proxies[0].dispatch_tool('business_catalog_read', {}, 'denied')
        self.native.first_poll = first_poll
        with patch.dict('sys.modules', {'frappe': SimpleNamespace(PermissionError=NativePermissionError)}), \
                patch('tongjianyun.business_agent_worker.build_prompt', return_value=b'test tools'):
            result = self.worker(catalog_tools=catalog).run(self.identity, self.ticket.job_id)
        self.assertEqual(result['status'], 'completed')
        self.assertNotIn('private user', str(self.store.events(self.identity)))


if __name__ == '__main__':
    unittest.main()
