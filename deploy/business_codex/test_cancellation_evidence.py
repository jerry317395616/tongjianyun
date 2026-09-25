"""Pure cancellation evidence tests; no root, model, journal or business access."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import check_cancellation_evidence as review

TASK = 'f7fbb769-95bb-4293-be40-998599415585'
UNIT = 'tgy-business-codex-' + TASK + '.service'


def report_fixture():
    return {'task_id': TASK, 'site': review.live.qa.SITE, 'mode': 'execute_once', 'unit': UNIT,
        'status': 'cancelled', 'acceptance_case': 'explicit-cancellation',
        'explicit_cancellation_exercised': True, 'cancel_trigger_process_unexited': True,
        'cancel_trigger_identity': {'pid': 424242, 'uid': 64512, 'dynamic_uid': True,
            'non_root_non_site_owner': True, 'capabilities_empty': True,
            'binary_inode_matches_reviewed_runtime': True, 'seccomp': '2', 'no_new_privs': '1'},
        'tool_calls': [{'tool': 'scene_bootstrap', 'success': True}], 'model_calls': 2,
        'jsonl_events': [{'type': 'thread.started'}, {'type': 'turn.started'}], 'malformed_jsonl_events': 0,
        'process_exit_code': 0, 'protected_business_digest_unchanged': True,
        'business_writes': False, 'production_writes': False,
        'cleanup': {'unit': UNIT, 'unit_load_state': 'not-found', 'errors': [],
            'task_token_removed': True, 'task_input_directory_removed': True,
            'dynamic_runtime_directory_removed': True, 'jsonl_readers_stopped': True}}


def journal_fixture():
    common = {'_PID': '1', '_UID': '0', '_COMM': 'systemd', '_EXE': '/usr/lib/systemd/systemd',
        '_TRANSPORT': 'journal', '_SYSTEMD_UNIT': 'init.scope', '_SYSTEMD_CGROUP': '/init.scope',
        '_BOOT_ID': 'b' * 32, '_MACHINE_ID': 'c' * 32, 'INVOCATION_ID': 'd' * 32, 'UNIT': UNIT}
    return [{**common, **row, '__MONOTONIC_TIMESTAMP': str(100 + index),
             '__REALTIME_TIMESTAMP': str(200 + index)} for index, row in enumerate([
        {'MESSAGE_ID': review.STARTED, 'JOB_ID': '101', 'JOB_TYPE': 'start', 'JOB_RESULT': 'done'},
        {'MESSAGE_ID': review.STOPPING, 'JOB_ID': '102', 'JOB_TYPE': 'stop'},
        {'MESSAGE_ID': review.DEACTIVATED},
        {'MESSAGE_ID': review.STOPPED, 'JOB_ID': '102', 'JOB_TYPE': 'stop', 'JOB_RESULT': 'done'}])]


class CancellationAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.report, self.journal = report_fixture(), journal_fixture()

    def assess(self, **resources):
        return review.assess(self.report, self.journal, **{'unit_absent': True, 'pid_absent': True,
            'cgroup_absent': True, 'inputs_absent': True, **resources})

    def test_zero_client_exit_requires_and_accepts_pid1_ordered_explicit_stop(self):
        result = self.assess()
        self.assertTrue(result['cancellation_verified'])
        self.assertEqual(result['task_status'], 'cancelled')
        self.assertEqual(result['client_exit_code'], 0)
        self.assertEqual(len(result['journal_stop_sequence']), 4)

    def test_nonzero_client_exit_alone_never_proves_cancel(self):
        self.report['process_exit_code'] = 143
        self.journal = []
        self.assertFalse(self.assess()['cancellation_verified'])

    def test_natural_completion_then_cleanup_stop_is_not_cancel(self):
        for terminal in ('turn.completed', 'turn.failed'):
            with self.subTest(terminal=terminal):
                self.report['jsonl_events'] = [{'type': 'turn.started'}, {'type': terminal}]
                self.assertFalse(self.assess()['cancellation_verified'])
        self.report = report_fixture()
        self.journal[1]['__MONOTONIC_TIMESTAMP'] = '104'  # Deactivation precedes the stop request.
        self.assertFalse(self.assess()['cancellation_verified'])

    def test_report_identity_case_and_trigger_must_be_exact(self):
        for field, value in (('task_id', 'b7fbb769-95bb-4293-be40-998599415585'), ('site', 'other.localhost'),
                ('mode', 'admin_project'), ('unit', UNIT + '.other'), ('acceptance_case', 'readonly-query'),
                ('status', 'passed'), ('explicit_cancellation_exercised', False), ('cancel_trigger_process_unexited', False)):
            with self.subTest(field=field):
                self.report = {**report_fixture(), field: value}
                self.assertFalse(self.assess()['cancellation_verified'])

    def test_missing_identity_or_boundary_proof_never_passes(self):
        for field, value in (('pid', 1), ('pid', True), ('uid', 0), ('uid', True), ('dynamic_uid', False),
                ('non_root_non_site_owner', False), ('capabilities_empty', False),
                ('binary_inode_matches_reviewed_runtime', False), ('seccomp', '0'), ('no_new_privs', '0')):
            with self.subTest(field=field):
                self.report = report_fixture()
                self.report['cancel_trigger_identity'][field] = value
                self.assertFalse(self.assess()['cancellation_verified'])

    def test_real_tool_and_model_not_only_claimed_text_required(self):
        for tools in ([], [{'tool': 'scene_bootstrap', 'success': False}], [{'tool': 'other', 'success': True}], ['fake']):
            with self.subTest(tools=tools):
                self.report = {**report_fixture(), 'tool_calls': tools}
                self.assertFalse(self.assess()['cancellation_verified'])
        for count in (0, True, '2'):
            self.report = {**report_fixture(), 'model_calls': count}
            self.assertFalse(self.assess()['cancellation_verified'])

    def test_truncated_malformed_or_missing_jsonl_lifecycle_fails_closed(self):
        for changed in ({'jsonl_events': []}, {'jsonl_events': None}, {'jsonl_events': ['bad']},
                        {'malformed_jsonl_events': 1}, {'malformed_jsonl_events': False},
                        {'jsonl_events': [{'type': 'turn.started'}] * review.live.MAX_EVENTS},
                        {'process_exit_code': None}, {'process_exit_code': True}):
            with self.subTest(changed=list(changed)):
                self.report = {**report_fixture(), **changed}
                self.assertFalse(self.assess()['cancellation_verified'])

    def test_forged_pid_uid_transport_executable_or_unit_journal_cannot_prove_stop(self):
        for field, value in (('_PID', '22'), ('_UID', '1000'), ('_COMM', 'python'), ('_EXE', '/tmp/systemd'),
                ('_TRANSPORT', 'stdout'), ('_SYSTEMD_UNIT', UNIT), ('_SYSTEMD_CGROUP', '/user.slice'), ('UNIT', 'other.service')):
            with self.subTest(field=field):
                self.journal = journal_fixture()
                self.journal[1][field] = value
                self.assertFalse(self.assess()['cancellation_verified'])

    def test_message_text_is_never_stop_evidence(self):
        self.journal[1].pop('MESSAGE_ID')
        self.journal[1]['MESSAGE'] = 'Stopping ' + UNIT
        self.assertFalse(self.assess()['cancellation_verified'])

    def test_duplicate_lifecycle_or_missing_event_is_ambiguous(self):
        for index in range(4):
            with self.subTest(index=index):
                self.journal = journal_fixture()
                self.journal.append(deepcopy(self.journal[index]))
                self.assertFalse(self.assess()['cancellation_verified'])
                self.journal = journal_fixture()
                self.journal.pop(index)
                self.assertFalse(self.assess()['cancellation_verified'])

    def test_mixed_boot_host_invocation_or_stop_job_cannot_be_combined(self):
        for field, value in (('_BOOT_ID', 'a' * 32), ('_MACHINE_ID', 'a' * 32),
                             ('INVOCATION_ID', 'a' * 32), ('JOB_ID', '999'), ('JOB_RESULT', 'failed')):
            with self.subTest(field=field):
                self.journal = journal_fixture()
                self.journal[-1][field] = value
                self.assertFalse(self.assess()['cancellation_verified'])

    def test_monotonic_sequence_not_wall_clock_or_supplied_array_order(self):
        self.journal.reverse()
        for index, row in enumerate(self.journal):
            row['__REALTIME_TIMESTAMP'] = str(index)
        self.assertTrue(self.assess()['cancellation_verified'])
        for stamp in ('100', 'not-a-time', None, 102):
            self.journal = journal_fixture()
            self.journal[2]['__MONOTONIC_TIMESTAMP'] = stamp
            self.assertFalse(self.assess()['cancellation_verified'])

    def test_malformed_journal_metadata_fails_closed(self):
        for field in ('MESSAGE_ID', '_EXE', '_BOOT_ID', 'INVOCATION_ID'):
            with self.subTest(field=field):
                self.journal = journal_fixture()
                self.journal[1][field] = []
                self.assertFalse(self.assess()['cancellation_verified'])
        self.journal = journal_fixture() * 17
        self.assertFalse(self.assess()['cancellation_verified'])

    def test_any_live_resource_or_cleanup_gap_prevents_acceptance(self):
        for field in ('unit_absent', 'pid_absent', 'cgroup_absent', 'inputs_absent'):
            with self.subTest(field=field):
                self.assertFalse(self.assess(**{field: False})['cancellation_verified'])
        for field in ('task_token_removed', 'task_input_directory_removed', 'dynamic_runtime_directory_removed', 'jsonl_readers_stopped'):
            self.report = report_fixture()
            self.report['cleanup'][field] = False
            self.assertFalse(self.assess()['cancellation_verified'])
        self.report = report_fixture()
        self.report['cleanup']['errors'] = [{'stage': 'stop'}]
        self.assertFalse(self.assess()['cancellation_verified'])

    def test_business_mutation_or_changed_digest_prevents_acceptance(self):
        for changed in ({'business_writes': True}, {'production_writes': True}, {'protected_business_digest_unchanged': False}):
            self.report = {**report_fixture(), **changed}
            self.assertFalse(self.assess()['cancellation_verified'])


class CancellationReviewGuards(unittest.TestCase):
    def test_observer_reads_only_exact_unit_journal_and_resources(self):
        report = report_fixture()
        completed = SimpleNamespace(stdout=b'\n'.join(json.dumps(row).encode() for row in journal_fixture()))
        with patch.object(review.subprocess, 'run', return_value=completed) as command, \
                patch.object(review.live, 'unit_state', return_value={'LoadState': 'not-found'}) as unit, \
                patch.object(review, '_absent', return_value=True) as absent:
            result = review.observe(report)
        self.assertTrue(result['cancellation_verified'])
        self.assertEqual(command.call_args.args[0], ['/usr/bin/journalctl', '--unit=' + UNIT,
                         '--no-pager', '--output=json', '-n', '64'])
        self.assertNotIn('shell', command.call_args.kwargs)
        unit.assert_called_once_with(UNIT)
        self.assertEqual([call.args[0] for call in absent.call_args_list], [Path('/proc/424242'),
            Path('/sys/fs/cgroup/system.slice') / UNIT, review.live.INPUT / TASK, Path('/run') / ('tgy-business-' + TASK)])

    def test_journal_failure_size_or_missing_pid_never_passes(self):
        for raw in (b'x' * 262145, b'not json'):
            with patch.object(review.subprocess, 'run', return_value=SimpleNamespace(stdout=raw)), self.assertRaises(ValueError):
                review.observe(report_fixture())
        report = report_fixture()
        report['cancel_trigger_identity'].pop('pid')
        with patch.object(review.subprocess, 'run', return_value=SimpleNamespace(stdout=b'')), self.assertRaises(ValueError):
            review.observe(report)

    def test_broken_symlink_is_a_residual_resource(self):
        with tempfile.TemporaryDirectory() as name:
            missing = Path(name) / 'missing'
            self.assertTrue(review._absent(missing))
            with patch.object(Path, 'exists', return_value=False), patch.object(Path, 'is_symlink', return_value=True):
                self.assertFalse(review._absent(missing))

    def test_review_preserves_original_false_report_and_writes_separate_evidence_only(self):
        report = {**report_fixture(), 'cancellation_check_passed': False}
        raw = json.dumps(report).encode()
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            original = root / ('live-codex-' + TASK + '.json')
            with patch.object(review.live.qa, 'ROOT', root), patch.object(review.live, 'fixture_guard') as fixture, \
                    patch.object(review.live, 'read_root_json', return_value=(report, raw, (1, 2, 3, 4))) as read, \
                    patch.object(review, 'observe', return_value={'cancellation_verified': True}), \
                    patch.object(review.live.qa, 'digest_file', return_value='reviewer-hash'), \
                    patch.object(review.live.qa, 'safe_target', side_effect=lambda path: path), \
                    patch.object(review.live, 'private_create') as create:
                result = review.review(TASK)
            self.assertFalse(report['cancellation_check_passed'])
            self.assertEqual(result['original_report_sha256'], hashlib.sha256(raw).hexdigest())
            self.assertFalse(result['model_executed'])
            self.assertFalse(result['original_report_modified'])
            self.assertEqual(read.call_count, 2)
            self.assertTrue(all(call.args[0] == original for call in read.call_args_list))
            create.assert_called_once()
            self.assertNotEqual(create.call_args.args[0], original)
            self.assertTrue(create.call_args.args[0].name.startswith('live-codex-cancel-review-' + TASK))
            fixture.assert_called_once_with()

    def test_changed_original_or_wrong_identity_does_not_write_review(self):
        for wrong in ('changed', 'identity'):
            report = report_fixture()
            if wrong == 'identity':
                report['site'] = 'other.localhost'
            with patch.object(review.live, 'fixture_guard'), patch.object(review.live, 'read_root_json',
                    side_effect=[(report, b'original', ()), (report, b'changed', ())]), \
                    patch.object(review, 'observe', return_value={}), patch.object(review.live, 'private_create') as create, \
                    self.assertRaises(PermissionError):
                review.review(TASK)
            create.assert_not_called()


if __name__ == '__main__':
    unittest.main()
