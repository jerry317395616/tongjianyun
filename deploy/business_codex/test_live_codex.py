"""Pure local tests: no root, network, database, model or system service execution."""
import importlib.util
from contextlib import nullcontext
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('live_codex_acceptance', Path(__file__).with_name('check_live_codex.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
UUID = '72c25760-b7bb-4430-ab8a-055f557d7941'
NONCE = 'a' * 32
TOKEN = 't' * 43


class LiveCodexGuards(unittest.TestCase):
    def test_wrong_qa_configuration_stops_before_fixture_access(self):
        with patch.object(runner.qa, 'config_guard', side_effect=AssertionError), \
                patch.object(runner.qa, 'safe_target') as read, self.assertRaises(AssertionError):
            runner.fixture_guard()
        read.assert_not_called()

    def test_optimized_python_rejected_before_assertion_guards(self):
        with patch.object(runner.sys, 'flags', SimpleNamespace(optimize=1)), \
                patch.object(runner.qa, 'config_guard') as guard, self.assertRaises(RuntimeError):
            runner.fixture_guard()
        guard.assert_not_called()

    def test_fixture_all_four_fields_are_pinned(self):
        fixture = {'owner': runner.qa.TASK, 'site': runner.qa.SITE, 'teacher': runner.TEACHER, 'group': runner.GROUP}
        for field in fixture:
            read = MagicMock()
            read.read_text.return_value = json.dumps({**fixture, field: 'different'})
            with self.subTest(field=field), patch.object(runner.qa, 'config_guard'), \
                    patch.object(runner.qa, 'safe_target', return_value=read), self.assertRaises(PermissionError):
                runner.fixture_guard()

    def test_non_root_refused_before_runtime_file_or_subprocess_access(self):
        with patch.object(runner.os, 'name', 'posix'), patch.object(runner.os, 'geteuid', return_value=1000, create=True), \
                patch.object(runner, 'root_path') as path, self.assertRaises(PermissionError):
            runner.runtime_guard()
        path.assert_not_called()

    def test_marker_prevents_prepare_and_execution_without_context_or_model(self):
        marker = MagicMock()
        marker.exists.return_value = True
        for operation in (runner.prepare, runner.execute):
            with self.subTest(operation=operation.__name__), patch.object(runner, 'fixture_guard'), \
                    patch.object(runner, 'runtime_guard'), patch.object(runner, 'MARKER', marker), \
                    patch.object(runner, 'attempt_lock', return_value=nullcontext()), \
                    patch.object(runner, 'run_internal') as child, patch.object(runner, 'load_module') as load, \
                    self.assertRaises(RuntimeError):
                operation()
            child.assert_not_called()
            load.assert_not_called()

    def test_prepare_is_separate_and_never_loads_or_executes_model(self):
        marker = MagicMock()
        marker.exists.return_value = False
        with patch.object(runner, 'fixture_guard'), patch.object(runner, 'runtime_guard', return_value={'codex': 'hash'}), \
                patch.object(runner, 'attempt_lock', return_value=nullcontext()), \
                patch.object(runner, 'source_hashes', return_value={'script': 'hash'}), \
                patch.object(runner, 'MARKER', marker), patch.object(runner, 'run_internal',
                    return_value={'ready': True, 'student_count': 2, 'protected_digest': 'hash'}), \
                patch.object(runner, 'read_model_key', return_value='not-returned'), \
                patch.object(runner.qa, 'private_json') as persist, patch.object(runner, 'load_module') as load:
            result = runner.prepare()
        self.assertEqual(result['mode'], 'prepare-only')
        self.assertFalse(result['model_executed'])
        self.assertNotIn('not-returned', json.dumps(result))
        persist.assert_called_once()
        load.assert_not_called()

    def test_tool_allowlist_exact_scope_and_no_writes(self):
        context = {'day': runner.DAY, 'meal': runner.MEAL, 'group': runner.GROUP}
        runner.readonly_request('scene_bootstrap', context, 'bootstrap001')
        for view in ('class_students', 'classroom_day'):
            runner.readonly_request('business_view', {'selection': {'view': view, **context}, 'publish': True}, 'students001')
        for tool, args in [('save_attendance', context), ('scene_bootstrap', {**context, 'group': 'other'}),
                           ('scene_bootstrap', {**context, 'day': '2026-09-16'}),
                           ('business_view', {'selection': {'view': 'students', **context}, 'publish': True}),
                           ('business_view', {'selection': {'view': 'class_students', **context}, 'publish': False})]:
            with self.subTest(tool=tool, args=args), self.assertRaises(PermissionError):
                runner.readonly_request(tool, args, 'request0001')

    def test_subprocess_has_no_inherited_credentials_or_total_deadline(self):
        result = SimpleNamespace(returncode=0, stdout=b'{"ok":true,"data":{"authorized":true}}', stderr=b'secret')
        with patch.object(runner.subprocess, 'run', return_value=result) as run:
            self.assertTrue(runner.run_internal({'action': 'authorize', 'task_id': UUID})['authorized'])
        argv = run.call_args.args[0]
        kwargs = run.call_args.kwargs
        self.assertEqual(argv[-1], '--internal-read')
        self.assertEqual(set(kwargs['env']), {'PATH', 'LANG', 'PYTHONDONTWRITEBYTECODE'})
        self.assertNotIn('timeout', kwargs)
        self.assertNotIn('shell', kwargs)

    def test_subprocess_exception_or_stderr_not_returned(self):
        result = SimpleNamespace(returncode=1, stdout=b'secret', stderr=b'sk-secret')
        with patch.object(runner.subprocess, 'run', return_value=result), self.assertRaises(PermissionError) as raised:
            runner.run_internal({'action': 'preflight'})
        self.assertNotIn('secret', str(raised.exception))

    def test_task_uuid_namespace_and_business_mode(self):
        key = runner.task_key(UUID)
        self.assertIn('business-codex-live-qa:v1:' + runner.qa.SITE, key)
        self.assertEqual(runner.expected_task(UUID)['mode'], 'business')
        for value in ('../../other', UUID.upper(), None):
            with self.subTest(value=value), self.assertRaises((ValueError, AttributeError, TypeError)):
                runner.task_key(value)

    def test_prompt_fixed_tools_no_credentials_and_utf8_bound(self):
        prompt = runner.build_prompt(NONCE)
        self.assertTrue(1 <= len(prompt) <= 131072)
        text = prompt.decode('utf-8')
        self.assertEqual(text.count('/opt/business-codex/business_tool.py'), 2)
        self.assertIn('scene_bootstrap', text)
        self.assertIn('class_students', text)
        self.assertNotIn(str(runner.KEY_FILE), text)
        self.assertNotIn(TOKEN, text)
        with self.assertRaises(ValueError):
            runner.build_prompt("'; import os")

    def test_model_text_commands_and_secrets_are_never_retained(self):
        raw = json.dumps({'type': 'item.completed', 'thread_id': 'private', 'item': {
            'type': 'command_execution', 'exit_code': 0, 'command': TOKEN,
            'aggregated_output': 'Student Jane\nsk-private\n' + TOKEN, 'text': 'chain of thought'}}).encode()
        safe = runner.sanitize_event(raw, TOKEN, NONCE)
        self.assertEqual(safe, {'type': 'item.completed', 'item_type': 'command_execution', 'exit_code': 0})

    def test_probe_only_exact_schema_and_primitive_types(self):
        probe = {'qa_namespace_probe': NONCE, 'uid': 62500, 'seccomp': '2', 'no_new_privs': '1',
            'host_project_visible': False, 'host_etc_visible': False, 'host_docker_visible': False,
            'database_connect_error': 111}
        def sanitize(value):
            return runner.sanitize_event(json.dumps({'type': 'item.completed', 'item': {
                'type': 'command_execution', 'aggregated_output': json.dumps(value)}}).encode(), TOKEN, NONCE)
        self.assertEqual(sanitize(probe)['model_reported_probe'], probe)
        for changed in ({'uid': 'Student Jane'}, {'host_etc_visible': TOKEN}, {'no_new_privs': 'sk-private'},
                        {'database_connect_error': True}, {'qa_namespace_probe': 'other'}, {'extra': 'private'}):
            with self.subTest(changed=changed):
                self.assertNotIn('model_reported_probe', sanitize({**probe, **changed}))

    def test_unknown_or_malformed_event_fails_closed(self):
        for raw in (b'not json', b'{"type":[]}', b'{"type":"student_name"}', b'[]'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                runner.sanitize_event(raw, TOKEN, NONCE)

    def test_cleanup_redis_failure_does_not_skip_token_and_proxy_revocation(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / UUID
            directory.mkdir()
            (directory / 'token').write_text(TOKEN)
            (directory / 'prompt.txt').write_text('private')
            redis, proxy = MagicMock(), MagicMock()
            redis.hset.side_effect = RuntimeError('secret')
            proxy.model_calls = 3
            order = []
            proxy.close.side_effect = lambda: order.append('proxy')
            def stop(*args, **kwargs):
                self.assertFalse((directory / 'token').exists())
                order.append('stop')
            evidence = {'status': 'passed'}
            with patch.object(runner, 'INPUT', Path(root)), patch.object(runner.subprocess, 'run', side_effect=stop), \
                    patch.object(runner, 'unit_state', return_value={'LoadState': 'not-found'}):
                runner.cleanup_attempt(task_id=UUID, directory=directory, unit=f'tgy-business-codex-{UUID}.service',
                    runtime_directory=Path('/run') / f'tgy-business-{UUID}', redis=redis, key=runner.task_key(UUID),
                    proxy=proxy, process=None, readers=[], evidence=evidence)
            self.assertEqual(order, ['proxy', 'stop'])
            self.assertFalse(directory.exists())
            self.assertEqual(evidence['status'], 'failed_cleanup')
            self.assertNotIn('secret', json.dumps(evidence))

    def test_cleanup_stop_failure_still_removes_private_files(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / UUID
            directory.mkdir()
            (directory / 'token').write_text(TOKEN)
            (directory / 'prompt.txt').write_text('private')
            evidence = {'status': 'cancelled'}
            with patch.object(runner, 'INPUT', Path(root)), patch.object(runner.subprocess, 'run', side_effect=TimeoutError), \
                    patch.object(runner, 'unit_state', return_value={'LoadState': 'not-found'}):
                runner.cleanup_attempt(task_id=UUID, directory=directory, unit=f'tgy-business-codex-{UUID}.service',
                    runtime_directory=Path('/run') / f'tgy-business-{UUID}', redis=None, key=runner.task_key(UUID),
                    proxy=None, process=None, readers=[], evidence=evidence)
            self.assertFalse(directory.exists())
            self.assertEqual(evidence['status'], 'failed_cleanup')

    def test_cleanup_does_not_touch_existing_unowned_directory_or_unit(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / UUID
            directory.mkdir()
            (directory / 'token').write_text('belongs-to-another-attempt')
            with patch.object(runner, 'INPUT', Path(root)), patch.object(runner.subprocess, 'run') as stop, \
                    patch.object(runner, 'unit_state', return_value={'LoadState': 'not-found'}):
                runner.cleanup_attempt(task_id=UUID, directory=directory, unit=f'tgy-business-codex-{UUID}.service',
                    runtime_directory=Path('/run') / f'tgy-business-{UUID}', redis=None, key=runner.task_key(UUID),
                    proxy=None, process=None, readers=[], evidence={'status': 'failed'},
                    directory_owned=False, unit_requested=False)
            stop.assert_not_called()
            self.assertEqual((directory / 'token').read_text(), 'belongs-to-another-attempt')


class ReviewedRetryGuards(unittest.TestCase):
    def setUp(self):
        self.unit = f'tgy-business-codex-{UUID}.service'
        self.marker = {'mode': 'execute_once', 'task_id': UUID, 'site': runner.qa.SITE,
            'evidence': str(runner.qa.ROOT / f'live-codex-{UUID}.json'), 'unit': self.unit, 'broker_pid': 193456789}
        self.report = {**self.marker, 'status': 'failed', 'business_writes': False, 'production_writes': False,
            'cleanup': {'unit': self.unit, 'unit_load_state': 'not-found', 'errors': [],
                'task_token_removed': True, 'task_input_directory_removed': True,
                'dynamic_runtime_directory_removed': True, 'jsonl_readers_stopped': True}}
        self.identity = (1, 2, 3, 4)

    def reviewed(self, *, marker=None, report=None, exists=False, state=None, task=None):
        marker = self.marker if marker is None else marker
        report = self.report if report is None else report
        files = [(marker, json.dumps(marker).encode(), self.identity),
                 (report, json.dumps(report).encode(), (1, 3, 4, 5))]
        with patch.object(runner, 'read_root_json', side_effect=files), \
                patch.object(runner.Path, 'exists', return_value=exists), \
                patch.object(runner, 'unit_state', return_value=state or {'LoadState': 'not-found'}), \
                patch.object(runner, 'read_qa_task', return_value=task if task is not None else {
                    **runner.expected_task(UUID), 'status': 'failed', 'cancel_requested': '1'}):
            return runner.review_retry({}, UUID, 'bwrap-startup-fixed')

    def test_only_explicit_fully_verified_retry_succeeds(self):
        result = self.reviewed()
        self.assertEqual(result['metadata']['retry_of'], UUID)
        self.assertEqual(result['metadata']['review_reason'], 'bwrap-startup-fixed')
        self.assertEqual(result['raw_marker'], json.dumps(self.marker).encode())
        self.assertEqual(len(result['metadata']['previous_evidence_sha256']), 64)

    def test_wrong_uuid_site_path_mode_or_unit_refused(self):
        for field in ('task_id', 'site', 'evidence', 'mode', 'unit'):
            with self.subTest(field=field), self.assertRaises(PermissionError):
                self.reviewed(marker={**self.marker, field: 'other'})

    def test_nonterminal_success_cancel_or_uncertain_cleanup_refused(self):
        for status in ('running', 'starting', 'passed', 'cancelled', 'failed_cleanup', None):
            with self.subTest(status=status), self.assertRaises(PermissionError):
                self.reviewed(report={**self.report, 'status': status})

    def test_any_cleanup_gap_or_write_disallows_retry(self):
        for field in ('task_token_removed', 'task_input_directory_removed',
                      'dynamic_runtime_directory_removed', 'jsonl_readers_stopped'):
            report = {**self.report, 'cleanup': {**self.report['cleanup'], field: False}}
            with self.subTest(field=field), self.assertRaises(PermissionError):
                self.reviewed(report=report)
        for field in ('business_writes', 'production_writes'):
            with self.subTest(field=field), self.assertRaises(PermissionError):
                self.reviewed(report={**self.report, field: True})
        with self.assertRaises(PermissionError):
            self.reviewed(report={**self.report, 'cleanup': {**self.report['cleanup'], 'errors': ['unknown']}})

    def test_live_pid_or_unit_or_unrevoked_task_refused_without_killing(self):
        with patch.object(runner.subprocess, 'run') as command:
            for arguments in ({'exists': True}, {'state': {'LoadState': 'loaded'}},
                              {'task': runner.expected_task(UUID)}, {'task': {}}):
                with self.subTest(arguments=arguments), self.assertRaises(PermissionError):
                    self.reviewed(**arguments)
        command.assert_not_called()

    def test_reason_requires_exact_uuid_and_fixed_code(self):
        for previous, reason in ((None, 'bwrap-startup-fixed'), (UUID, None), (UUID, 'arbitrary secret'),
                                 ('../other', 'bwrap-startup-fixed')):
            with self.subTest(previous=previous, reason=reason), self.assertRaises(ValueError):
                runner.review_retry({}, previous, reason)

    def test_prepare_reviews_but_does_not_archive_or_reserve(self):
        retry = {'metadata': {'retry_of': UUID, 'review_reason': 'bwrap-startup-fixed'}}
        with patch.object(runner, 'fixture_guard', return_value={}), patch.object(runner, 'runtime_guard', return_value={}), \
                patch.object(runner, 'attempt_lock', return_value=nullcontext()), \
                patch.object(runner, 'review_retry', return_value=retry) as review, \
                patch.object(runner, 'source_hashes', return_value={}), \
                patch.object(runner, 'run_internal', return_value={'ready': True, 'student_count': 2}), \
                patch.object(runner, 'read_model_key'), patch.object(runner.qa, 'private_json'), \
                patch.object(runner, 'reserve_marker') as reserve, patch.object(runner, 'private_create') as create:
            result = runner.prepare(UUID, 'bwrap-startup-fixed')
        self.assertEqual(result['reviewed_retry'], retry['metadata'])
        review.assert_called_once_with({}, UUID, 'bwrap-startup-fixed')
        self.assertFalse(result['model_executed'])
        reserve.assert_not_called()
        create.assert_not_called()

    def test_marker_archive_preserves_bytes_and_original_report(self):
        new_id = '51c821ea-1dd1-4d99-86b7-5f61ed0d89ba'
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            marker = root / 'current.json'
            old_raw = json.dumps(self.marker, indent=2).encode()
            marker.write_bytes(old_raw)
            old_report = root / f'live-codex-{UUID}.json'
            old_report.write_bytes(b'original failure evidence')
            retry = {'raw_marker': old_raw, 'identity': self.identity, 'metadata': {'retry_of': UUID}}
            with patch.object(runner.qa, 'ROOT', root), patch.object(runner, 'MARKER', marker), \
                    patch.object(runner.qa, 'safe_target', side_effect=lambda path: path), \
                    patch.object(runner, 'private_create', side_effect=lambda path, raw: path.write_bytes(raw)), \
                    patch.object(runner, 'read_root_json', return_value=(self.marker, old_raw, self.identity)), \
                    patch.object(runner.os, 'O_DIRECTORY', 0, create=True), \
                    patch.object(runner.os, 'open', return_value=999), patch.object(runner.os, 'fsync'), \
                    patch.object(runner.os, 'close'):
                runner.reserve_marker({'task_id': new_id, 'reviewed_retry': retry['metadata']}, retry)
            self.assertEqual((root / f'live-codex-marker-{UUID}.json').read_bytes(), old_raw)
            self.assertEqual(old_report.read_bytes(), b'original failure evidence')
            self.assertEqual(json.loads(marker.read_bytes())['task_id'], new_id)

    def test_changed_current_marker_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            marker = root / 'current.json'
            marker.write_bytes(b'changed attempt')
            retry = {'raw_marker': b'old marker', 'identity': self.identity, 'metadata': {'retry_of': UUID}}
            with patch.object(runner.qa, 'ROOT', root), patch.object(runner, 'MARKER', marker), \
                    patch.object(runner.qa, 'safe_target', side_effect=lambda path: path), \
                    patch.object(runner, 'private_create', side_effect=lambda path, raw: path.write_bytes(raw)), \
                    patch.object(runner, 'read_root_json', return_value=({}, b'changed attempt', self.identity)), \
                    patch.object(runner.os, 'replace') as replace, self.assertRaises(PermissionError):
                runner.reserve_marker({'task_id': '51c821ea-1dd1-4d99-86b7-5f61ed0d89ba'}, retry)
            replace.assert_not_called()
            self.assertEqual(marker.read_bytes(), b'changed attempt')


class CancellationCaseGuards(unittest.TestCase):
    def test_cancellation_result_reuses_external_stop_evidence_not_exit_code(self):
        evidence = {'status': 'cancelled', 'process_exit_code': 0}
        proof = {'cancellation_verified': True, 'checks': {'pid1_ordered_stop_job': True}}
        with patch('check_cancellation_evidence.observe', return_value=proof) as observe:
            runner.record_cancellation_evidence(evidence)
        observe.assert_called_once_with(evidence)
        self.assertTrue(evidence['cancellation_check_passed'])
        self.assertEqual(evidence['cancellation_evidence'], proof)
        self.assertEqual(evidence['status'], 'cancelled')

    def test_cancellation_exit_code_never_overrides_negative_or_missing_proof(self):
        for exit_code in (0, 143, None):
            for proof in ({'cancellation_verified': False}, {}, {'cancellation_verified': 1}):
                with self.subTest(exit_code=exit_code, proof=proof):
                    evidence = {'status': 'cancelled', 'process_exit_code': exit_code}
                    with patch('check_cancellation_evidence.observe', return_value=proof):
                        runner.record_cancellation_evidence(evidence)
                    self.assertFalse(evidence['cancellation_check_passed'])

    def test_cancellation_evidence_observation_failure_fails_closed(self):
        evidence = {'status': 'cancelled', 'process_exit_code': 0, 'cancellation_check_passed': True}
        with patch('check_cancellation_evidence.observe', side_effect=RuntimeError('journal unavailable')), \
                self.assertRaises(RuntimeError):
            runner.record_cancellation_evidence(evidence)
        self.assertFalse(evidence['cancellation_check_passed'])

    def test_cancel_trigger_rechecks_actual_process_not_old_watchdog_identity(self):
        process = MagicMock()
        process.poll.return_value = 0
        with patch.object(runner, 'actual_codex_identity') as inspect:
            self.assertIsNone(runner.cancellation_trigger(UUID, process, []))
        inspect.assert_not_called()

    def test_cancel_trigger_rejects_exit_during_identity_check(self):
        process = MagicMock()
        process.poll.side_effect = [None, 0]
        identity = {'dynamic_uid': True, 'binary_inode_matches_reviewed_runtime': True}
        with patch.object(runner, 'actual_codex_identity', return_value=identity):
            self.assertIsNone(runner.cancellation_trigger(UUID, process, []))

    def test_cancel_trigger_requires_live_reviewed_codex_without_terminal_event(self):
        process = MagicMock()
        process.poll.return_value = None
        identity = {'dynamic_uid': True, 'binary_inode_matches_reviewed_runtime': True}
        with patch.object(runner, 'actual_codex_identity', return_value=identity):
            self.assertEqual(runner.cancellation_trigger(UUID, process, []), identity)
            for terminal in ('turn.completed', 'turn.failed'):
                self.assertIsNone(runner.cancellation_trigger(UUID, process, [{'type': terminal}]))
        with patch.object(runner, 'actual_codex_identity', return_value=None):
            self.assertIsNone(runner.cancellation_trigger(UUID, process, []))

    def invoke(self, args, result, *, operation='execute'):
        seen = {}
        def run(*values, **options):
            seen.update(marker=runner.MARKER, prepared=runner.PREPARED, values=values, options=options)
            return result
        with patch.object(runner.sys, 'argv', ['check_live_codex.py', *args]), \
                patch.object(runner, 'MARKER', runner.MARKER), patch.object(runner, 'PREPARED', runner.PREPARED), \
                patch.object(runner, operation, side_effect=run), patch('builtins.print'):
            code = runner.main()
        return code, seen

    def test_cancellation_prepare_has_own_marker_and_does_not_execute(self):
        with patch.object(runner, 'execute') as execute:
            code, seen = self.invoke(['--cancel-check'], {'ready': True}, operation='prepare')
        self.assertEqual(code, 0)
        self.assertEqual(seen['marker'].name, 'live-codex-cancel-execute-once-20260925.json')
        self.assertEqual(seen['prepared'].name, 'live-codex-cancel-prepare-only-20260925.json')
        execute.assert_not_called()

    def test_explicit_cancel_case_only_passes_actual_cancellation_check(self):
        for result, expected in (({'status': 'cancelled', 'cancellation_check_passed': True}, 0),
                                 ({'status': 'cancelled'}, 1), ({'status': 'passed'}, 1),
                                 ({'status': 'failed_cleanup', 'cancellation_check_passed': False}, 1)):
            with self.subTest(result=result):
                code, seen = self.invoke(['--run', '--cancel-check'], result)
                self.assertEqual(code, expected)
                self.assertIs(seen['options']['cancel_after_first_tool'], True)

    def test_normal_query_has_no_cancellation_trigger_and_original_marker(self):
        original = runner.MARKER
        code, seen = self.invoke(['--run'], {'status': 'passed'})
        self.assertEqual(code, 0)
        self.assertEqual(seen['marker'], original)
        self.assertIs(seen['options']['cancel_after_first_tool'], False)

    def test_internal_child_cannot_select_cancellation_case(self):
        with patch.object(runner.sys, 'argv', ['check_live_codex.py', '--internal-read', '--cancel-check']), \
                patch.object(runner, 'internal_request') as request, patch('builtins.print'):
            self.assertEqual(runner.main(), 1)
        request.assert_not_called()

    def test_invalid_programmatic_mode_fails_before_preflight_or_model(self):
        with patch.object(runner, 'run_internal') as read, self.assertRaises(ValueError):
            runner.execute_locked({}, {}, None, cancel_after_first_tool='yes')
        read.assert_not_called()


if __name__ == '__main__':
    unittest.main()
