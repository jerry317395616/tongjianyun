"""Pure guards for the live-worker checker; never start a model or a database.

The run-wiring tests deliberately replace the runtime/worker/authority with
sentinels. They verify the acceptance SCRIPT, not live runtime correctness.
"""
from contextlib import ExitStack, contextmanager
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from tongjianyun.business_agent_tasks import TaskIdentity, QueueObservation, ExecutionObservation


SPEC = importlib.util.spec_from_file_location('worker_live_guard_checker',
    Path(__file__).with_name('check_worker_live.py'))
checker = importlib.util.module_from_spec(SPEC)
_paths = list(sys.path)
try:
    SPEC.loader.exec_module(checker)
finally:
    sys.path[:] = _paths


def module(name, **attributes):
    value = ModuleType(name)
    value.__dict__.update(attributes)
    return value


class CheckerGuardTests(unittest.TestCase):
    def test_source_evidence_includes_executed_fixture_and_projection_dependencies(self):
        self.assertLessEqual({'deploy/business_codex/check_worker_live.py',
            'deploy/business_codex/check_live_codex.py', 'deploy/unified_business/serve_isolated_browser.py',
            'tongjianyun/attendance_scope.py', 'tongjianyun/meal_chat_events.py',
            'tongjianyun/business_agent_authority.py', 'tongjianyun/business_agent_events.py'},
            set(checker.SOURCE_FILES))

    @contextmanager
    def harness(self):
        """Isolated synthetic Python objects, no Frappe/runtime/model imports."""
        with tempfile.TemporaryDirectory() as name, ExitStack() as stack:
            root = Path(name).resolve()
            sites = root / 'sites'
            (sites / checker.qa.SITE / 'private').mkdir(parents=True)
            trace, evidence, workers, proxies = [], [], [], []
            store = MagicMock()
            store.create.return_value = {'created': True}
            store.task.return_value = {'status': 'completed'}
            store._owned.return_value = {'claim_id': '81b224c6-7333-433c-bf57-84ce9b789788'}
            store.required_scopes.return_value = [{'kind': 'class'}]
            store.events.return_value = [
                {'kind': 'view', 'selection': {'view': 'classroom_day', 'group': checker.fixture.GROUP,
                                             'day': checker.fixture.DAY}},
                {'kind': 'message', 'item_id': 'answer', 'text': 'synthetic response'},
                {'kind': 'terminal', 'status': 'completed'},
            ]
            store_type = MagicMock(side_effect=lambda *args, **kwargs: (trace.append('store'), store)[1])
            runtime = MagicMock()
            runtime.ready.return_value = True
            runtime.observe.return_value = ExecutionObservation('81b224c6-7333-433c-bf57-84ce9b789788',
                                                                'exited', 0, 0, False, True)
            runtime_type = MagicMock(return_value=runtime)
            frappe = SimpleNamespace()
            def baseline(owner, callback):
                trace.append('diagnostic:' + owner)
                return callback()
            adapter = SimpleNamespace(run_check=baseline, view_scopes=MagicMock(return_value=[]))
            data = {'group': checker.fixture.GROUP, 'day': checker.fixture.DAY,
                    'students': [{'student': 'synthetic-1'}, {'student': 'synthetic-2'}],
                    'counts': {'visible': 2, 'unknown': 2}}
            adapter.read_attendance = MagicMock(return_value=data)
            key = MagicMock(side_effect=AssertionError('A pure checker test must never load a key'))
            def proxy_type(directory, token, **kwargs):
                trace.append('proxy')
                proxy = SimpleNamespace(model_calls=1, tool_handler=kwargs['tool_handler'])
                proxies.append(proxy)
                return proxy
            class FakeWorker:
                def __init__(self, _store, _runtime, **kwargs):
                    trace.append('worker')
                    self.kwargs, self.runs = kwargs, 0
                    workers.append(self)
                def run(self, identity, job_id):
                    self.runs += 1
                    if self.runs > 1:
                        return {'started': False, 'status': 'already_claimed_or_stopped'}
                    trace.append('worker.run')
                    proxy = self.kwargs['proxy_factory'](root, 't' * 43,
                        tool_handler=lambda tool, args, call_id: self.kwargs['read_attendance']('synthetic-claim', **args))
                    proxy.tool_handler('classroom_read', {'group': checker.fixture.GROUP, 'day': checker.fixture.DAY}, 'read-1')
                    return {'started': True, 'status': 'completed'}
            imported = {
                'tongjianyun.business_agent_tasks': module('tongjianyun.business_agent_tasks',
                    BusinessTaskStore=store_type, TaskIdentity=TaskIdentity, QueueObservation=QueueObservation),
                'tongjianyun.business_agent_worker': module('tongjianyun.business_agent_worker',
                    BusinessWorker=FakeWorker, UnixLauncherRuntime=runtime_type),
                'tongjianyun.business_agent_transport': module('tongjianyun.business_agent_transport',
                    TaskProxy=proxy_type, private_directory=lambda directory: directory),
                'tongjianyun.business_agent_service': module('tongjianyun.business_agent_service', _model_key=key),
            }
            stack.enter_context(patch.dict(sys.modules, imported))
            stack.enter_context(patch.object(checker.os, 'name', 'posix'))
            stack.enter_context(patch.object(checker.os, 'geteuid', return_value=1000, create=True))
            stack.enter_context(patch.object(checker.qa, 'ROOT', root))
            stack.enter_context(patch.object(checker.qa, 'SITES', sites))
            stack.enter_context(patch.object(checker, 'MARKER', root / 'once.json'))
            config = stack.enter_context(patch.object(checker.qa, 'config_guard'))
            prepare = stack.enter_context(patch.object(checker.qa, 'runtime', return_value=frappe))
            digest_file = stack.enter_context(patch.object(checker.qa, 'digest_file', return_value='a' * 64))
            stack.enter_context(patch.object(checker.qa, 'safe_target', side_effect=lambda path: path))
            stack.enter_context(patch.object(checker.qa, 'private_json',
                side_effect=lambda path, value: evidence.append(json.loads(json.dumps(value)))))
            stack.enter_context(patch.object(checker, 'readonly_adapter', return_value=adapter))
            account = stack.enter_context(patch.object(checker.fixture, 'account_guard'))
            digest = stack.enter_context(patch.object(checker.fixture, 'protected_digest', return_value='same-digest'))
            reserve = stack.enter_context(patch.object(checker, 'reserve', side_effect=lambda value: trace.append('reserve')))
            output = stack.enter_context(patch('sys.stdout', new_callable=io.StringIO))
            yield SimpleNamespace(**locals())

    def test_prepare_does_not_reserve_provision_store_dispatch_worker_proxy_or_model(self):
        with self.harness() as h:
            checker.run()
            result = json.loads(h.output.getvalue())
            self.assertTrue(result['prepare_passed'])
            self.assertFalse(result['executed'])
            self.assertFalse(result['model_started'])
            self.assertFalse(result['http_rq_browser_exercised'])
            h.reserve.assert_not_called()
            h.store_type.assert_not_called()
            h.key.assert_not_called()
            self.assertEqual(h.workers, [])
            self.assertEqual(h.proxies, [])
            self.assertEqual(h.evidence, [])
            self.assertEqual(h.trace, ['diagnostic:' + checker.fixture.TEACHER])
            h.account.assert_called_once_with(h.frappe)
            h.digest.assert_called_once_with(h.frappe)
            self.assertEqual(h.digest_file.call_count, len(checker.SOURCE_FILES))

    def test_existing_execute_once_marker_refuses_before_task_or_key_access(self):
        with self.harness() as h:
            h.reserve.side_effect = FileExistsError('existing execute-once marker')
            with self.assertRaises(FileExistsError):
                checker.run(True)
            h.store_type.assert_not_called()
            h.key.assert_not_called()
            self.assertEqual(h.workers, [])
            self.assertEqual(h.evidence, [])

    def test_run_reserves_before_creating_task_and_records_non_http_scope(self):
        with self.harness() as h:
            checker.run(True)
            self.assertLess(h.trace.index('reserve'), h.trace.index('store'))
            self.assertLess(h.trace.index('reserve'), h.trace.index('worker.run'))
            self.assertEqual(len(h.workers), 1)
            self.assertEqual(h.workers[0].runs, 2)  # second is only the replay guard
            self.assertEqual(len(h.proxies), 1)
            h.key.assert_not_called()
            final = h.evidence[-1]
            self.assertTrue(final['all_passed'])
            self.assertTrue(final['redelivery_did_not_execute'])
            self.assertFalse(final['http_rq_browser_exercised'])
            self.assertFalse(final['production_access'])
            self.assertEqual(final['tool_calls'][0]['student_count'], 2)
            self.assertEqual(final['tool_calls'][0]['counts'], h.data['counts'])
            self.assertEqual(h.digest.call_count, 2)
            self.assertEqual(h.trace.count('diagnostic:' + checker.fixture.TEACHER), 2)

    def test_no_real_launcher_readiness_cannot_reserve_or_run(self):
        with self.harness() as h:
            h.runtime.ready.return_value = False
            with self.assertRaises(PermissionError):
                checker.run(True)
            h.reserve.assert_not_called()
            h.store_type.assert_not_called()
            h.digest.assert_not_called()

    def test_fixture_authority_failure_precedes_marker_and_task(self):
        with self.harness() as h:
            h.account.side_effect = PermissionError('synthetic teacher changed')
            with self.assertRaises(PermissionError):
                checker.run(True)
            h.reserve.assert_not_called()
            h.store_type.assert_not_called()
            h.digest.assert_not_called()

    def test_root_execution_is_rejected_before_any_runtime_or_marker(self):
        with self.harness() as h, patch.object(checker.os, 'geteuid', return_value=0):
            with self.assertRaises(PermissionError):
                checker.run(True)
            h.prepare.assert_not_called()
            h.reserve.assert_not_called()

    def test_missing_tool_wrong_projection_or_changed_digest_cannot_pass(self):
        for issue in ('student_count', 'group', 'day', 'view', 'view_day', 'digest', 'exit', 'lease'):
            with self.subTest(issue=issue), self.harness() as h:
                if issue == 'student_count':
                    h.data['students'] = []
                elif issue == 'group':
                    h.data['group'] = 'another-group'
                elif issue == 'day':
                    h.data['day'] = '2026-09-18'
                elif issue == 'view':
                    h.store.events.return_value = [{'kind': 'message', 'item_id': 'a', 'text': 'only text'}]
                elif issue == 'view_day':
                    h.store.events.return_value[0]['selection']['day'] = '2026-09-18'
                elif issue == 'digest':
                    h.digest.side_effect = ['before', 'changed']
                else:
                    h.runtime.observe.return_value = ExecutionObservation('81b224c6-7333-433c-bf57-84ce9b789788',
                        'exited', 0, 1 if issue == 'exit' else 0, False, issue != 'lease')
                with self.assertRaises(RuntimeError):
                    checker.run(True)
                self.assertFalse(h.evidence[-1]['all_passed'])
                self.assertEqual(len(h.workers), 1)

    def test_worker_failure_persists_failure_and_never_retries(self):
        with self.harness() as h:
            h.adapter.read_attendance.side_effect = PermissionError('denied fixture')
            with self.assertRaises(PermissionError):
                checker.run(True)
            self.assertEqual(h.workers[0].runs, 1)
            self.assertFalse(h.evidence[-1]['all_passed'])
            self.assertEqual(h.evidence[-1]['failure_type'], 'PermissionError')
            self.assertEqual(h.evidence[-1]['tool_calls'], [])
            h.reserve.assert_called_once()


class ReadonlyAdapterTests(unittest.TestCase):
    def test_actual_legacy_digest_temporary_admin_is_readonly_and_restores_teacher(self):
        # Exercise the actual imported diagnostic helper, never a live DB.
        trace = []
        frappe = SimpleNamespace(conf={}, flags=SimpleNamespace(), db=MagicMock(),
                                 session=SimpleNamespace(user=checker.fixture.TEACHER))
        def sql(query):
            trace.append(query)
            return [[1]]
        frappe.db.sql.side_effect = sql
        def set_user(owner):
            trace.append(('set-user', owner))
            frappe.session.user = owner
        frappe.set_user = set_user
        def get_doc(*args):
            self.assertTrue(frappe.flags.read_only)
            self.assertEqual(frappe.session.user, 'Administrator')
            trace.append('diagnostic-read')
            return SimpleNamespace(as_dict=lambda: {'synthetic': True})
        frappe.get_doc = MagicMock(side_effect=get_doc)
        frappe.get_all = MagicMock(return_value=[])
        class Fresh:
            def __init__(self, site, sites, *, before_connect):
                self.before = before_connect
            def __call__(self, owner, callback):
                self.before()
                self_outer.assertEqual(owner, checker.fixture.TEACHER)
                return callback()
        self_outer = self
        authority_module = module('tongjianyun.business_agent_authority', FreshFrappeChecks=Fresh,
            FrappeBusinessAuthority=lambda site, run_check: SimpleNamespace(run_check=run_check))
        with patch.dict(sys.modules, {'tongjianyun.business_agent_authority': authority_module}), \
                patch.object(checker.qa, 'config_guard'), patch.object(checker.qa, 'guard'):
            adapter = checker.readonly_adapter(frappe)
            digest = adapter.run_check(checker.fixture.TEACHER, lambda: checker.fixture.protected_digest(frappe))
            self.assertEqual(len(digest), 64)
            self.assertEqual(frappe.session.user, checker.fixture.TEACHER)
            self.assertLess(trace.index('SET SESSION TRANSACTION READ ONLY'), trace.index(('set-user', 'Administrator')))
            frappe.get_doc.side_effect = RuntimeError('synthetic diagnostic read failure')
            with self.assertRaises(RuntimeError):
                adapter.run_check(checker.fixture.TEACHER, lambda: checker.fixture.protected_digest(frappe))
            self.assertEqual(frappe.session.user, checker.fixture.TEACHER)
        frappe.db.commit.assert_not_called()

    def test_every_callback_runs_in_guarded_fresh_teacher_readonly_context(self):
        trace = []
        frappe = SimpleNamespace(conf={'fixture': True}, flags=SimpleNamespace(), db=MagicMock())
        def sql(query):
            trace.append(query)
            return [[1]]
        frappe.db.sql.side_effect = sql
        class Fresh:
            def __init__(self, site, sites, *, before_connect):
                self.before = before_connect
                trace.append(('fresh-config', site, sites))
            def __call__(self, owner, callback):
                self.before()
                trace.append(('fresh-owner', owner))
                return callback()
        class Authority:
            def __init__(self, site, *, run_check):
                self.run_check = run_check
        authority_module = module('tongjianyun.business_agent_authority',
                                  FreshFrappeChecks=Fresh, FrappeBusinessAuthority=Authority)
        with patch.dict(sys.modules, {'tongjianyun.business_agent_authority': authority_module}), \
                patch.object(checker.qa, 'config_guard') as config, patch.object(checker.qa, 'guard') as guard:
            adapter = checker.readonly_adapter(frappe)
            for _ in range(2):
                result = adapter.run_check(checker.fixture.TEACHER,
                    lambda: (trace.append('callback'), frappe.flags.read_only)[1])
                self.assertTrue(result)
            self.assertEqual(config.call_count, 2)
            self.assertEqual(guard.call_count, 2)
            guard.assert_called_with(frappe.conf)
        self.assertEqual(trace[0], ('fresh-config', checker.qa.SITE, str(checker.qa.SITES)))
        self.assertEqual(trace[1:], [('fresh-owner', checker.fixture.TEACHER),
            'SET SESSION TRANSACTION READ ONLY', 'SELECT @@session.tx_read_only', 'callback'] * 2)
        frappe.db.commit.assert_not_called()

    def test_failed_readonly_verification_never_enters_business_callback(self):
        frappe = SimpleNamespace(conf={}, flags=SimpleNamespace(), db=MagicMock())
        frappe.db.sql.return_value = [[0]]
        fresh = MagicMock(side_effect=lambda owner, callback: callback())
        authority = lambda site, run_check: SimpleNamespace(run_check=run_check)
        authority_module = module('tongjianyun.business_agent_authority',
            FreshFrappeChecks=MagicMock(return_value=fresh), FrappeBusinessAuthority=authority)
        callback = MagicMock()
        with patch.dict(sys.modules, {'tongjianyun.business_agent_authority': authority_module}):
            adapter = checker.readonly_adapter(frappe)
            with self.assertRaises(PermissionError):
                adapter.run_check(checker.fixture.TEACHER, callback)
        callback.assert_not_called()
        frappe.db.commit.assert_not_called()


@unittest.skipUnless(os.name == 'posix', 'Real Linux O_NOFOLLOW/O_DIRECTORY and fsync')
class RealMarkerTests(unittest.TestCase):
    def test_marker_is_durable_private_exclusive_and_never_replaced(self):
        with tempfile.TemporaryDirectory() as name:
            marker = Path(name) / 'once.json'
            with patch.object(checker, 'MARKER', marker), patch.object(checker.qa, 'safe_target', side_effect=lambda p: p):
                checker.reserve({'task_id': 'first'})
                original = marker.read_bytes()
                self.assertEqual(marker.stat().st_mode & 0o777, 0o600)
                with self.assertRaises(FileExistsError):
                    checker.reserve({'task_id': 'second'})
                self.assertEqual(marker.read_bytes(), original)

    def test_marker_symlink_is_never_followed_or_target_overwritten(self):
        with tempfile.TemporaryDirectory() as name:
            marker, target = Path(name) / 'once.json', Path(name) / 'target'
            target.write_bytes(b'preserve')
            marker.symlink_to(target)
            with patch.object(checker, 'MARKER', marker), patch.object(checker.qa, 'safe_target', side_effect=lambda p: p):
                with self.assertRaises(OSError):
                    checker.reserve({'task_id': 'other'})
                self.assertEqual(target.read_bytes(), b'preserve')


if __name__ == '__main__':
    unittest.main()
