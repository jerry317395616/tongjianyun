"""Pure tests: no server, Redis, native task, model, credential or sudo access."""
from contextlib import ExitStack, contextmanager, nullcontext, redirect_stderr, redirect_stdout
import builtins
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import sqlite3
import stat
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

SPEC = importlib.util.spec_from_file_location('unaccepted_recipe_recovery_tests',
    Path(__file__).with_name('finalize_unaccepted_recipe_journey.py'))
f = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(f)
j = f.j
RUN = '40f8247d-c7e1-4efd-9f8c-a702ab969e6e'
TASK = '40fab4e3-a2a2-4a9d-9e55-fa894f995ecd'
SHA = 'a' * 64


class Pure(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)

    def patch(self, obj, name, **kwargs):
        return self.stack.enter_context(patch.object(obj, name, **kwargs))


class ContractTests(Pure):
    def test_explicit_uuid_and_reviewed_hash_required(self):
        execute = self.patch(f, 'execute')
        for args in ([], ['--run-id', RUN], ['--run-id', '../bad', '--request-id', TASK, '--source-sha256', SHA],
                     ['--run-id', RUN, '--request-id', TASK, '--source-sha256', 'A' * 64],
                     ['--run-id', RUN, '--request-id', TASK, '--source-sha256', SHA, '--owner', 'Administrator']):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                f.main(args)
        execute.assert_not_called()

    def test_default_is_read_only_command(self):
        execute = self.patch(f, 'execute', return_value={'read_only': True})
        with redirect_stdout(io.StringIO()):
            self.assertTrue(f.main(['--run-id', RUN, '--request-id', TASK, '--source-sha256', SHA])['read_only'])
        execute.assert_called_once_with('check', RUN, TASK, SHA)

    def test_foreign_helper_path_never_initializes_native_environment(self):
        environment = self.patch(j, 'environment')
        with self.assertRaises(PermissionError):
            f.environment(SHA)
        environment.assert_not_called()

    def test_exact_backend_id_and_composite_start_record(self):
        backend = j.qa.SITE + '||business-codex-site-' + TASK
        self.assertTrue(f.matching_job(backend.encode(), backend))
        self.assertTrue(f.matching_job(backend + ':execution', backend))
        self.assertFalse(f.matching_job(backend + '-different', backend))
        with self.assertRaises(PermissionError):
            f.matching_job(None, backend)


class DurableTests(Pure):
    def database(self, host=False):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('CREATE TABLE identity (id INTEGER, site TEXT)')
        db.execute('INSERT INTO identity VALUES (1, ?)', (j.qa.SITE,))
        db.execute('CREATE TABLE tasks (task_id TEXT, owner TEXT)')
        for table in (('aliases',) if host else ('outbox', 'events', 'authorities')):
            db.execute('CREATE TABLE ' + table + ' (task_id TEXT)')
        @contextmanager
        def read(_):
            yield db
        self.patch(j.previous, 'read_db', side_effect=read)
        return db

    def test_exact_absence_with_correct_site(self):
        db = self.database()
        db.execute('INSERT INTO tasks VALUES (?, ?)', ('unrelated', 'someone-else'))
        self.assertEqual(f.absent_rows(Path('unused'), TASK)['owner_history_count'], 0)

    def test_every_original_task_table_blocks_even_orphan_rows(self):
        db = self.database()
        for table in ('tasks', 'outbox', 'events', 'authorities'):
            db.execute('INSERT INTO ' + table + ' (task_id) VALUES (?)', (TASK,))
            with self.subTest(table=table), self.assertRaises(PermissionError):
                f.absent_rows(Path('unused'), TASK)
            db.execute('DELETE FROM ' + table)

    def test_other_manager_history_blocks_recovery(self):
        db = self.database()
        db.execute('INSERT INTO tasks VALUES (?, ?)', ('another-task', j.OWNER))
        with self.assertRaises(PermissionError):
            f.absent_rows(Path('unused'), TASK)

    def test_host_gate_and_orphan_alias_each_block(self):
        db = self.database(host=True)
        for table in ('tasks', 'aliases'):
            db.execute('INSERT INTO ' + table + ' (task_id) VALUES (?)', (TASK,))
            with self.subTest(table=table), self.assertRaises(PermissionError):
                f.absent_rows(Path('unused'), TASK, host=True)
            db.execute('DELETE FROM ' + table)

    def test_foreign_or_missing_sqlite_identity_blocks(self):
        db = self.database()
        db.execute("UPDATE identity SET site='production'")
        with self.assertRaises(PermissionError):
            f.absent_rows(Path('unused'), TASK)
        db.execute('DELETE FROM identity')
        with self.assertRaises(PermissionError):
            f.absent_rows(Path('unused'), TASK)


class QueueTests(Pure):
    def setUp(self):
        super().setUp()
        self.frappe = MagicMock()
        self.connection = MagicMock()
        self.connection.exists.return_value = 0
        self.connection.scan.return_value = (0, [])
        self.connection.llen.return_value = 0
        self.connection.zcard.return_value = 0
        self.connection.zrange.return_value = []
        self.connection.hmget.return_value = [b'idle', b'']
        self.logical = 'business-codex-' + hashlib.sha256(j.qa.SITE.encode()).hexdigest()[:16] + '-' + TASK
        self.backend = j.qa.SITE + '||' + self.logical
        self.patch(j.qa, 'guard')
        registry = SimpleNamespace()
        for name in ('StartedJobRegistry', 'DeferredJobRegistry', 'ScheduledJobRegistry',
                     'FailedJobRegistry', 'FinishedJobRegistry', 'CanceledJobRegistry'):
            def initialize(instance, *, queue, key=name):
                instance.key = key
            setattr(registry, name, type(name, (), {'__init__': initialize}))
        self.bg = SimpleNamespace(create_job_id=lambda value: j.qa.SITE + '||' + value,
            generate_qname=lambda name: 'bench:' + name, get_redis_conn=lambda: self.connection)
        self.stack.enter_context(patch.dict(sys.modules, {
            'frappe.utils.background_jobs': self.bg,
            'rq': SimpleNamespace(Queue=lambda *args, **kwargs: SimpleNamespace(key='rq:queue:bench:business_codex')),
            'rq.registry': registry,
            'rq.worker_registration': SimpleNamespace(get_keys=lambda **kwargs: ['rq:worker:exact'])}))

    def test_all_reads_no_cleanup_with_real_composite_formats(self):
        result = f.queue_absence(self.frappe, TASK)
        self.assertTrue(result['exact_job_absent'])
        self.assertTrue(result['execution_entities_absent'])
        self.assertEqual(result['idle_registered_workers'], 1)
        self.assertEqual(set(result['registries']), {'StartedJobRegistry', 'DeferredJobRegistry',
            'ScheduledJobRegistry', 'FailedJobRegistry', 'FinishedJobRegistry', 'CanceledJobRegistry'})
        self.assertTrue({call[0] for call in self.connection.method_calls} <=
                        {'exists', 'scan', 'llen', 'zcard', 'zrange', 'hmget'})
        self.frappe.destroy.assert_called_once()

    def test_existing_job_or_execution_registry_blocks(self):
        for prefix in ('rq:job:', 'rq:executions:'):
            self.connection.exists.side_effect = lambda key: int(key.startswith(prefix))
            with self.subTest(prefix=prefix), self.assertRaises(PermissionError):
                f.queue_absence(self.frappe, TASK)

    def test_orphan_execution_entity_blocks(self):
        self.connection.scan.return_value = (0, [b'rq:execution:orphan'])
        with self.assertRaises(PermissionError):
            f.queue_absence(self.frappe, TASK)

    def test_unknown_or_unbounded_scan_blocks(self):
        self.connection.scan.return_value = (1, [])
        with self.assertRaises(PermissionError):
            f.queue_absence(self.frappe, TASK)
        self.assertEqual(self.connection.scan.call_count, 1000)

    def test_queue_or_intermediate_pending_blocks(self):
        for suffix in ('business_codex', ':intermediate'):
            self.connection.llen.side_effect = lambda key: int(key.endswith(suffix))
            with self.subTest(suffix=suffix), self.assertRaises(PermissionError):
                f.queue_absence(self.frappe, TASK)

    def test_exact_id_or_started_composite_in_any_registry_blocks(self):
        for value in (self.backend, self.backend + ':execution'):
            self.connection.zcard.return_value = 1
            self.connection.zrange.return_value = [value.encode()]
            with self.subTest(value=value), self.assertRaises(PermissionError):
                f.queue_absence(self.frappe, TASK)

    def test_active_other_workhorse_or_changed_registry_blocks(self):
        self.connection.zcard.return_value = 1
        self.connection.zrange.return_value = [b'another-job:execution']
        with self.assertRaises(PermissionError):
            f.queue_absence(self.frappe, TASK)
        self.connection.zrange.return_value = []
        with self.assertRaises(PermissionError):
            f.queue_absence(self.frappe, TASK)

    def test_busy_worker_unknown_state_or_current_job_blocks(self):
        for values in ([b'busy', b''], [None, None], [b'idle', self.backend.encode()]):
            self.connection.hmget.return_value = values
            with self.subTest(values=values), self.assertRaises(PermissionError):
                f.queue_absence(self.frappe, TASK)


class NativeTests(Pure):
    def setUp(self):
        super().setUp()
        self.observation = {'task_id': TASK, 'root_lstat': True, 'tombstone_absent': True,
                            'input_absent': True, 'work_absent': True, 'cgroup_absent': True}
        self.run = self.patch(f, 'admin_probe', return_value=json.dumps(self.observation))
        self.unit = self.patch(j.previous, 'unit_proof', return_value={'LoadState': 'not-found',
            'ActiveState': 'inactive', 'SubState': 'dead', 'MainPID': '0', 'ControlGroup': ''})

    def test_only_fixed_root_readonly_probe_and_exact_unit(self):
        value = f.native_absence(TASK)
        self.assertEqual(value['native_state'], 'never_accepted_not_exit_evidence')
        self.run.assert_called_once_with(TASK)
        self.assertNotIn('seal_before_start', f.ROOT_PROBE)
        self.unit.assert_called_once_with(TASK)

    def test_root_probe_unknown_or_wrong_task_blocks(self):
        for result in ('{}', json.dumps({**self.observation, 'task_id': RUN}),
                       json.dumps({**self.observation, 'cgroup_absent': False}),
                       json.dumps({**self.observation, 'cgroup_absent': 1})):
            self.run.return_value = result
            with self.subTest(result=result), self.assertRaises(PermissionError):
                f.native_absence(TASK)

    def test_existing_inactive_native_unit_still_blocks(self):
        self.unit.return_value['LoadState'] = 'loaded'
        with self.assertRaises(PermissionError):
            f.native_absence(TASK)

    def test_task_id_injection_never_runs_sudo(self):
        with self.assertRaises(ValueError):
            f.native_absence(TASK + ';id')
        self.run.assert_not_called()


class AdminProtocolTests(Pure):
    def test_exact_three_admin_frames_never_start_a_thread_or_turn(self):
        frames = f.admin_frames(TASK)
        self.assertEqual([value['method'] for value in frames], ['initialize', 'initialized', 'command/exec'])
        self.assertEqual(frames[2]['params'], {'command': ['/usr/bin/python3', '-I', '-B', '-c', f.ROOT_PROBE, TASK],
            'cwd': '/', 'sandboxPolicy': {'type': 'dangerFullAccess'}, 'timeoutMs': 10000})
        self.assertEqual(f.ADMIN_ARGV, ('/usr/bin/sudo', '-n', '/usr/local/sbin/codex-deepseek-admin', 'app-server'))

    def test_split_response_and_notifications_are_bounded_without_actions(self):
        protocol = f.AdminProtocol()
        self.assertIsNone(protocol.response('stdout', b'{"method":"info","params":{}}\n{"id":', 1))
        self.assertEqual(protocol.response('stdout', b'1,"result":{"version":"native"}}\n', 1), {'version': 'native'})
        self.assertIsNone(protocol.response('stderr', b'bounded ignored diagnostics', 2))

    def test_native_emitted_at_metadata_is_ignored_for_known_observed_shapes(self):
        protocol = f.AdminProtocol()
        for method in ('configWarning', 'remoteControl/status/changed'):
            frame = {'method': method, 'params': {}, 'emittedAtMs': 1790409600000}
            self.assertIsNone(protocol.response('stdout', json.dumps(frame).encode() + b'\n', 1))
        self.assertEqual(protocol.response('stdout', b'{"id":1,"result":{}}\n', 1), {})
        # The same finite metadata is valid during final tail drainage.
        frame = {'method': 'remoteControl/status/changed', 'params': {}, 'emittedAtMs': 0}
        self.assertIsNone(protocol.response('stdout', json.dumps(frame).encode() + b'\n', None))

    def test_native_emitted_at_rejects_bool_negative_noninteger_or_unsafe_integer(self):
        for stamp in (True, False, -1, 1.0, None, '1790409600000', 9007199254740992):
            frame = {'method': 'configWarning', 'params': {}, 'emittedAtMs': stamp}
            with self.subTest(stamp=stamp), self.assertRaises(PermissionError):
                f.AdminProtocol().response('stdout', json.dumps(frame).encode() + b'\n', 1)

    def test_unknown_id_error_server_request_or_duplicate_keys_rejected(self):
        for frame in (b'{"id":2,"result":{}}\n', b'{"id":1,"error":{}}\n',
                      b'{"id":1,"method":"tool/request","params":{}}\n',
                      b'{"id":true,"result":{}}\n', b'{"id":1,"id":1,"result":{}}\n',
                      b'{"method":"notice","error":{}}\n', b'{"method":""}\n',
                      b'{"method":"notice","jsonrpc":"1.0"}\n'):
            with self.subTest(frame=frame), self.assertRaises((PermissionError, ValueError)):
                f.AdminProtocol().response('stdout', frame, 1)

    def test_stdout_stderr_notification_floods_fail_closed(self):
        for source, data in (('stdout', b'x' * 65537), ('stderr', b'x' * 16385),
                             ('stdout', b'{"method":"info"}\n' * 101)):
            with self.subTest(source=source), self.assertRaises(PermissionError):
                f.AdminProtocol().response(source, data, 1)


class AdminLifecycleTests(Pure):
    def setUp(self):
        super().setUp()
        self.process = MagicMock()
        self.process.returncode = 0
        self.process.stdin.write.side_effect = len
        self.process.stdout.fileno.return_value = 21
        self.process.stderr.fileno.return_value = 22
        self.popen = self.patch(f.subprocess, 'Popen', return_value=self.process)
        class Selector:
            def __init__(self): self.streams = {}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def register(self, pipe, events, name): self.streams[pipe] = SimpleNamespace(fileobj=pipe, data=name)
            def unregister(self, pipe): del self.streams[pipe]
            def get_map(self): return self.streams
            def select(self, timeout): return [(next(iter(self.streams.values())), None)]
        self.patch(f.selectors, 'DefaultSelector', side_effect=Selector)
        self.responses = [b'{"id":1,"result":{}}\n',
            json.dumps({'id': 2, 'result': {'exitCode': 0, 'stdout': '{}', 'stderr': ''}}).encode() + b'\n', b'']
        self.stderr = [b'']
        self.read = self.patch(f.os, 'read', side_effect=lambda fd, size:
            (self.responses if fd == 21 else self.stderr).pop(0))

    def test_success_closes_stdin_and_waits_without_terminating(self):
        self.assertEqual(f.admin_probe(TASK), '{}')
        sent = [json.loads(call.args[0]) for call in self.process.stdin.write.call_args_list]
        self.assertEqual(sent, list(f.admin_frames(TASK)))
        self.process.stdin.close.assert_called_once()
        self.process.wait.assert_called_once_with(timeout=10)
        self.process.terminate.assert_not_called()
        self.assertEqual(self.popen.call_args.args, (list(f.ADMIN_ARGV),))
        self.assertEqual(self.popen.call_args.kwargs['cwd'], '/')

    def test_nonzero_command_result_never_becomes_native_proof(self):
        self.responses[1] = b'{"id":2,"result":{"exitCode":1,"stdout":"{}","stderr":""}}\n'
        with self.assertRaises(PermissionError):
            f.admin_probe(TASK)
        self.process.stdin.close.assert_called_once()

    def test_channel_eof_is_unknown_and_closes_transport(self):
        self.responses[0] = b''
        with self.assertRaises(PermissionError):
            f.admin_probe(TASK)
        self.process.wait.assert_called_once()

    def test_partial_write_is_unknown_and_closes_transport(self):
        self.process.stdin.write.side_effect = lambda raw: len(raw) - 1
        with self.assertRaises(PermissionError):
            f.admin_probe(TASK)
        self.read.assert_not_called()
        self.process.stdin.close.assert_called_once()

    def test_timeout_termination_never_counts_as_success(self):
        self.process.wait.side_effect = [f.subprocess.TimeoutExpired(list(f.ADMIN_ARGV), 10), 0]
        with self.assertRaises(PermissionError):
            f.admin_probe(TASK)
        self.process.terminate.assert_called_once()
        self.assertEqual(self.process.wait.call_count, 2)

    def test_nonzero_transport_exit_rejects_even_successful_command(self):
        self.process.returncode = 1
        with self.assertRaises(PermissionError):
            f.admin_probe(TASK)

    def test_same_chunk_duplicate_response_after_success_is_rejected(self):
        self.responses[1] += b'{"id":666,"result":{}}\n'
        with self.assertRaises(PermissionError):
            f.admin_probe(TASK)

    def test_partial_tail_after_success_is_rejected_at_eof(self):
        self.responses[1] += b'{"method":'
        with self.assertRaises(PermissionError):
            f.admin_probe(TASK)

    def test_later_chunk_duplicate_response_after_success_is_rejected(self):
        self.responses.insert(2, b'{"id":2,"result":{}}\n')
        with self.assertRaises(PermissionError):
            f.admin_probe(TASK)

    def test_later_stderr_flood_after_success_is_rejected(self):
        self.stderr.insert(0, b'x' * 16385)
        with self.assertRaises(PermissionError):
            f.admin_probe(TASK)

    def test_finite_tail_notifications_then_both_eof_are_allowed(self):
        self.responses[1] += b'{"method":"notice","params":{}}\n'
        self.responses.insert(2, b'{"method":"stopped","jsonrpc":"2.0"}\n')
        self.stderr.insert(0, b'finite diagnostic')
        self.assertEqual(f.admin_probe(TASK), '{}')
        self.assertEqual(self.responses, [])
        self.assertEqual(self.stderr, [])
        self.process.wait.assert_called_once_with(timeout=10)


class RootProbeTests(Pure):
    def probe(self, *, present=None, uid=0, unsafe=None, foreign_root=False):
        observations, output = [], []
        class FakePath(PurePosixPath):
            def resolve(self, strict):
                return self
            def lstat(self):
                observations.append(str(self))
                is_task = TASK in str(self)
                if is_task and str(self) != present:
                    raise FileNotFoundError
                return SimpleNamespace(st_uid=uid, st_mode=(stat.S_IFDIR | (0o777 if str(self) == unsafe else 0o700)))
        modules = {'json': json, 'os': SimpleNamespace(geteuid=lambda: 1 if foreign_root else 0),
                   'pathlib': SimpleNamespace(Path=FakePath), 'stat': stat,
                   'sys': SimpleNamespace(argv=['fixed', TASK]), 'uuid': f.uuid}
        builtins_copy = dict(vars(builtins), __import__=lambda name, *args, **kwargs: modules[name], print=output.append)
        exec(f.ROOT_PROBE, {'__builtins__': builtins_copy})
        return observations, json.loads(output[0])

    def test_root_probe_observes_exact_cgroup_and_original_paths_only(self):
        paths, value = self.probe()
        self.assertTrue(value['cgroup_absent'])
        self.assertEqual({path for path in paths if TASK in path}, {
            '/var/lib/tongjianyun-business-codex/launcher/' + TASK + '.json',
            '/run/tongjianyun-business-codex/tasks/' + TASK,
            '/run/tgy-business-' + TASK,
            '/sys/fs/cgroup/system.slice/tgy-business-codex-' + TASK + '.service'})

    def test_any_exact_record_input_work_or_cgroup_blocks_without_reading_contents(self):
        for path in ('/var/lib/tongjianyun-business-codex/launcher/' + TASK + '.json',
                     '/run/tongjianyun-business-codex/tasks/' + TASK, '/run/tgy-business-' + TASK,
                     '/sys/fs/cgroup/system.slice/tgy-business-codex-' + TASK + '.service'):
            with self.subTest(path=path), self.assertRaises(PermissionError):
                self.probe(present=path)

    def test_foreign_user_or_untrusted_directory_is_not_absence(self):
        for values in ({'foreign_root': True}, {'uid': 1000}, {'unsafe': '/run'}):
            with self.subTest(values=values), self.assertRaises(PermissionError):
                self.probe(**values)


class WorkflowTests(Pure):
    def setUp(self):
        super().setUp()
        self.events = []
        self.record = {'run_id': RUN, 'source_sha256': {'original': SHA}, 'before': {}}
        self.patch(f, 'environment', return_value=object())
        self.patch(j.previous, 'lock', side_effect=lambda *_: nullcontext())
        self.patch(f, 'load', return_value=self.record)
        self.close = self.patch(j, 'close_admission', side_effect=lambda *_: self.events.append('close'))
        self.collect = self.patch(f, 'collect', side_effect=lambda *args, **kwargs:
            (self.events.append('proof'), {'classification': 'never_accepted', 'business_journey_passed': False})[1])
        self.write = self.patch(j.old, 'exclusive_json', side_effect=lambda *_: self.events.append('record'))
        self.stop = self.patch(f, 'stop_processes', side_effect=lambda *_: (self.events.append('stop'), [])[1])
        self.restore = self.patch(f, 'restore_owned', side_effect=lambda *_: self.events.append('restore'))
        self.patch(j, 'folder', return_value=Path('/not-used'))

    def test_check_never_fences_stops_restores_or_writes(self):
        result = f.execute('check', RUN, TASK, SHA)
        self.assertTrue(result['read_only'])
        self.assertFalse(result['finalization_authorized_by_this_check'])
        self.assertEqual(self.events, ['proof'])

    def test_finalization_requires_fence_and_both_pre_and_post_stop_proofs(self):
        result = f.execute('finalize', RUN, TASK, SHA)
        self.assertEqual(self.events, ['close', 'proof', 'record', 'stop', 'proof', 'restore', 'record'])
        self.assertEqual(result['classification'], 'never_accepted')
        self.assertFalse(result['business_journey_passed'])
        self.assertFalse(result['automatic_retry'])
        self.assertTrue(result['configuration_restored'])
        self.assertEqual(self.collect.call_args_list[0].kwargs, {'fenced': True})

    def test_unknown_absence_after_fence_never_signals_or_restores(self):
        self.collect.side_effect = PermissionError('unknown')
        with self.assertRaises(PermissionError):
            f.execute('finalize', RUN, TASK, SHA)
        self.close.assert_called_once()
        self.stop.assert_not_called()
        self.restore.assert_not_called()
        self.write.assert_not_called()

    def test_stop_failure_preserves_config_and_pre_stop_evidence(self):
        self.stop.side_effect = PermissionError('not stopped')
        with self.assertRaises(PermissionError):
            f.execute('finalize', RUN, TASK, SHA)
        self.restore.assert_not_called()
        self.assertEqual(self.write.call_count, 1)

    def test_post_stop_unknown_keeps_owned_configuration(self):
        self.collect.side_effect = [{'classification': 'never_accepted'}, PermissionError('unknown')]
        with self.assertRaises(PermissionError):
            f.execute('finalize', RUN, TASK, SHA)
        self.stop.assert_called_once()
        self.restore.assert_not_called()


class CollectionTests(Pure):
    def setUp(self):
        super().setUp()
        self.record = {'run_id': RUN, 'source_sha256': {'original': SHA}}
        self.frappe = object()
        self.fence = {'run_id': RUN, 'site': j.qa.SITE, 'owner': j.OWNER, 'closed': True}
        self.patch(j, 'pin')
        self.patch(j, 'folder', return_value=Path('/unused'))
        self.read = self.patch(j.old, 'private_read', return_value=self.fence)
        self.http = self.patch(j, 'http_drained')
        self.patch(j, 'registered_task', return_value=TASK)
        self.durable = self.patch(f, 'durable_absence', return_value={'absent': True})
        self.queue = self.patch(f, 'queue_absence', return_value={'absent': True})
        self.native = self.patch(f, 'native_absence', return_value={'absent': True})
        self.delta = self.patch(f, 'protected_delta', return_value={'protected_passed': True})

    def test_fenced_proof_checks_both_http_callbacks_and_repeats_durable_queue(self):
        proof = f.collect(self.record, self.frappe, TASK, fenced=True)
        self.assertTrue(proof['admission_closed'])
        self.assertEqual(proof['classification'], 'never_accepted')
        self.http.assert_called_once_with(self.record)
        self.assertEqual(self.durable.call_count, 2)
        self.assertEqual(self.queue.call_count, 2)

    def test_missing_or_foreign_fence_stops_before_any_runtime_proof(self):
        self.read.return_value = {**self.fence, 'closed': False}
        with self.assertRaises(PermissionError):
            f.collect(self.record, self.frappe, TASK, fenced=True)
        self.durable.assert_not_called()
        self.native.assert_not_called()

    def test_unknown_or_wrong_nonce_http_receipt_stops_before_runtime(self):
        self.http.side_effect = PermissionError('original nonce not drained')
        with self.assertRaises(PermissionError):
            f.collect(self.record, self.frappe, TASK, fenced=True)
        self.durable.assert_not_called()

    def test_protected_snapshot_failure_does_not_certify_absence(self):
        self.delta.side_effect = PermissionError('original recipe changed')
        with self.assertRaises(PermissionError):
            f.collect(self.record, self.frappe, TASK, fenced=True)

    def test_changed_second_task_or_queue_observation_refuses(self):
        self.durable.side_effect = [{'absent': True}, {'absent': False}]
        with self.assertRaises(PermissionError):
            f.collect(self.record, self.frappe, TASK, fenced=True)
        self.durable.side_effect = None
        self.queue.side_effect = [{'absent': True}, {'absent': False}]
        with self.assertRaises(PermissionError):
            f.collect(self.record, self.frappe, TASK, fenced=True)


class ProcessTests(Pure):
    def setUp(self):
        super().setUp()
        self.record = {'run_id': RUN}
        self.identities = {'web': {'pid': 12001, 'start_ticks': '1'}, 'worker': {'pid': 12002, 'start_ticks': '2'}}
        self.alive = {value['pid']: value for value in self.identities.values()}
        self.patch(j, 'folder', return_value=Path('/unused'))
        self.patch(j.old, 'private_read', side_effect=lambda path: {'identity': self.identities[path.stem]})
        self.identity = self.patch(j.previous, 'proc_identity', side_effect=lambda pid: self.alive.get(pid))
        self.pidfd = self.patch(f.os, 'pidfd_open', create=True, side_effect=lambda pid: pid)
        self.signal = self.patch(f.signal, 'pidfd_send_signal', create=True,
            side_effect=lambda fd, sig: self.alive.pop(fd, None))
        self.patch(f.os, 'close')
        self.select = self.patch(f.select, 'select', side_effect=lambda read, *args: (read, [], []))
        self.port = self.patch(j, 'port_absent')

    def test_only_exact_saved_pidfds_signaled(self):
        self.assertEqual(len(f.stop_processes(self.record)), 2)
        self.assertEqual([call.args for call in self.signal.call_args_list],
                         [(12001, f.signal.SIGTERM), (12002, f.signal.SIGTERM)])
        self.port.assert_called_once()

    def test_reused_pid_never_signaled(self):
        self.alive[12001] = {'pid': 12001, 'start_ticks': 'new'}
        with self.assertRaises(PermissionError):
            f.stop_processes(self.record)
        self.signal.assert_not_called()

    def test_unknown_shutdown_never_force_kills(self):
        self.select.return_value = ([], [], [])
        self.select.side_effect = None
        with self.assertRaises(PermissionError):
            f.stop_processes(self.record)
        self.assertEqual(self.signal.call_count, 1)
        self.port.assert_not_called()

    def test_already_absent_original_processes_are_not_signaled(self):
        self.alive.clear()
        self.assertEqual(len(f.stop_processes(self.record)), 2)
        self.signal.assert_not_called()

    def test_missing_native_pidfd_apis_uses_only_same_uid_system_helper(self):
        helper = self.patch(f, 'system_pidfd_stop', side_effect=lambda record, role, identity:
            {'role': role, 'original_process_absent': True, 'same_uid_system_pidfd_helper': True})
        # Exercise the actual hasattr branch, as in the deployed Python 3.14.
        del f.os.pidfd_open
        del f.signal.pidfd_send_signal
        try:
            values = f.stop_processes(self.record)
            self.assertEqual(helper.call_count, 2)
            self.assertTrue(all(value['same_uid_system_pidfd_helper'] for value in values))
            self.pidfd.assert_not_called()
            self.signal.assert_not_called()
        finally:
            f.os.pidfd_open = self.pidfd
            f.signal.pidfd_send_signal = self.signal


class SystemHelperTests(Pure):
    def setUp(self):
        super().setUp()
        self.identity = {'pid': 12001, 'start_ticks': '25', 'boot_id': RUN, 'cmdline_sha256': 'a' * 64}
        self.patch(f.os, 'geteuid', create=True, return_value=1000)
        self.current = self.patch(j.previous, 'proc_identity', return_value=None)
        self.result = {'run_id': RUN, 'role': 'web', 'pid': 12001,
                       'original_process_absent': True, 'term_sent': True, 'pidfd_verified': True}
        self.run = self.patch(f.subprocess, 'run', side_effect=lambda *args, **kwargs:
            SimpleNamespace(returncode=0, stdout=json.dumps(self.result).encode(), stderr=b''))

    def test_fixed_system_interpreter_same_uid_and_bounded_json_stdin(self):
        value = f.system_pidfd_stop({'run_id': RUN}, 'web', self.identity)
        self.assertTrue(value['same_uid_system_pidfd_helper'])
        self.assertEqual(self.run.call_args.args[0], ['/usr/bin/python3', '-I', '-B', '-c', f.PIDFD_STOP_PROBE])
        sent = json.loads(self.run.call_args.kwargs['input'])
        self.assertEqual(sent, {'run_id': RUN, 'role': 'web', 'identity': self.identity, 'uid': 1000})
        self.assertEqual(self.run.call_args.kwargs['timeout'], 15)
        self.assertEqual(self.run.call_args.kwargs['env'], {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})

    def test_wrong_role_or_root_never_executes_helper(self):
        with self.assertRaises(PermissionError):
            f.system_pidfd_stop({'run_id': RUN}, 'arbitrary', self.identity)
        f.os.geteuid.return_value = 0
        with self.assertRaises(PermissionError):
            f.system_pidfd_stop({'run_id': RUN}, 'web', self.identity)
        self.run.assert_not_called()

    def test_wrong_identity_nonboolean_or_live_pid_rejects_output(self):
        for change in ({'pid': 12002}, {'role': 'worker'}, {'term_sent': 1}, {'pidfd_verified': False},
                       {'original_process_absent': 1}):
            original = dict(self.result)
            self.result.update(change)
            with self.subTest(change=change), self.assertRaises(PermissionError):
                f.system_pidfd_stop({'run_id': RUN}, 'web', self.identity)
            self.result = original
        self.current.return_value = self.identity
        with self.assertRaises(PermissionError):
            f.system_pidfd_stop({'run_id': RUN}, 'web', self.identity)

    def test_failed_stderr_or_oversized_output_never_confirms_stop(self):
        for result in (SimpleNamespace(returncode=1, stdout=b'', stderr=b''),
                       SimpleNamespace(returncode=0, stdout=b'{}', stderr=b'warning'),
                       SimpleNamespace(returncode=0, stdout=b'x' * 4097, stderr=b'')):
            self.run.side_effect = None
            self.run.return_value = result
            with self.subTest(result=result), self.assertRaises(PermissionError):
                f.system_pidfd_stop({'run_id': RUN}, 'web', self.identity)


class SystemProbeTests(Pure):
    def probe(self, *, change=None, state_change=None, wait=True, remains=False, after_open_change=False,
              file_changes=None, zombie=False, reap=False):
        identity = {'pid': 12001, 'start_ticks': '25', 'boot_id': RUN,
                    'cmdline_sha256': hashlib.sha256(b'original').hexdigest()}
        value = {'run_id': RUN, 'role': 'web', 'identity': identity, 'uid': 1000}
        if change:
            value.update(change)
        record = {'run_id': RUN, 'site': j.qa.SITE, 'owner': j.OWNER, 'profile': j.PROFILE, 'state': 'prepared'}
        fence = {'run_id': RUN, 'site': j.qa.SITE, 'owner': j.OWNER, 'closed': True}
        files = {'run.json': record, 'admission-closed.json': fence, 'web.json': {'identity': identity}}
        if file_changes:
            files.update(file_changes)
        state = {'alive': True, 'cmdline': b'original', 'uid': 1000}
        if state_change:
            state.update(state_change)
        signals, output, opened, elapsed = [], [], {}, [0.0]
        self.signals = signals
        class FakePath(PurePosixPath):
            def resolve(self, strict): return self
            def lstat(self): return SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_uid=1000)
            def stat(self):
                if not state['alive']: raise FileNotFoundError
                return SimpleNamespace(st_uid=state['uid'])
            def read_text(self):
                if str(self) == '/proc/sys/kernel/random/boot_id': return RUN
                return '12001 (python) ' + ' '.join(['Z' if zombie and signals else 'S'] + ['0'] * 18 + ['25', '0'])
            def read_bytes(self): return state['cmdline']
        def open_file(path, flags):
            fd = 30 + len(opened)
            opened[fd] = json.dumps(files[path.name]).encode()
            return fd
        def pidfd(pid):
            if after_open_change: state['cmdline'] = b'changed'
            return 99
        def send(fd, sig):
            signals.append((fd, sig))
            if not remains: state['alive'] = False
        def sleep(seconds):
            elapsed[0] += seconds
            if reap: state['alive'] = False
        native_os = SimpleNamespace(geteuid=lambda: 1000, getuid=lambda: 1000, getpid=lambda: 888,
            O_RDONLY=0, O_NOFOLLOW=1, open=open_file, close=lambda fd: None,
            fstat=lambda fd: SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=1000,
                                           st_nlink=1, st_size=len(opened[fd])),
            fdopen=lambda fd, *args, **kwargs: io.BytesIO(opened[fd]), pidfd_open=pidfd)
        modules = {'hashlib': hashlib, 'json': json, 'os': native_os, 'pathlib': SimpleNamespace(Path=FakePath),
            're': f.re, 'select': SimpleNamespace(select=lambda *args: ([99], [], []) if wait else ([], [], [])),
            'signal': SimpleNamespace(SIGTERM=15, pidfd_send_signal=send), 'stat': stat,
            'sys': SimpleNamespace(stdin=SimpleNamespace(buffer=io.BytesIO(json.dumps(value).encode()))),
            'time': SimpleNamespace(monotonic=lambda: elapsed[0], sleep=sleep), 'uuid': f.uuid}
        builtins_copy = dict(vars(builtins), __import__=lambda name, *args, **kwargs: modules[name], print=output.append)
        exec(f.PIDFD_STOP_PROBE, {'__builtins__': builtins_copy})
        return json.loads(output[0])

    def test_original_uid_record_and_pidfd_exit_are_required(self):
        result = self.probe()
        self.assertTrue(result['original_process_absent'])
        self.assertTrue(result['term_sent'])
        self.assertEqual(self.signals, [(99, 15)])

    def test_bad_input_uid_role_or_identity_never_signals(self):
        for change in ({'uid': 0}, {'uid': True}, {'uid': 1001}, {'role': 'arbitrary'},
                       {'run_id': '../escape'}, {'identity': {'pid': 12001}}):
            with self.subTest(change=change), self.assertRaises((PermissionError, ValueError)):
                self.probe(change=change)
            self.assertEqual(self.signals, [])

    def test_uid_or_identity_change_before_or_after_pidfd_never_signals(self):
        for values in ({'state_change': {'uid': 1001}}, {'state_change': {'cmdline': b'changed'}},
                       {'after_open_change': True}):
            with self.subTest(values=values), self.assertRaises(PermissionError):
                self.probe(**values)
            self.assertEqual(self.signals, [])

    def test_absent_original_pid_needs_no_signal(self):
        result = self.probe(state_change={'alive': False})
        self.assertFalse(result['term_sent'])
        self.assertEqual(self.signals, [])

    def test_foreign_original_record_or_unfenced_run_never_signals(self):
        for files in ({'admission-closed.json': {}}, {'run.json': {}}, {'web.json': {'identity': {}}}):
            with self.subTest(files=files), self.assertRaises(PermissionError):
                self.probe(file_changes=files)
            self.assertEqual(self.signals, [])

    def test_brief_same_original_zombie_can_reap_without_another_signal(self):
        result = self.probe(remains=True, zombie=True, reap=True)
        self.assertTrue(result['original_process_absent'])
        self.assertEqual(self.signals, [(99, 15)])

    def test_unreaped_zombie_still_fails_after_bound_without_signal_repeat(self):
        with self.assertRaises(PermissionError):
            self.probe(remains=True, zombie=True)
        self.assertEqual(self.signals, [(99, 15)])

    def test_timeout_or_remaining_pid_does_not_repeat_or_force_signal(self):
        for values in ({'wait': False}, {'remains': True}):
            with self.subTest(values=values), self.assertRaises(PermissionError):
                self.probe(**values)
            self.assertEqual(self.signals, [(99, 15)])


if __name__ == '__main__':
    unittest.main()
