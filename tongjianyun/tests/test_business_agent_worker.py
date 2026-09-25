"""No model/root/production. Real store+projector+orchestrator, simulated OS proof."""
from dataclasses import replace
import http.client
import importlib.util
import json
import os
from pathlib import Path
import socket
import stat
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
import uuid

from tongjianyun import business_agent_worker as worker
from tongjianyun.business_agent_tasks import BusinessTaskStore, TaskIdentity, QueueObservation, ExecutionObservation
from tongjianyun.business_agent_events import CodexEventProjector

HAS_FRAPPE = importlib.util.find_spec('frappe') is not None


def jsonl(*events):
    return b''.join(json.dumps(event, ensure_ascii=False).encode() + b'\n' for event in events)


def completed(text='本班 2 人，1 人已到园，1 人尚未登记。'):
    return jsonl({'type': 'thread.started', 'thread_id': 'native-thread'}, {'type': 'turn.started'},
                 {'type': 'item.completed', 'item': {'id': 'answer', 'type': 'agent_message', 'text': text}},
                 {'type': 'turn.completed'})


class FakeRuntime:
    def __init__(self, calls):
        self.calls = calls
        self.ready_value = True
        self.frames = [worker.RuntimeFrame(completed(), stdout_eof=True, state='exited')]
        self.state = 'unknown'
        self.code = None
        self.projection = None
        self.first_poll = None
        self.active_writes = 0

    def ready(self):
        return self.ready_value

    def bind(self, claim):
        self.calls.append('bind')
        self.claim = claim

    def start(self, claim, **kwargs):
        self.calls.append('start')
        self.inputs = kwargs
        self.state = 'running'

    def poll(self, claim):
        self.calls.append('poll')
        if self.first_poll:
            action, self.first_poll = self.first_poll, None
            action()
        frame = self.frames.pop(0)
        if frame.state == 'exited':
            self.state, self.code = 'exited', 0
        return frame

    def stop(self, claim):
        self.calls.append('stop')
        self.state, self.code = 'exited', -15

    def record_projection(self, claim, observation):
        self.calls.append('projected')
        self.projection = observation

    def observe(self, identity, claim_id):
        self.calls.append('observe')
        return ExecutionObservation(claim_id, self.state, self.active_writes, self.code,
                                    bool(self.projection and self.projection.turn_completed and self.projection.input_closed))

    def close(self, claim):
        self.calls.append('close_runtime')


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.site = 'qa.localhost'
        self.identity = TaskIdentity(self.site, 'teacher@example.invalid', str(uuid.uuid4()))
        self.calls = []
        self.allowed = True
        self.runtime = FakeRuntime(self.calls)
        self.store = BusinessTaskStore(self.temp.name, self.site,
            authorize=lambda identity, scopes: self.allowed,
            observe_execution=self.runtime.observe,
            observe_queue=lambda job: QueueObservation(job, 'present'))
        self.store.create(self.identity.owner, self.identity.task_id, '查看本班到园情况',
                          {'day': '2026-09-16', 'selection': {'view': 'classroom_day', 'group': 'G1', 'day': '2026-09-16'}})
        ticket = self.store.take_dispatch(self.identity)
        self.store.acknowledge_dispatch(ticket)
        self.job_id = ticket.job_id
        self.proxies = []
        outer = self
        class Proxy:
            def __init__(self, directory, token, **kwargs):
                self.directory, self.token = directory, token
                self.path = directory / 'proxy.sock'
                self.authorize = kwargs['authorize']
                self.handler = kwargs['tool_handler']
                self.model_key = kwargs['model_key']
                self.closed = False
                outer.proxies.append(self)
            def start(self):
                outer.calls.append('proxy_start')
                return self
            def close(self):
                outer.calls.append('proxy_close')
                self.closed = True
        self.proxy_factory = Proxy
        self.key = MagicMock(return_value='never-loaded-key')
        def read(claim, *, group, day):
            self.calls.append('read')
            # Stands in for the already tested native source-aware adapter.
            self.store.register_authorities(claim, [
                {'kind': 'class', 'group': group, 'actions': ['read']},
                {'kind': 'document', 'doctype': 'Student', 'document': 'S1', 'actions': ['read']},
            ])
            return {'group': group, 'day': day, 'revision': 'a' * 64, 'counts': {'Present': 1, 'Unknown': 1},
                    'students': [{'student': 'S1', 'student_name': 'Synthetic', 'status': 'Present', 'source': '考勤登记'}],
                    'attendance_write': False, 'scope': '本班'}
        self.read = MagicMock(side_effect=read)

    def make_worker(self, **kwargs):
        return worker.BusinessWorker(self.store, self.runtime, read_attendance=self.read,
                                     model_key=self.key, proxy_factory=self.proxy_factory, poll_seconds=0, **kwargs)

    def run_worker(self):
        return self.make_worker().run(self.identity, self.job_id)

    def public(self):
        return self.store.events(self.identity)

    def test_complete_requires_real_claim_projection_exit_and_store_observer(self):
        result = self.run_worker()
        self.assertEqual(result['status'], 'completed')
        self.assertFalse(result['automatic_retry_allowed'])
        self.assertEqual(self.calls.count('start'), 1)
        self.assertLess(self.calls.index('proxy_close'), self.calls.index('observe'))
        self.assertLess(self.calls.index('projected'), self.calls.index('observe'))
        self.assertTrue(self.runtime.projection.input_closed)
        self.key.assert_not_called()
        self.assertNotIn('claim_id', result)
        self.assertNotIn(self.runtime.claim.token, str(result))

    def test_duplicate_queue_delivery_never_restarts_or_resumes_model(self):
        self.run_worker()
        result = self.run_worker()
        self.assertFalse(result['started'])
        self.assertEqual(self.calls.count('bind'), 1)
        self.assertEqual(self.calls.count('start'), 1)

    def test_pipe_drain_after_process_exit_preserves_final_chunk(self):
        payload = completed()
        middle = len(payload) // 2
        self.runtime.frames = [worker.RuntimeFrame(payload[:middle], state='draining'),
                               worker.RuntimeFrame(payload[middle:], stdout_eof=True, state='exited')]
        self.assertEqual(self.run_worker()['status'], 'completed')
        self.assertEqual(self.calls.count('poll'), 2)
        self.assertNotIn('stop', self.calls)

    def test_no_total_runtime_deadline_or_empty_poll_retry(self):
        self.runtime.frames = [worker.RuntimeFrame()] * 10 + self.runtime.frames
        self.assertEqual(self.run_worker()['status'], 'completed')
        self.assertEqual(self.calls.count('poll'), 11)
        self.assertEqual(self.calls.count('start'), 1)

    def test_unavailable_runtime_refuses_before_claim(self):
        self.runtime.ready_value = False
        with self.assertRaises(worker.RuntimeUnavailable):
            self.run_worker()
        self.assertEqual(self.store.task(self.identity)['status'], 'queued')
        self.assertEqual(self.calls, [])

    @unittest.skipUnless(os.name == 'posix', 'POSIX root identity check')
    def test_root_business_worker_is_refused(self):
        with patch.object(os, 'geteuid', return_value=0):
            with self.assertRaises(PermissionError):
                self.run_worker()
        self.assertEqual(self.calls, [])

    def test_wrong_site_mode_job_or_forged_identity_never_launches(self):
        for identity, job in ((replace(self.identity, site='other.localhost'), self.job_id),
                              (replace(self.identity, mode='admin_project'), self.job_id),
                              (self.identity, 'wrong-job')):
            with self.assertRaises(PermissionError):
                self.make_worker().run(identity, job)
        self.assertEqual(self.calls, [])

    @unittest.skipUnless(HAS_FRAPPE, 'Original argument validator requires installed Frappe; exercised on native-bench')
    def test_classroom_read_registers_sources_before_view_and_result(self):
        delivered = []
        def tool():
            result = self.proxies[0].handler('classroom_read', {'group': 'G1', 'day': '2026-09-16'}, 'read-0001')
            registered = self.store.required_scopes(self.identity)
            self.assertIn({'kind': 'document', 'doctype': 'Student', 'document': 'S1', 'actions': ['read']}, registered)
            delivered.append(result)
        self.runtime.first_poll = tool
        self.assertEqual(self.run_worker()['status'], 'completed')
        self.assertEqual(len(delivered), 1)
        self.read.assert_called_once_with(self.runtime.claim, group='G1', day='2026-09-16')
        events = self.store.events(self.identity)
        self.assertTrue(any(event.get('kind') == 'view' for event in events))

    @unittest.skipUnless(os.name == 'posix' and HAS_FRAPPE, 'Real Unix TaskProxy and installed Frappe')
    def test_real_private_task_proxy_calls_worker_reader_without_model_credentials(self):
        self.proxy_factory = worker.TaskProxy
        delivered = []
        def tool():
            path, token = self.runtime.inputs['proxy_path'], self.runtime.inputs['token']
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            connection = http.client.HTTPConnection('localhost')
            connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            connection.sock.settimeout(3)
            connection.sock.connect(str(path))
            try:
                payload = json.dumps({'tool': 'classroom_read',
                    'arguments': {'group': 'G1', 'day': '2026-09-16'}, 'call_id': 'read-0001'})
                connection.request('POST', '/tools/call', body=payload, headers={
                    'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                delivered.append(json.loads(response.read())['result'])
            finally:
                connection.close()
        self.runtime.first_poll = tool
        self.assertEqual(self.run_worker()['status'], 'completed')
        self.assertEqual(delivered[0]['counts'], {'Present': 1, 'Unknown': 1})
        self.assertFalse(self.runtime.inputs['proxy_path'].exists())
        self.key.assert_not_called()
        self.assertTrue(any(event.get('kind') == 'view' for event in self.public()))

    @unittest.skipUnless(HAS_FRAPPE, 'Original argument validator requires installed Frappe; exercised on native-bench')
    def test_unintegrated_tools_and_identity_arguments_refused(self):
        def tools():
            for tool in ('attendance_save', 'meal_read', 'business_view', 'scene_bootstrap', 'shell', 'run_task'):
                with self.assertRaises(PermissionError):
                    self.proxies[0].handler(tool, {}, 'read-0001')
            with self.assertRaises(ValueError):
                self.proxies[0].handler('classroom_read', {'group': 'G1', 'day': '2026-09-16', 'owner': 'Administrator'}, 'read-0001')
        self.runtime.first_poll = tools
        self.assertEqual(self.run_worker()['status'], 'completed')
        self.read.assert_not_called()

    @unittest.skipUnless(HAS_FRAPPE, 'Original argument validator requires installed Frappe; exercised on native-bench')
    def test_tool_revocation_after_read_does_not_deliver_or_publish(self):
        def read(claim, **args):
            self.store.cancel(self.identity)
            return {'group': 'G1', 'day': '2026-09-16', 'students': [{'student_name': 'MUST NOT DELIVER'}]}
        self.read.side_effect = read
        def tool():
            with self.assertRaises(PermissionError):
                self.proxies[0].handler('classroom_read', {'group': 'G1', 'day': '2026-09-16'}, 'read-0001')
        self.runtime.first_poll = tool
        self.assertEqual(self.run_worker()['status'], 'cancelled')
        events = self.store.events(self.identity)
        self.assertNotIn('MUST NOT DELIVER', str(events))
        self.assertFalse(any(event.get('kind') == 'view' for event in events))

    @unittest.skipUnless(HAS_FRAPPE, 'Discovery adapter imports native Frappe permission contracts')
    def test_discovery_is_trusted_claim_bound_and_does_not_double_publish(self):
        def dispatch(claim, tool, args):
            self.assertEqual(claim, self.runtime.claim)
            self.store.register_authority(claim, {'kind':'class','group':'G1','actions':['read']})
            self.store.emit(claim, {'kind':'view','version':1,
                'selection':{'view':'class_students','group':'G1'},'title':'本班学生'})
            return {'page_count':1,'visible_class_count':None}
        adapter = MagicMock(side_effect=dispatch)
        def call():
            result = self.proxies[0].handler('class_students_read',{'group':'G1'},'read-0001')
            self.assertIsNone(result['visible_class_count'])
            with self.assertRaises(PermissionError):
                self.proxies[0].handler('business_view',{},'read-0002')
        self.runtime.first_poll = call
        result = self.make_worker(read_tools=adapter).run(self.identity,self.job_id)
        self.assertEqual(result['status'],'completed')
        self.assertEqual(adapter.call_count,1)
        self.assertIn('scene_bootstrap',self.runtime.inputs['prompt'].decode())
        self.assertEqual(sum(event['kind']=='view' for event in self.public()),1)
        self.read.assert_not_called()

    @unittest.skipUnless(HAS_FRAPPE, 'Discovery adapter imports native Frappe permission contracts')
    def test_discovery_rechecks_cancellation_before_releasing_result(self):
        def dispatch(claim, tool, args):
            self.store.cancel(self.identity)
            return {'groups':['MUST NOT DELIVER']}
        def call():
            with self.assertRaises(PermissionError):
                self.proxies[0].handler('scene_bootstrap',{'day':'2026-09-16'},'read-0001')
        self.runtime.first_poll = call
        result = self.make_worker(read_tools=dispatch).run(self.identity,self.job_id)
        self.assertEqual(result['status'],'cancelled')
        self.assertNotIn('MUST NOT DELIVER',str(self.public()))

    def test_discovery_is_not_advertised_without_a_trusted_adapter(self):
        self.run_worker()
        self.assertNotIn('scene_bootstrap',self.runtime.inputs['prompt'].decode())
        with self.assertRaises(ValueError):
            self.make_worker(read_tools='untrusted-method-name')

    def test_explicit_cancel_closes_proxy_before_stopping_exact_runtime(self):
        self.runtime.first_poll = lambda: self.store.cancel(self.identity)
        result = self.run_worker()
        self.assertEqual(result['status'], 'cancelled')
        self.assertLess(self.calls.index('proxy_close'), self.calls.index('stop'))
        self.assertFalse(self.proxies[0].authorize())

    def test_scope_revocation_stops_and_does_not_publish_old_buffer(self):
        self.runtime.first_poll = lambda: setattr(self, 'allowed', False)
        self.assertEqual(self.run_worker()['status'], 'cancelled')
        with self.assertRaises(PermissionError):
            self.store.events(self.identity)
        self.assertTrue(self.proxies[0].closed)

    def test_malformed_jsonl_is_not_restarted_or_stored_raw(self):
        self.runtime.frames = [worker.RuntimeFrame(b'{private broken stderr secret}\n')]
        self.assertEqual(self.run_worker()['status'], 'failed')
        self.assertEqual(self.calls.count('start'), 1)
        self.assertNotIn('private broken', str(self.store.events(self.identity)))

    def test_stage_output_is_projected_without_raw_command_reasoning_or_stderr(self):
        self.runtime.frames = [worker.RuntimeFrame(jsonl(
            {'type': 'thread.started', 'thread_id': 'thread'}, {'type': 'turn.started'},
            {'type': 'item.started', 'item': {'type': 'command_execution', 'id': 'tool', 'command': 'SECRET RAW COMMAND'}},
            {'type': 'item.completed', 'item': {'type': 'reasoning', 'id': 'private', 'text': 'PRIVATE REASONING'}},
            {'type': 'item.completed', 'item': {'type': 'command_execution', 'id': 'tool', 'aggregated_output': 'PRIVATE TOOL OUTPUT'}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'id': 'answer', 'text': '正在核对，结果已取得。'}},
            {'type': 'turn.completed'}), stderr_bytes=999, stdout_eof=True, state='exited')]
        self.assertEqual(self.run_worker()['status'], 'completed')
        public = str(self.store.events(self.identity))
        self.assertIn('执行操作', public)
        self.assertNotIn('PRIVATE', public)
        self.assertNotIn('SECRET RAW', public)

    def test_plain_claim_of_completion_does_not_replace_turn_evidence(self):
        self.runtime.frames = [worker.RuntimeFrame(jsonl(
            {'type': 'thread.started', 'thread_id': 'thread'}, {'type': 'turn.started'},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'id': 'a', 'text': '已全部完成'}}),
            stdout_eof=True, state='exited')]
        self.assertEqual(self.run_worker()['status'], 'failed')

    def test_unverified_cgroup_or_active_write_cannot_finish_successfully(self):
        self.runtime.active_writes = 1
        result = self.run_worker()
        self.assertEqual(result['status'], 'running')
        self.assertEqual(self.store.task(self.identity)['status'], 'running')
        self.assertFalse(result['automatic_retry_allowed'])

    def test_unknown_runtime_stops_and_leaves_unresolved_when_stop_cannot_prove_exit(self):
        self.runtime.frames = [worker.RuntimeFrame(state='unknown')]
        self.runtime.stop = MagicMock(side_effect=worker.RuntimeUnavailable('unknown'))
        result = self.run_worker()
        self.assertEqual(result['status'], 'unresolved')
        self.assertEqual(result['error'], 'execution_unverified')
        self.assertNotIn('unknown', result['error'])

    def test_bind_crash_after_claim_cannot_be_reclaimed(self):
        self.runtime.bind = MagicMock(side_effect=RuntimeError('private details'))
        result = self.run_worker()
        self.assertEqual(result['status'], 'unresolved')
        self.assertFalse(self.run_worker()['started'])
        self.assertNotIn('private details', str(result))
        self.assertEqual(self.proxies, [])

    def test_runtime_directory_is_never_reused(self):
        directory = Path(self.temp.name) / self.identity.task_id
        directory.mkdir(mode=0o700)
        result = self.run_worker()
        self.assertNotEqual(result['status'], 'completed')
        self.assertNotIn('start', self.calls)
        self.assertTrue(directory.exists())

    def test_proxy_close_failure_cannot_preserve_successful_projection(self):
        def close_failure():
            self.proxies[0].close = MagicMock(side_effect=RuntimeError('private close details'))
        self.runtime.first_poll = close_failure
        result = self.run_worker()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['error'], 'cleanup_unverified')
        self.assertFalse(self.runtime.projection.turn_completed)
        self.assertNotIn('private close', str(result))

    def test_proxy_start_failure_still_closes_constructed_socket(self):
        with patch.object(self.proxy_factory, 'start', side_effect=RuntimeError('start failed')):
            result = self.run_worker()
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(self.proxies[0].closed)
        self.assertLess(self.calls.index('proxy_close'), self.calls.index('stop'))
        self.assertNotIn('start', self.calls)

    def test_oversized_or_untyped_runtime_frame_is_never_published(self):
        self.runtime.frames = [worker.RuntimeFrame(b'x' * (worker.MAX_CHUNK + 1))]
        result = self.run_worker()
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('xxx', str(self.public()))

    def test_model_or_worker_capabilities_are_redacted_from_output(self):
        def leak():
            self.runtime.frames = [worker.RuntimeFrame(completed(self.proxies[0].token + ' ' + self.runtime.claim.token), stdout_eof=True, state='exited')]
        self.runtime.first_poll = leak
        self.run_worker()
        public = str(self.store.events(self.identity))
        self.assertNotIn(self.proxies[0].token, public)
        self.assertNotIn(self.runtime.claim.token, public)


class LauncherClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.site = 'qa.localhost'
        self.identity = TaskIdentity(self.site, 'teacher@example.invalid', str(uuid.uuid4()))
        from tongjianyun.business_agent_tasks import WorkerClaim
        self.claim = WorkerClaim(self.identity, str(uuid.uuid4()), 'c' * 43)
        self.runtime = worker.UnixLauncherRuntime(site=self.site, sites_path=self.temp.name)
        self.channel = MagicMock()
        self.factory = patch.object(worker, '_ControlChannel', return_value=self.channel)
        self.factory.start()
        self.addCleanup(self.factory.stop)

    def ready_reply(self):
        return {'ok': True, 'version': 1, 'profile': worker.LAUNCHER_PROFILE,
                'native_revision': worker.NATIVE_REVISION, 'ready': True}

    def proof(self, **changes):
        return {'ok': True, 'unit': worker._unit(self.identity.task_id), 'claim_id': self.claim.claim_id,
                'state': 'exited', 'exit_code': 0, 'cgroup_empty': True, 'stdout_eof': True,
                'lease_closed': False, **changes}

    def bind(self):
        self.channel.call.return_value = {'ok': True, 'unit': worker._unit(self.identity.task_id), 'bound': True}
        self.runtime.bind(self.claim)

    def test_real_handshake_required_no_daemon_means_false(self):
        self.channel.call.side_effect = FileNotFoundError()
        self.assertFalse(self.runtime.ready())
        self.channel.call.side_effect = None
        self.channel.call.return_value = self.ready_reply()
        self.assertTrue(self.runtime.ready())
        self.channel.call.return_value = {**self.ready_reply(), 'native_revision': 'wrong'}
        self.assertFalse(self.runtime.ready())

    def test_bind_is_exact_and_not_reusable(self):
        self.bind()
        with self.assertRaises(PermissionError):
            self.runtime.bind(self.claim)
        with self.assertRaises(PermissionError):
            self.runtime.stop(replace(self.claim, claim_id=str(uuid.uuid4())))

    def test_bind_refuses_wrong_unit_and_closes_channel(self):
        self.channel.call.return_value = {'ok': True, 'unit': 'ssh.service', 'bound': True}
        with self.assertRaises(worker.RuntimeUnavailable):
            self.runtime.bind(self.claim)
        self.channel.close.assert_called_once()

    def test_observer_combines_native_drain_and_local_parsed_projection(self):
        self.bind()
        projector = CodexEventProjector(lambda _: None)
        projector.feed(completed())
        self.runtime.record_projection(self.claim, projector.finish_input())
        self.channel.call.return_value = self.proof()
        observed = self.runtime.observe(self.identity, self.claim.claim_id)
        self.assertEqual(observed.state, 'exited')
        self.assertTrue(observed.turn_completed)
        self.assertFalse(observed.lease_closed)
        self.channel.call.return_value = self.proof(cgroup_empty=False)
        self.assertEqual(self.runtime.observe(self.identity, self.claim.claim_id).state, 'unknown')
        self.channel.call.return_value = self.proof(stdout_eof=False)
        self.assertEqual(self.runtime.observe(self.identity, self.claim.claim_id).state, 'unknown')

    def test_new_runtime_after_worker_crash_cannot_infer_successful_turn(self):
        self.channel.call.return_value = self.proof(lease_closed=True)
        observation = self.runtime.observe(self.identity, self.claim.claim_id)
        self.assertEqual(observation.state, 'exited')
        self.assertFalse(observation.turn_completed)
        self.assertTrue(observation.lease_closed)

    def test_model_boolean_is_not_projection_evidence(self):
        self.bind()
        with self.assertRaises(ValueError):
            self.runtime.record_projection(self.claim, {'turn_completed': True})

    def test_native_proof_wrong_task_claim_or_schema_fails_closed(self):
        for proof in (self.proof(unit='other.service'), self.proof(claim_id=str(uuid.uuid4())),
                      self.proof(cgroup_empty=1), self.proof(exit_code=False), self.proof(extra='secret'),
                      self.proof(lease_closed=1)):
            self.channel.call.return_value = proof
            self.assertEqual(self.runtime.observe(self.identity, self.claim.claim_id).state, 'unknown')

    def test_stop_requires_actual_exit_and_cgroup_drain(self):
        self.bind()
        self.channel.call.return_value = self.proof(state='running', cgroup_empty=False, exit_code=None)
        with self.assertRaises(worker.RuntimeUnavailable):
            self.runtime.stop(self.claim)
        self.channel.call.return_value = self.proof(exit_code=-15)
        self.runtime.stop(self.claim)

    def test_seal_is_explicit_permanent_never_started_proof_not_exit(self):
        self.channel.call.return_value = self.proof(state='never_started_and_sealed',
                                                   exit_code=None, lease_closed=True)
        observed = self.runtime.seal_before_start(self.identity, self.claim.claim_id)
        self.assertEqual(observed.state, 'never_started_and_sealed')
        self.assertIsNone(observed.exit_code)
        self.assertFalse(observed.turn_completed)
        self.assertTrue(observed.lease_closed)
        self.assertEqual(self.channel.call.call_args.args[0]['op'], 'seal_before_start')
        self.channel.close.assert_called_once()
        self.assertEqual(self.runtime._bound, {})
        self.assertEqual(self.runtime._started, set())

    def test_seal_requires_all_flags_exact_task_and_no_exit_code(self):
        base = self.proof(state='never_started_and_sealed', exit_code=None, lease_closed=True)
        for change in ({'exit_code': 0}, {'stdout_eof': False}, {'cgroup_empty': False},
                       {'lease_closed': False}, {'lease_closed': 1},
                       {'claim_id': str(uuid.uuid4())}, {'unit': 'another.service'}):
            with self.subTest(change=change):
                self.channel.call.return_value = {**base, **change}
                self.assertEqual(self.runtime.seal_before_start(self.identity, self.claim.claim_id).state, 'unknown')

    def test_seal_never_interprets_missing_or_active_runtime_as_cancelled(self):
        for state in ('unknown', 'running'):
            self.channel.call.return_value = self.proof(state=state, exit_code=None,
                                                       cgroup_empty=False, stdout_eof=False)
            self.assertEqual(self.runtime.seal_before_start(self.identity, self.claim.claim_id).state, state)
        self.channel.call.side_effect = ConnectionError('lost acknowledgement')
        self.assertEqual(self.runtime.seal_before_start(self.identity, self.claim.claim_id).state, 'unknown')

    def test_poll_is_bounded_binary_stdout_not_raw_stderr(self):
        import base64
        self.bind()
        self.channel.call.return_value = {'ok': True, 'stdout': base64.b64encode(b'{}\n').decode(),
            'stderr_bytes': 10, 'execution': self.proof()}
        frame = self.runtime.poll(self.claim)
        self.assertEqual(frame.stdout, b'{}\n')
        self.assertEqual(frame.stderr_bytes, 10)
        self.channel.call.return_value['stderr'] = 'private raw error'
        with self.assertRaises(worker.RuntimeUnavailable):
            self.runtime.poll(self.claim)

    def test_native_process_exit_waits_for_pipe_delivery_before_terminal(self):
        self.bind()
        self.channel.call.return_value = {'ok': True, 'stdout': 'e30K',
            'stderr_bytes': 0, 'execution': self.proof(stdout_eof=False)}
        frame = self.runtime.poll(self.claim)
        self.assertEqual(frame.state, 'draining')
        self.assertFalse(frame.stdout_eof)
        self.channel.call.return_value = self.proof(stdout_eof=False)
        self.assertEqual(self.runtime.observe(self.identity, self.claim.claim_id).state, 'unknown')

    def test_start_reservation_precedes_rpc_failure_no_blind_retry(self):
        self.bind()
        proxy = Path(self.temp.name) / self.site / 'private/business-codex/tasks' / self.identity.task_id / 'proxy.sock'
        info = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=1000)
        with patch.object(worker, 'private_directory'), patch.object(Path, 'lstat', return_value=info), \
                patch.object(worker.os, 'geteuid', return_value=1000, create=True):
            self.channel.call.side_effect = ConnectionError('lost reply')
            with self.assertRaises(ConnectionError):
                self.runtime.start(self.claim, prompt=b'hello', proxy_path=proxy, token='t' * 43)
            with self.assertRaises(PermissionError):
                self.runtime.start(self.claim, prompt=b'hello', proxy_path=proxy, token='t' * 43)

    def test_start_cannot_supply_host_proxy_arbitrary_command_or_other_site(self):
        self.bind()
        with self.assertRaises(ValueError):
            self.runtime.start(self.claim, prompt=b'hello', proxy_path=Path('/run/docker.sock'), token='t' * 43)
        with self.assertRaises(TypeError):
            self.runtime.start(self.claim, prompt=b'hello', proxy_path=Path('/tmp/no'), token='t' * 43, command='sudo admin')
        with self.assertRaises(PermissionError):
            self.runtime.bind(replace(self.claim, identity=replace(self.identity, site='other.localhost')))

    def test_release_requires_cleanup_receipt_and_always_drops_lease(self):
        self.bind()
        self.channel.call.return_value = {'ok': True, 'unit': worker._unit(self.identity.task_id), 'cleaned': False}
        with self.assertRaises(worker.RuntimeUnavailable):
            self.runtime.close(self.claim)
        self.channel.close.assert_called_once()
        with self.assertRaises(PermissionError):
            self.runtime.stop(self.claim)


class ControlTransportTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix', 'Linux authenticated control transport')
    def test_socket_owner_and_peer_uid_are_required(self):
        safe_socket = SimpleNamespace(st_mode=stat.S_IFSOCK | 0o660, st_uid=0)
        safe_dir = SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
        fake = MagicMock()
        fake.getsockopt.return_value = struct.pack('3i', 123, 1000, 1000)
        with patch.object(Path, 'lstat', side_effect=lambda p: safe_socket if p == worker.LAUNCHER_SOCKET else safe_dir, autospec=True), \
                patch.object(Path, 'stat', return_value=safe_socket), patch.object(socket, 'socket', return_value=fake):
            with self.assertRaises(PermissionError):
                worker._ControlChannel()
        fake.close.assert_called_once()

    def test_control_frame_rejects_duplicate_keys_and_oversized_reply(self):
        for raw in (b'{"ok":true,"ok":true}',):
            channel = worker._ControlChannel.__new__(worker._ControlChannel)
            channel.socket = MagicMock()
            channel.lock = __import__('threading').Lock()
            channel.socket.recv.side_effect = [struct.pack('!I', len(raw)), raw]
            with self.assertRaises(ValueError):
                channel.call({'op': 'ready'})
        channel.socket.recv.side_effect = [struct.pack('!I', worker.MAX_CONTROL + 1)]
        with self.assertRaises(worker.RuntimeUnavailable):
            channel.call({'op': 'ready'})


if __name__ == '__main__':
    unittest.main()
