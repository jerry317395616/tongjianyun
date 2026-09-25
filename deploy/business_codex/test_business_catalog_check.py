"""Pure guards for catalog QA; no Frappe, DB, SSH, model or running services."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import importlib.util
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SPEC = importlib.util.spec_from_file_location('catalog_check_test', Path(__file__).with_name('check_business_catalog.py'))
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def prepared():
    return {'status': 'prepared_read_only', 'site': checker.qa.SITE, 'teacher': checker.OWNER,
            'session_transaction_read_only': True, 'ordinary_teacher': True, 'existing_foreign_fixture': True,
            'app': 'education', 'module': 'Education', 'business_writes': False, 'model_calls': 0}


class CatalogCheckerTests(unittest.TestCase):
    def environment(self, stack):
        values = tuple(object() for _ in range(5))
        setup = stack.enter_context(patch.object(checker.fixture, 'setup', return_value=values))
        modules = stack.enter_context(patch.object(checker, 'runtime_modules', return_value=()))
        source = stack.enter_context(patch.object(checker, 'source_guard', return_value={'source': 'sha'}))
        prepare = stack.enter_context(patch.object(checker, 'prepare', return_value=prepared()))
        execute = stack.enter_context(patch.object(checker, 'execute'))
        stack.enter_context(redirect_stdout(io.StringIO()))
        return values, setup, modules, source, prepare, execute

    def test_default_is_read_only_prepare_with_no_task_or_evidence_directory(self):
        with ExitStack() as stack:
            values, setup, modules, source, prepare, execute = self.environment(stack)
            checker.main([])
            setup.assert_called_once_with()
            modules.assert_called_once_with(values[1])
            source.assert_called_once_with(())
            prepare.assert_called_once_with(values[0], values[2])
            execute.assert_not_called()

    def test_explicit_run_only_after_guarded_setup_and_prepare(self):
        with ExitStack() as stack:
            values, _, _, _, _, execute = self.environment(stack)
            checker.main(['--run'])
            execute.assert_called_once_with(values[0], (), values[2], values[3], values[4], prepared(), {'source': 'sha'})

    def test_setup_source_and_prepare_fail_closed_without_execution(self):
        for target in ('setup', 'source', 'prepare'):
            with self.subTest(target=target), ExitStack() as stack:
                _, setup, _, source, prepare, execute = self.environment(stack)
                {'setup': setup, 'source': source, 'prepare': prepare}[target].side_effect = PermissionError('guard')
                with self.assertRaises(PermissionError):
                    checker.main(['--run'])
                execute.assert_not_called()

    def test_no_cli_override_for_actor_site_command_queue_model_or_writes(self):
        for flag in ('--site', '--owner', '--group', '--model', '--command', '--queue', '--force', '--write'):
            with self.subTest(flag=flag), patch.object(checker.fixture, 'setup') as setup, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    checker.main([flag, 'foreign'])
                setup.assert_not_called()

    def test_preparation_requires_exact_teacher_site_and_strict_readonly_booleans(self):
        mutations = ({'site': 'child.myyr.top'}, {'teacher': 'Administrator'}, {'status': 'ready'},
                     {'session_transaction_read_only': 1}, {'ordinary_teacher': False},
                     {'existing_foreign_fixture': 1}, {'business_writes': 0}, {'model_calls': False},
                     {'model_calls': 1}, {'app': ''}, {'module': None})
        for value in (None, {}, *(dict(prepared(), **change) for change in mutations)):
            with self.subTest(value=value), self.assertRaises(PermissionError):
                checker.require_prepared(value)
        checker.require_prepared(prepared())

    def test_changed_source_blocks_execute_before_any_frappe_import_or_write(self):
        with patch.object(checker, 'source_guard', return_value={'source': 'different'}), \
             patch.object(checker.qa, 'config_guard') as guard:
            with self.assertRaisesRegex(PermissionError, 'changed'):
                checker.execute(None, (), None, None, None, prepared(), {'source': 'prepared'})
            guard.assert_not_called()

    def test_source_guard_rejects_local_or_nonreviewed_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(checker.qa, 'SOURCE', root / 'reviewed'), \
                 patch.object(checker, '__file__', str(root / 'foreign/check_business_catalog.py')), \
                 patch.object(checker.qa, 'digest_file') as digest:
                with self.assertRaises(PermissionError):
                    checker.source_guard(())
                digest.assert_not_called()

    def test_source_guard_pins_helpers_and_rejects_foreign_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'deploy/business_codex/check_business_catalog.py'
            fixture = root / 'fixture.py'
            qa = root / 'qa.py'
            module = root / 'catalog.py'
            with patch.object(checker.qa, 'SOURCE', root), patch.object(checker, '__file__', str(script)), \
                 patch.object(checker.fixture, '__file__', str(fixture)), patch.object(checker.qa, '__file__', str(qa)), \
                 patch.object(checker.qa, 'digest_file', return_value='sha') as digest:
                result = checker.source_guard((SimpleNamespace(__file__=str(module)),))
                self.assertEqual(set(result), {'deploy/business_codex/check_business_catalog.py', 'fixture.py', 'qa.py', 'catalog.py'})
                digest.reset_mock()
                with self.assertRaises(PermissionError):
                    checker.source_guard((SimpleNamespace(__file__=str(root.parent / 'foreign.py')),))
                digest.assert_not_called()

    def test_native_oracle_uses_original_filters_modules_and_excludes_control_types(self):
        frappe = Mock()
        gates = SimpleNamespace(_account=Mock(), CONTROL_DOCTYPES={'User'})
        native = SimpleNamespace(module_apps=Mock(return_value={'Education': 'education', 'Stock': 'erpnext'}),
                                 catalog_entries=Mock(return_value=[
                                     {'kind': 'doctype', 'module': 'Education', 'name': 'Student Group'},
                                     {'kind': 'doctype', 'module': 'Education', 'name': 'User'}]))
        filters = {'app': 'education', 'module': 'Education', 'keyword': 'Student Group'}
        result = checker.native_keys(frappe, gates, native, filters)
        self.assertEqual(result, [('education', 'Education', 'Student Group')])
        gates._account.assert_called_once_with(checker.OWNER, checker.qa.SITE)
        native.catalog_entries.assert_called_once_with({'kind': 'doctype', **filters}, {'Education': 'education'})

    def test_browser_source_proof_includes_new_executable_dependencies(self):
        spec = importlib.util.spec_from_file_location('browser_catalog_dependency_test', Path(__file__).with_name('serve_business_browser.py'))
        browser = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(browser)
        expected = {'tongjianyun/business_agent_catalog.py', 'tongjianyun/business_agent_execution.py',
                    'tongjianyun/business_agent_writes.py', 'tongjianyun/business_agent_write_adapter.py',
                    'tongjianyun/frappe_project_views.py'}
        self.assertTrue(expected <= set(browser.SOURCE_FILES))
        self.assertTrue(expected <= set(browser.LOADED_SOURCE_SHA256))
        self.assertEqual(len(browser.SOURCE_FILES), len(set(browser.SOURCE_FILES)))


if __name__ == '__main__':
    unittest.main()
