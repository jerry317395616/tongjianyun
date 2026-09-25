"""Pure/mocked launcher tests plus Linux socket tests; never launch systemd/model."""
from __future__ import annotations

import copy
import io
import hashlib
import json
import marshal
import os
from pathlib import Path, PurePosixPath
import socket
import stat
import struct
import sys
import py_compile
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import native_launcher as launcher
import native_sandbox

TASK = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'
CLAIM = 'bbbbbbbb-bbbb-4ccc-8ddd-eeeeeeeeeeee'
OTHER = 'cccccccc-bbbb-4ccc-8ddd-eeeeeeeeeeee'
SITE = launcher.Site('qa.localhost', PurePosixPath('/srv/sites'), 1000, 1000)
PEER = (321, 1000, 1000)


def request(op, **kw):
    result = {'version': 1, 'profile': launcher.PROFILE, 'op': op, 'site': SITE.name}
    if op != 'ready':
        result.update(task_id=TASK, claim_id=CLAIM)
    result.update(kw)
    return result


def start():
    return request('start', prompt='合成只读请求', token='a' * 43, proxy_path=str(SITE.proxy_path(TASK)))


class MemoryLedger:
    def __init__(self):
        self.records = {}

    def reserve(self, site, task, claim, *, sealed=False):
        if task in self.records:
            raise FileExistsError('already reserved')
        value = {'version': 1, 'site': site, 'task_id': task, 'claim_id': claim,
                 'stage': 'never_started_and_sealed' if sealed else 'bound',
                 'proof': launcher.sealed_proof(task, claim) if sealed else None}
        self.update(value)
        return value

    def update(self, record):
        self.records[record['task_id']] = copy.deepcopy(record)

    def load(self, task):
        if task not in self.records:
            raise FileNotFoundError('No registered task')
        return copy.deepcopy(self.records[task])


def task_object():
    ledger = MemoryLedger()
    record = ledger.reserve(SITE.name, TASK, CLAIM)
    return launcher.Task(SITE, record, ledger, native_sandbox)


def inactive():
    return {'inactive': True, 'empty': True, 'missing': True}


class ProtocolTests(unittest.TestCase):
    def test_exact_shapes_and_registered_peer(self):
        self.assertEqual(launcher.validate_request(start(), {SITE.name: SITE}, PEER), SITE)
        for altered in (dict(start(), command='id'), dict(start(), env={}), dict(start(), uid=0),
                        dict(start(), mount='/'), dict(start(), owner='Administrator'),
                        dict(start(), site='../x'), dict(start(), proxy_path='/tmp/proxy.sock')):
            with self.subTest(altered=list(altered)), self.assertRaises((ValueError, PermissionError)):
                launcher.validate_request(altered, {SITE.name: SITE}, PEER)
        for peer in ((1, 0, 0), (1, 1001, 1000), (1, 1000, 1001)):
            with self.assertRaises(PermissionError):
                launcher.validate_request(start(), {SITE.name: SITE}, peer)

    def test_uuids_credentials_and_bounds(self):
        for key, value in (('task_id', '../escape'), ('claim_id', CLAIM.upper()), ('token', 'x\n' * 43),
                           ('token', 'x' * 42), ('token', 'x' * 129), ('prompt', ''),
                           ('prompt', '汉' * (launcher.MAX_PROMPT // 3 + 1))):
            with self.subTest(key=key), self.assertRaises(ValueError):
                launcher.validate_request(dict(start(), **{key: value}), {SITE.name: SITE}, PEER)
        for wait in (-1, 1001, True, '1'):
            with self.assertRaises(ValueError):
                launcher.validate_request(request('poll', wait_ms=wait), {SITE.name: SITE}, PEER)

    def test_nonfinite_duplicate_and_unknown_version_rejected(self):
        for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}'):
            with self.assertRaises(ValueError):
                launcher.finite_json(raw)
        for version in (True, '1', 2):
            with self.assertRaises(ValueError):
                launcher.validate_request(dict(start(), version=version), {SITE.name: SITE}, PEER)

    def test_real_socket_pair_framing_and_clean_eof(self):
        left, right = socket.socketpair()
        try:
            data = launcher.encoded(request('ready'))
            left.sendall(data[:2])
            left.sendall(data[2:])
            self.assertEqual(launcher.receive(right), request('ready'))
            self.assertIsNone(right.gettimeout())
            left.close()
            self.assertIsNone(launcher.receive(right))
        finally:
            left.close()
            right.close()

    def test_truncated_and_oversized_frames(self):
        for raw in (b'\x00\x00', struct.pack('!I', launcher.MAX_FRAME + 1), struct.pack('!I', 8) + b'{}'):
            left, right = socket.socketpair()
            try:
                left.sendall(raw)
                left.shutdown(socket.SHUT_WR)
                with self.assertRaises(ValueError):
                    launcher.receive(right)
            finally:
                left.close()
                right.close()

    def test_config_exact_site_mapping_and_hashes(self):
        config = {'version': 1, 'control_gid': 5000, 'sites': {SITE.name:
            {'sites_path': '/srv/sites', 'uid': 1000, 'gid': 1000}},
            'runtime_sha256': {name: 'a' * 64 for name in launcher.RUNTIME_FILES}}
        with mock.patch.object(launcher, 'Path', PurePosixPath):
            self.assertEqual(launcher.parse_config(config), {SITE.name: SITE})
            for mutation in ({'control_gid': 0}, {'control_gid': True}, {'sites': {}}, {'runtime_sha256': {}}, {'env': {}}):
                with self.assertRaises(ValueError):
                    launcher.parse_config(dict(config, **mutation))
            for field, value in (('sites_path', '/srv/../sites'), ('sites_path', '/srv//sites'), ('uid', 0), ('gid', True)):
                changed = copy.deepcopy(config)
                changed['sites'][SITE.name][field] = value
                with self.assertRaises(ValueError):
                    launcher.parse_config(changed)


class TaskTests(unittest.TestCase):
    def test_popen_zero_is_not_cgroup_exit_evidence(self):
        task = task_object()
        task.process = mock.Mock()
        task.process.poll.return_value = 0
        task.stdout_eof = task.stderr_eof = True
        for actual in ({'inactive': False, 'empty': False, 'missing': False},
                       {'inactive': True, 'empty': False, 'missing': False}):
            with mock.patch.object(launcher, 'system_unit', return_value=actual):
                self.assertNotEqual(task.proof()['state'], 'exited')
        with mock.patch.object(launcher, 'system_unit', side_effect=RuntimeError):
            self.assertEqual(task.proof()['state'], 'unknown')

    def test_actual_exit_proof_live_lease_not_reconcileable(self):
        task = task_object()
        task.process = mock.Mock()
        task.process.poll.return_value = 0
        task.stdout_eof = task.stderr_eof = True
        with mock.patch.object(launcher, 'system_unit', return_value=inactive()):
            proof = task.proof()
        self.assertEqual(proof['state'], 'exited')
        self.assertFalse(proof['lease_closed'])
        self.assertEqual(task.ledger.load(TASK)['proof'], proof)

    def test_stdout_chunks_never_signal_early_eof(self):
        task = task_object()
        task.process = mock.Mock()
        task.process.poll.return_value = 0
        task.stdout_eof = task.stderr_eof = True
        task.stdout.extend(b'a' * (launcher.MAX_CHUNK + 7))
        with mock.patch.object(launcher, 'system_unit', return_value=inactive()):
            first, last = task.poll(0), task.poll(0)
        self.assertEqual(len(launcher.base64.b64decode(first['stdout'])), launcher.MAX_CHUNK)
        self.assertFalse(first['execution']['stdout_eof'])
        self.assertTrue(last['execution']['stdout_eof'])
        self.assertEqual(last['execution']['state'], 'exited')
        self.assertEqual(launcher.base64.b64decode(last['stdout']), b'a' * 7)

    def test_stderr_is_count_only_and_never_stored(self):
        task = task_object()
        task._drain(io.BytesIO(b'PRIVATE_KEY_VALUE traceback'), False)
        with mock.patch.object(launcher, 'system_unit', return_value=inactive()):
            first, next_frame = task.poll(0), task.poll(0)
        self.assertEqual(first['stderr_bytes'], len(b'PRIVATE_KEY_VALUE traceback'))
        self.assertEqual(next_frame['stderr_bytes'], 0)
        self.assertNotIn('PRIVATE_KEY_VALUE', repr(first) + repr(task.record))

    def test_pipe_drain_memory_and_byte_limits(self):
        task = task_object()
        with mock.patch.object(launcher, 'MAX_BUFFER', 16):
            task._drain(io.BytesIO(b'x' * 32), True)
        self.assertTrue(task.failed)
        self.assertLessEqual(len(task.stdout), 16)
        other = task_object()
        with mock.patch.object(launcher, 'MAX_STDERR', 16):
            other._drain(io.BytesIO(b'x' * 32), False)
        self.assertTrue(other.failed)
        self.assertTrue(other.stderr_eof)

    def test_stop_revokes_relay_before_fixed_cgroup_stop(self):
        task = task_object()
        task.record['stage'] = 'started'
        task.process = mock.Mock()
        task.process.poll.return_value = -15
        task.stdout_eof = task.stderr_eof = True
        trace = []
        task.relay = mock.Mock()
        task.relay.close.side_effect = lambda: trace.append('revoke')
        with (mock.patch.object(launcher, 'fixed_stop', side_effect=lambda _, **kw: trace.append('stop')),
              mock.patch.object(launcher, 'system_unit', return_value=inactive())):
            proof = task.stop()
        self.assertEqual(trace, ['revoke', 'stop'])
        self.assertEqual(proof['state'], 'exited')
        self.assertFalse(proof['lease_closed'])

    def test_close_marks_lease_closed_only_after_verified_cleanup(self):
        task = task_object()
        with (mock.patch.object(launcher, 'fixed_stop'), mock.patch.object(launcher, 'system_unit', return_value=inactive()),
              mock.patch.object(Path, 'exists', return_value=False)):
            self.assertTrue(task.close())
        proof = task.ledger.load(TASK)['proof']
        self.assertEqual(proof['state'], 'never_started_and_sealed')
        self.assertTrue(proof['lease_closed'])
        self.assertEqual(task.record['stage'], 'never_started_and_sealed')

    def test_unverified_close_never_claims_cleaned(self):
        task = task_object()
        unknown = launcher.unknown_proof(TASK, CLAIM)
        with mock.patch.object(task, 'stop', return_value=unknown):
            self.assertFalse(task.close())
        self.assertEqual(task.record['stage'], 'unresolved')
        self.assertFalse(task.lease_closed)

    def test_starting_or_started_without_handle_never_invents_exit(self):
        for stage in ('starting', 'started'):
            task = task_object()
            task.record['stage'] = stage
            with (mock.patch.object(launcher, 'fixed_stop') as stop,
                  mock.patch.object(launcher, 'system_unit', return_value=inactive())):
                proof = task.stop()
            stop.assert_called_once()
            self.assertEqual(proof['state'], 'unknown')
            self.assertIsNone(proof['exit_code'])
            self.assertFalse(proof['lease_closed'])
            self.assertIsNone(task.terminal_proof)

    def test_popen_failure_retains_unknown_attempt_not_sealed(self):
        task = task_object()
        with (mock.patch.object(Path, 'mkdir'), mock.patch.object(launcher, 'PinnedProxy'),
              mock.patch.object(launcher, 'write_private'), mock.patch.object(launcher, 'Relay'),
              mock.patch.object(launcher.subprocess, 'Popen', side_effect=OSError('launch outcome unavailable')),
              mock.patch.object(launcher, 'fixed_stop'),
              mock.patch.object(launcher, 'system_unit', return_value=inactive())):
            with self.assertRaises(OSError):
                task.start(start())
            self.assertEqual(task.proof()['state'], 'unknown')
        self.assertEqual(task.record['stage'], 'starting')
        self.assertIsNone(task.exit_code)

    def test_launch_fixed_native_argv_environment_and_pre_reserved_once(self):
        task = task_object()
        pinned = mock.Mock()
        fake_process = mock.Mock()
        with (mock.patch.object(Path, 'mkdir'), mock.patch.object(launcher, 'PinnedProxy', return_value=pinned),
             mock.patch.object(launcher, 'write_private') as write,
             mock.patch.object(launcher, 'Relay'), mock.patch.object(launcher.subprocess, 'Popen', return_value=fake_process) as launch,
             mock.patch.object(launcher.threading, 'Thread')):
            task.start(start())
            with self.assertRaises(PermissionError):
                task.start(start())
        launch.assert_called_once()
        self.assertEqual(launch.call_args.args[0], launcher.launch_command(native_sandbox, TASK))
        self.assertEqual(launch.call_args.kwargs['env'], launcher.ENV)
        self.assertNotIn('a' * 43, repr(launch.call_args))
        self.assertEqual(write.call_count, 2)
        self.assertEqual(task.ledger.load(TASK)['stage'], 'started')
        self.assertNotIn('合成', repr(task.ledger.records))


class LeaseTests(unittest.TestCase):
    def setUp(self):
        self.ledger = MemoryLedger()
        self.service = launcher.Launcher({SITE.name: SITE}, native_sandbox, self.ledger)
        self.lease = object()
        self.unit_check = mock.patch.object(launcher, 'system_unit', return_value=inactive())
        self.path_check = mock.patch.object(Path, 'exists', return_value=False)
        self.unit_check.start()
        self.path_check.start()
        self.addCleanup(self.unit_check.stop)
        self.addCleanup(self.path_check.stop)

    def bind(self):
        return self.service.request(request('bind'), PEER, self.lease)

    def test_bind_once_and_second_claim_never_restarts(self):
        self.assertEqual(self.bind(), {'ok': True, 'unit': launcher.unit(TASK), 'bound': True})
        for other_lease, claim in ((self.lease, CLAIM), (object(), CLAIM), (object(), OTHER)):
            with self.assertRaises((PermissionError, FileExistsError)):
                self.service.request(request('bind', claim_id=claim), PEER, other_lease)

    def test_foreign_lease_cannot_start_stop_release_or_poll(self):
        self.bind()
        for call in (start(), request('stop'), request('release'), request('poll', wait_ms=0)):
            with self.assertRaises(PermissionError):
                self.service.request(call, PEER, object())

    def test_observe_requires_known_exact_site_and_claim(self):
        with self.assertRaises(FileNotFoundError):
            self.service.request(request('observe'), PEER, object())
        self.bind()
        with self.assertRaises(PermissionError):
            self.service.request(request('observe', claim_id=OTHER), PEER, object())
        self.assertEqual(self.service.request(request('observe'), PEER, object())['state'], 'unknown')

    def test_disconnect_stops_original_task_and_retains_tombstone(self):
        self.bind()
        task = self.service.tasks[TASK]
        with mock.patch.object(launcher, 'fixed_stop') as stop:
            self.service.disconnect(self.lease)
        stop.assert_not_called()  # No process was ever admitted.
        self.assertNotIn(self.lease, self.service.leases)
        self.assertNotIn(TASK, self.service.tasks)
        proof = self.service.request(request('observe'), PEER, object())
        self.assertTrue(proof['lease_closed'])
        self.assertEqual(proof['state'], 'never_started_and_sealed')
        self.assertIsNone(proof['exit_code'])
        with self.assertRaises(FileExistsError):
            self.service.request(request('bind'), PEER, object())

    def test_release_retains_proof_and_cannot_relaunch(self):
        self.bind()
        with mock.patch.object(launcher, 'fixed_stop'):
            self.assertTrue(self.service.request(request('release'), PEER, self.lease)['cleaned'])
        self.assertTrue(self.service.request(request('observe'), PEER, object())['lease_closed'])
        with self.assertRaises(PermissionError):
            self.service.request(start(), PEER, self.lease)

    def test_recovery_stops_without_launch_and_no_false_success(self):
        record = self.ledger.reserve(SITE.name, TASK, CLAIM)
        self.ledger.directory = mock.Mock()
        self.ledger.directory.iterdir.return_value = [Path('daemon.lock'), Path(TASK + '.json')]
        with (mock.patch.object(launcher, 'fixed_stop') as stop,
              mock.patch.object(launcher.subprocess, 'Popen') as popen):
            launcher.recover(self.ledger)
        stop.assert_called_once_with(TASK)
        popen.assert_not_called()
        self.assertEqual(self.ledger.load(TASK)['proof']['state'], 'unknown')


class SealTests(unittest.TestCase):
    def setUp(self):
        self.ledger = MemoryLedger()
        self.service = launcher.Launcher({SITE.name: SITE}, native_sandbox, self.ledger)
        for patcher in (mock.patch.object(launcher, 'system_unit', return_value=inactive()),
                        mock.patch.object(Path, 'exists', return_value=False),
                        mock.patch.object(launcher.os.path, 'lexists', return_value=False)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def seal(self, **fields):
        return self.service.request(request('seal_before_start', **fields), PEER, object())

    def test_exact_protocol_and_no_authority_parameters(self):
        self.assertEqual(launcher.validate_request(request('seal_before_start'), {SITE.name: SITE}, PEER), SITE)
        for fields in ({'cancel_requested': True}, {'owner': 'Administrator'}, {'proof': 'missing'},
                       {'token': 'x' * 43}, {'command': 'stop'}, {'path': '/tmp'}):
            with self.assertRaises(ValueError):
                self.seal(**fields)

    def test_missing_unit_is_not_exit_and_success_is_durable_seal(self):
        with mock.patch.object(launcher.subprocess, 'Popen') as popen, mock.patch.object(launcher, 'fixed_stop') as stop:
            proof = self.seal()
        self.assertEqual(proof, launcher.sealed_proof(TASK, CLAIM))
        self.assertIsNone(proof['exit_code'])
        self.assertNotEqual(proof['state'], 'exited')
        self.assertEqual(self.ledger.load(TASK)['proof'], proof)
        self.assertEqual(self.ledger.load(TASK)['stage'], 'never_started_and_sealed')
        self.assertEqual(self.service.tasks, {})
        self.assertEqual(self.service.leases, {})
        popen.assert_not_called()
        stop.assert_not_called()

    def test_late_bind_and_start_cannot_bypass_permanent_seal(self):
        self.seal()
        for call in (request('bind'), request('bind', claim_id=OTHER), start()):
            with self.assertRaises((FileExistsError, PermissionError)):
                self.service.request(call, PEER, object())

    def test_active_bound_stop_permanently_excludes_late_same_lease_start(self):
        lease = object()
        self.service.request(request('bind'), PEER, lease)
        with mock.patch.object(launcher.subprocess, 'Popen') as popen:
            proof = self.service.request(request('stop'), PEER, lease)
            self.assertEqual(proof['state'], 'never_started_and_sealed')
            self.assertIsNone(proof['exit_code'])
            with self.assertRaises(PermissionError):
                self.service.request(start(), PEER, lease)
            self.assertEqual(self.service.request(request('observe'), PEER, lease), proof)
            self.assertTrue(self.service.request(request('release'), PEER, lease)['cleaned'])
            self.assertEqual(self.ledger.load(TASK)['stage'], 'never_started_and_sealed')
        popen.assert_not_called()

    def test_idempotent_seal_observe_and_restart_keep_original_claim(self):
        proof = self.seal()
        with mock.patch.object(launcher, 'system_unit', side_effect=AssertionError('Must use permanent evidence')):
            self.assertEqual(self.seal(), proof)
            self.assertEqual(self.service.request(request('observe'), PEER, object()), proof)
        self.ledger.directory = mock.Mock()
        self.ledger.directory.iterdir.return_value = [Path(TASK + '.json')]
        with mock.patch.object(launcher, 'fixed_stop') as stop:
            launcher.recover(self.ledger)
        stop.assert_not_called()
        restarted = launcher.Launcher({SITE.name: SITE}, native_sandbox, self.ledger)
        self.assertEqual(restarted.request(request('observe'), PEER, object()), proof)
        with self.assertRaises(PermissionError):
            self.seal(claim_id=OTHER)
        other_site = launcher.Site('other.localhost', SITE.sites_path, SITE.uid, SITE.gid)
        self.service.sites[other_site.name] = other_site
        with self.assertRaises(PermissionError):
            self.seal(site=other_site.name)

    def test_live_bound_lease_is_not_sealable(self):
        lease = object()
        self.service.request(request('bind'), PEER, lease)
        proof = self.seal()
        self.assertEqual(proof['state'], 'unknown')
        self.assertFalse(proof['lease_closed'])
        self.assertEqual(self.ledger.load(TASK)['stage'], 'bound')
        self.assertIn(lease, self.service.leases)

    def test_start_admission_uses_same_state_lock_as_bind_and_seal(self):
        lease = object()
        self.service.request(request('bind'), PEER, lease)
        task = self.service.tasks[TASK]
        def check_lock(value):
            self.assertTrue(self.service.lock._is_owned())
            self.assertEqual(value, start())
        with mock.patch.object(task, '_start', side_effect=check_lock) as launch:
            self.assertTrue(self.service.request(start(), PEER, lease)['started'])
        launch.assert_called_once()

    def test_all_prior_attempts_preserve_unknown_instead_of_sealing(self):
        for stage in ('bound', 'starting', 'started', 'unresolved', 'closed'):
            with self.subTest(stage=stage):
                self.ledger.records.clear()
                record = self.ledger.reserve(SITE.name, TASK, CLAIM)
                record['stage'] = stage
                self.ledger.update(record)
                self.assertEqual(self.seal()['state'], 'unknown')
                self.assertEqual(self.ledger.load(TASK)['stage'], stage)

    def test_actual_exited_proof_is_retained_not_relabelled(self):
        record = self.ledger.reserve(SITE.name, TASK, CLAIM)
        actual = dict(launcher.unknown_proof(TASK, CLAIM), state='exited', exit_code=1,
                      cgroup_empty=True, stdout_eof=True, lease_closed=True)
        record.update(stage='closed', proof=actual)
        self.ledger.update(record)
        self.assertEqual(self.seal(), actual)

    def test_any_unit_cgroup_input_or_runtime_residue_refuses_seal(self):
        for actual in ({'inactive': True, 'empty': False, 'missing': True},
                       {'inactive': False, 'empty': True, 'missing': True},
                       {'inactive': True, 'empty': True, 'missing': False}):
            with mock.patch.object(launcher, 'system_unit', return_value=actual), self.assertRaises(PermissionError):
                self.seal()
        for input_exists, work_exists in ((True, False), (False, True)):
            with (mock.patch.object(launcher.os.path, 'lexists', side_effect=[input_exists, work_exists]),
                  self.assertRaises(PermissionError)):
                self.seal()
        self.assertEqual(self.ledger.records, {})

    def test_persistence_failure_never_acknowledges_seal(self):
        with mock.patch.object(self.ledger, 'reserve', side_effect=OSError('fsync failed')), self.assertRaises(OSError):
            self.seal()
        self.assertEqual(self.ledger.records, {})

    def test_seal_and_late_bind_are_serialized_under_same_lock(self):
        entered, release = threading.Event(), threading.Event()
        original = self.ledger.reserve
        results = {}
        def reserve(*args, **kwargs):
            if kwargs.get('sealed'):
                entered.set()
                self.assertTrue(release.wait(2))
            return original(*args, **kwargs)
        def bind():
            try:
                self.service.request(request('bind'), PEER, object())
                results['bind'] = 'started'
            except Exception as error:
                results['bind'] = type(error).__name__
        def seal():
            results['seal'] = self.seal()
        with mock.patch.object(self.ledger, 'reserve', side_effect=reserve):
            first = threading.Thread(target=seal)
            second = threading.Thread(target=bind)
            first.start()
            self.assertTrue(entered.wait(1))
            second.start()
            self.assertNotIn('bind', results)
            release.set()
            first.join(2)
            second.join(2)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(results['seal']['state'], 'never_started_and_sealed')
        self.assertEqual(results['bind'], 'FileExistsError')

    def test_bind_wins_race_and_seal_cannot_claim_prestart(self):
        entered, release = threading.Event(), threading.Event()
        original = self.ledger.reserve
        results = {}
        def reserve(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(2))
            return original(*args, **kwargs)
        def bind():
            results['bind'] = self.service.request(request('bind'), PEER, object())
        def seal():
            results['seal'] = self.seal()
        with mock.patch.object(self.ledger, 'reserve', side_effect=reserve):
            first, second = threading.Thread(target=bind), threading.Thread(target=seal)
            first.start()
            self.assertTrue(entered.wait(1))
            second.start()
            self.assertNotIn('seal', results)
            release.set()
            first.join(2)
            second.join(2)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertTrue(results['bind']['bound'])
        self.assertEqual(results['seal']['state'], 'unknown')
        self.assertEqual(self.ledger.load(TASK)['stage'], 'bound')


class ShutdownTests(unittest.TestCase):
    def test_parallel_shutdown_reaches_all_tasks_before_waiting(self):
        service = launcher.Launcher({SITE.name: SITE}, native_sandbox, MemoryLedger())
        barrier = threading.Barrier(4)
        tasks = []
        for index in range(4):
            task = mock.Mock(task_id=str(index))
            task.close.side_effect = lambda: bool(barrier.wait(timeout=1) is not None)
            service.tasks[str(index)] = task
            tasks.append(task)
        self.assertTrue(service.shutdown(timeout=2))
        for task in tasks:
            task.close.assert_called_once()
            self.assertFalse(task.allow_start)
        self.assertFalse(service.request(request('ready'), PEER, object())['ready'])
        with self.assertRaises(PermissionError):
            service.request(request('bind'), PEER, object())

    def test_common_deadline_does_not_multiply_by_task_count(self):
        service = launcher.Launcher({SITE.name: SITE}, native_sandbox, MemoryLedger())
        release = threading.Event()
        for index in range(8):
            task = mock.Mock(task_id=str(index))
            task.close.side_effect = lambda: release.wait(1)
            service.tasks[str(index)] = task
        before = time.monotonic()
        try:
            self.assertFalse(service.shutdown(timeout=0.05))
            self.assertLess(time.monotonic() - before, 0.5)
        finally:
            release.set()


class UnitEvidenceTests(unittest.TestCase):
    def test_qa_units_bound_to_fixed_daemon_before_native_executable(self):
        original = native_sandbox.build_systemd_command(TASK)
        command = launcher.launch_command(native_sandbox, TASK)
        separator = command.index('--')
        self.assertEqual(command[separator - 2:separator], [
            '--property=BindsTo=tgy-business-codex-qa-launcher.service',
            '--property=After=tgy-business-codex-qa-launcher.service'])
        self.assertEqual(command[separator + 1:], original[-5:])
        self.assertEqual(command[:separator - 2], original[:-5])
        self.assertEqual(native_sandbox.build_systemd_command(TASK), original)
        for altered in (original + ['unreviewed'], ['sudo', *original], ['--', *original]):
            native = mock.Mock()
            native.build_systemd_command.return_value = altered
            with self.assertRaises(PermissionError):
                launcher.launch_command(native, TASK)

    def test_reviewed_native_source_not_poisoned_bytecode_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            source = ('from pathlib import Path\nPROC_ISOLATION_REVISION="bwrap-ro-v2"\n'
                      'INPUT_ROOT=Path("/run/tongjianyun-business-codex/tasks")\nMARKER="reviewed-source"\n')
            native = directory / 'native_sandbox.py'
            native.write_text(source, encoding='utf-8')
            cached = Path(py_compile.compile(str(native), doraise=True))
            poison = compile(source.replace('reviewed-source', 'unreviewed-cache'), str(native), 'exec')
            cached.write_bytes(cached.read_bytes()[:16] + marshal.dumps(poison))
            for name in launcher.RUNTIME_FILES - {'native_sandbox.py'}:
                (directory / name).write_bytes(b'synthetic')
            hashes = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest() for name in launcher.RUNTIME_FILES}
            info = mock.Mock(st_uid=0, st_mode=stat.S_IFREG | 0o755)
            with (mock.patch.object(launcher, 'INSTALL', directory),
                  mock.patch.object(launcher, 'root_path', side_effect=lambda path, **_: path),
                  mock.patch.object(Path, 'lstat', return_value=info),
                  mock.patch.object(Path, 'resolve', autospec=True, side_effect=lambda path, **_: path)):
                module = launcher.verify_runtime({'runtime_sha256': hashes})
            self.assertEqual(module.MARKER, 'reviewed-source')

    def test_systemctl_has_exact_unit_no_shell_and_requires_all_fields(self):
        result = mock.Mock(returncode=0, stdout=b'LoadState=not-found\nActiveState=inactive\nControlGroup=\nMainPID=0\n')
        with (mock.patch.object(launcher.subprocess, 'run', return_value=result) as run,
              mock.patch.object(Path, 'exists', return_value=False)):
            self.assertEqual(launcher.system_unit(TASK), inactive())
        self.assertEqual(run.call_args.args[0][0:3], ['/usr/bin/systemctl', 'show', launcher.unit(TASK)])
        self.assertNotIn('shell', run.call_args.kwargs)
        for output in (b'LoadState=not-found\n', result.stdout + b'Extra=1\n',
                       result.stdout.replace(b'ControlGroup=\n', b'ControlGroup=/other\n')):
            result.stdout = output
            with mock.patch.object(launcher.subprocess, 'run', return_value=result), self.assertRaises(RuntimeError):
                launcher.system_unit(TASK)

    def test_populated_child_prevents_empty_even_mainpid_zero(self):
        result = mock.Mock(returncode=0, stdout=('LoadState=loaded\nActiveState=inactive\nControlGroup=/system.slice/'
                          + launcher.unit(TASK) + '\nMainPID=0\n').encode())
        with (mock.patch.object(launcher.subprocess, 'run', return_value=result),
             mock.patch.object(Path, 'exists', return_value=True),
             mock.patch.object(Path, 'read_text', return_value='populated 1\nfrozen 0\n')):
            self.assertFalse(launcher.system_unit(TASK)['empty'])


class ClientContractTests(unittest.TestCase):
    def test_real_runtime_client_seal_and_observe_do_not_invent_exit(self):
        from tongjianyun import business_agent_worker as worker
        from tongjianyun.business_agent_tasks import TaskIdentity, WorkerClaim
        with tempfile.TemporaryDirectory() as folder:
            site = launcher.Site(SITE.name, Path(folder).resolve(), 1000, 1000)
            service = launcher.Launcher({site.name: site}, native_sandbox, MemoryLedger())
            runtime = worker.UnixLauncherRuntime(site=site.name, sites_path=site.sites_path)
            identity = TaskIdentity(site.name, 'teacher@example.invalid', TASK)
            class Channel:
                def __init__(self):
                    self.lease = object()
                def call(self, value):
                    return service.request(value, PEER, self.lease)
                def close(self):
                    service.disconnect(self.lease)
            with (mock.patch.object(worker, '_ControlChannel', Channel),
                  mock.patch.object(launcher, 'system_unit', return_value=inactive()),
                  mock.patch.object(Path, 'exists', return_value=False),
                  mock.patch.object(launcher.os.path, 'lexists', return_value=False)):
                proof = runtime.seal_before_start(identity, CLAIM)
                self.assertEqual(proof.state, 'never_started_and_sealed')
                self.assertIsNone(proof.exit_code)
                self.assertFalse(proof.turn_completed)
                self.assertTrue(proof.lease_closed)
                self.assertEqual(runtime.observe(identity, CLAIM), proof)
                with self.assertRaises(FileExistsError):
                    runtime.bind(WorkerClaim(identity, CLAIM, 'synthetic-claim-token'))

    def test_real_runtime_client_exact_protocol_end_to_end_without_process(self):
        from tongjianyun import business_agent_worker as worker
        from tongjianyun.business_agent_tasks import TaskIdentity, WorkerClaim
        from tongjianyun.business_agent_events import CodexEventProjector
        with tempfile.TemporaryDirectory() as folder:
            site = launcher.Site(SITE.name, Path(folder).resolve(), 1000, 1000)
            service = launcher.Launcher({site.name: site}, native_sandbox, MemoryLedger())
            runtime = worker.UnixLauncherRuntime(site=site.name, sites_path=site.sites_path)
            claim = WorkerClaim(TaskIdentity(site.name, 'teacher@example.invalid', TASK), CLAIM, 'not-a-real-claim-token')
            class Channel:
                def __init__(self):
                    self.lease = object()
                def call(self, value):
                    return service.request(value, PEER, self.lease)
                def close(self):
                    service.disconnect(self.lease)
            payload = b''.join(json.dumps(event).encode() + b'\n' for event in (
                {'type': 'thread.started', 'thread_id': 'synthetic-thread'}, {'type': 'turn.started'},
                {'type': 'item.completed', 'item': {'id': 'answer', 'type': 'agent_message', 'text': '2 students'}},
                {'type': 'turn.completed'}))
            def fake_start(task, value):
                self.assertEqual(value['proxy_path'], str(site.proxy_path(TASK)))
                task.process = mock.Mock()
                task.process.poll.return_value = 0
                task.stdout_eof = task.stderr_eof = True
                task.stdout.extend(payload)
                task.record['stage'] = 'started'
            info = mock.Mock(st_mode=stat.S_IFSOCK | 0o600, st_uid=1000)
            with (mock.patch.object(worker, '_ControlChannel', Channel),
                  mock.patch.object(worker, 'private_directory'),
                  mock.patch.object(worker.os, 'geteuid', return_value=1000, create=True),
                  mock.patch.object(Path, 'lstat', return_value=info),
                  mock.patch.object(Path, 'exists', return_value=False),
                  mock.patch.object(launcher.Task, 'start', fake_start),
                  mock.patch.object(launcher, 'system_unit', return_value=inactive()),
                  mock.patch.object(launcher, 'fixed_stop')):
                self.assertTrue(runtime.ready())
                runtime.bind(claim)
                runtime.start(claim, prompt=b'synthetic', proxy_path=site.proxy_path(TASK), token='x' * 43)
                frame = runtime.poll(claim)
                self.assertEqual(frame.stdout, payload)
                self.assertEqual(frame.state, 'exited')
                projector = CodexEventProjector(lambda event: None)
                projector.feed(frame.stdout)
                runtime.record_projection(claim, projector.finish_input())
                proof = runtime.observe(claim.identity, claim.claim_id)
                self.assertTrue(proof.turn_completed)
                self.assertFalse(proof.lease_closed)
                runtime.stop(claim)
                runtime.close(claim)
                after = runtime.observe(claim.identity, claim.claim_id)
                self.assertTrue(after.lease_closed)
                other_runtime = worker.UnixLauncherRuntime.__new__(worker.UnixLauncherRuntime)
                other_runtime.site = site.name
                other_runtime.sites_path = site.sites_path
                other_runtime._bound = {}
                other_runtime._projections = {}
                self.assertFalse(other_runtime.observe(claim.identity, claim.claim_id).turn_completed)


@unittest.skipUnless(sys.platform == 'linux', 'Linux SO_PEERCRED/O_PATH filesystem semantics')
class LinuxTests(unittest.TestCase):
    def test_seal_persisted_across_new_ledger_and_fsync_before_read_ack(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            ledger = launcher.Tombstones(directory)
            record = ledger.reserve(SITE.name, TASK, CLAIM, sealed=True)
            self.assertEqual(stat.S_IMODE(ledger.path(TASK).stat().st_mode), 0o600)
            restored = launcher.Tombstones(directory)
            with (mock.patch.object(launcher, 'root_path', side_effect=lambda path, **_: path),
                  mock.patch.object(launcher.os, 'fsync', wraps=os.fsync) as sync):
                self.assertEqual(restored.load(TASK), record)
                self.assertEqual(sync.call_count, 2)  # File and parent directory.
                with (mock.patch.object(launcher.os, 'fsync', side_effect=OSError('not durable')),
                      self.assertRaises(OSError)):
                    restored.load(TASK)
            with self.assertRaises(FileExistsError):
                restored.reserve(SITE.name, TASK, CLAIM)
            record['proof']['exit_code'] = 0
            ledger.update(record)
            with mock.patch.object(launcher, 'root_path', side_effect=lambda path, **_: path), self.assertRaises(ValueError):
                restored.load(TASK)

    def test_socket_inode_pinning_survives_basename_swap(self):
        # Rootless synthetic Unix socket; bypass only ancestor ownership fixture
        # setup, not the production socket-fd connector or SO_PEERCRED check.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'proxy.sock'
            original = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            original.bind(str(path))
            original.listen(1)
            descriptor = os.open(path, os.O_PATH | os.O_NOFOLLOW)
            pinned = launcher.PinnedProxy.__new__(launcher.PinnedProxy)
            pinned.site = launcher.Site('qa.localhost', Path(folder), os.geteuid(), os.getegid())
            pinned.lock = threading.Lock()
            pinned.fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
            pinned.socket_fd = descriptor
            info = os.fstat(descriptor)
            pinned.inode = (info.st_dev, info.st_ino)
            path.rename(Path(folder) / 'original.sock')
            replacement.bind(str(path))
            replacement.listen(1)
            replacement.settimeout(0.1)
            try:
                connected = pinned.connect()
                accepted, _ = original.accept()
                connected.sendall(b'original-only')
                self.assertEqual(accepted.recv(32), b'original-only')
                with self.assertRaises(socket.timeout):
                    replacement.accept()
                accepted.close()
                connected.close()
            finally:
                pinned.close()
                original.close()
                replacement.close()

    def test_private_tombstone_exclusive_and_secret_free(self):
        with tempfile.TemporaryDirectory() as folder:
            ledger = launcher.Tombstones(Path(folder))
            record = ledger.reserve(SITE.name, TASK, CLAIM)
            with self.assertRaises(FileExistsError):
                ledger.reserve(SITE.name, TASK, OTHER)
            self.assertEqual(stat.S_IMODE(ledger.path(TASK).stat().st_mode), 0o600)
            self.assertNotIn('token', ledger.path(TASK).read_text())
            record['stage'] = 'closed'
            ledger.update(record)
            with mock.patch.object(launcher, 'root_path', side_effect=lambda path, **_: path):
                self.assertEqual(ledger.load(TASK)['stage'], 'closed')


if __name__ == '__main__':
    unittest.main()
