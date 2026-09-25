"""Pure safeguards for the one-shot native QA checker; no DB/model/site calls."""
from contextlib import ExitStack, redirect_stdout, redirect_stderr
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


SPEC = importlib.util.spec_from_file_location('native_write_checker_test', Path(__file__).with_name('check_business_writes.py'))
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def prepared():
    return {'status': 'prepared_read_only', 'site': checker.qa.SITE, 'day': checker.DAY,
            'isolation': 'REPEATABLE-READ', 'empty_day_verified': True}


class NativeWriteCheckerTests(unittest.TestCase):
    def test_default_command_only_prepares_and_cannot_start_write(self):
        values = tuple(object() for _ in range(5))
        with patch.object(checker.fixture, 'setup', return_value=values), \
             patch.object(checker, 'prepare', return_value=prepared()) as preflight, \
             patch.object(checker, 'execute') as execute, redirect_stdout(io.StringIO()):
            checker.main([])
        preflight.assert_called_once_with(values[0], values[2])
        execute.assert_not_called()

    def test_explicit_run_requires_successful_prepare_first(self):
        values = tuple(object() for _ in range(5))
        with patch.object(checker.fixture, 'setup', return_value=values), \
             patch.object(checker, 'prepare', return_value=prepared()), \
             patch.object(checker, 'execute') as execute, redirect_stdout(io.StringIO()):
            checker.main(['--run'])
        execute.assert_called_once_with(values[0], values[2], values[3], values[4], prepared())

    def test_failed_preparation_never_executes_even_with_run(self):
        with patch.object(checker.fixture, 'setup', return_value=tuple(object() for _ in range(5))), \
             patch.object(checker, 'prepare', side_effect=RuntimeError('occupied fixture')), \
             patch.object(checker, 'execute') as execute:
            with self.assertRaisesRegex(RuntimeError, 'occupied'):
                checker.main(['--run'])
        execute.assert_not_called()

    def test_command_cannot_change_site_owner_date_or_model(self):
        for option in ('--site', '--owner', '--day', '--model', '--force'):
            with self.subTest(option=option), patch.object(checker.fixture, 'setup') as setup, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    checker.main([option, 'untrusted'])
                setup.assert_not_called()

    def test_unprepared_mismatched_or_nondefault_isolation_cannot_execute(self):
        for value in (None, {}, {**prepared(), 'site': 'production.localhost'}, {**prepared(), 'day': '2026-09-16'},
                      {**prepared(), 'empty_day_verified': 1}, {**prepared(), 'isolation': 'READ-COMMITTED'}):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                checker.require_prepared(value)
        checker.require_prepared(prepared())

    def test_existing_attempt_stops_prepare_before_any_business_read(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'attempt.json'
            path.touch()
            with patch.object(checker, 'ATTEMPT', path), patch.object(checker.qa, 'safe_target', side_effect=lambda value: value):
                runner = MagicMock()
                with self.assertRaisesRegex(RuntimeError, 'already exists'):
                    checker.prepare(MagicMock(), runner)
                runner.assert_not_called()

    def test_attempt_marker_is_exclusive_retained_and_contains_no_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'attempt.json'
            with patch.object(checker, 'ATTEMPT', path), patch.object(checker.qa, 'safe_target', side_effect=lambda value: value):
                checker.mark_attempt(Path(folder))
                first = path.read_bytes()
                with self.assertRaises(FileExistsError):
                    checker.mark_attempt(Path(folder))
                self.assertEqual(path.read_bytes(), first)
                data = json.loads(first)
                self.assertEqual(data['site'], checker.qa.SITE)
                self.assertEqual(data['day'], checker.DAY)
                self.assertEqual(set(data), {'site', 'day', 'evidence', 'purpose'})

    def test_all_source_types_are_checked_and_any_existing_source_blocks(self):
        daily = SimpleNamespace(CONFIRMATION_DOCTYPE='Daily', ADJUSTMENT_DOCTYPE='Adjustment')
        meals = SimpleNamespace(DOCTYPE='ClassMeal')
        import tongjianyun
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, {'tongjianyun.daily_meals': daily, 'tongjianyun.student_meals': meals}))
            stack.enter_context(patch.object(tongjianyun, 'daily_meals', daily, create=True))
            stack.enter_context(patch.object(tongjianyun, 'student_meals', meals, create=True))
            frappe = SimpleNamespace(db=MagicMock())
            frappe.db.exists.return_value = False
            checker.assert_empty_target(frappe)
            self.assertEqual([call.args[0] for call in frappe.db.exists.call_args_list],
                             ['Student Attendance', 'Student Leave Application', 'ClassMeal', 'Daily', 'Adjustment'])
            for occupied in range(5):
                frappe.db.exists.reset_mock()
                frappe.db.exists.side_effect = [False] * occupied + [True]
                with self.assertRaisesRegex(RuntimeError, 'existing sources'):
                    checker.assert_empty_target(frappe)
                self.assertEqual(frappe.db.exists.call_count, occupied + 1)
            frappe.db.commit.assert_not_called()

    def test_isolation_check_never_sets_or_weakens_transaction_isolation(self):
        frappe = SimpleNamespace(db=MagicMock())
        for value in ('READ-COMMITTED', 'SERIALIZABLE', ''):
            frappe.db.sql.return_value = [(value,)]
            with self.assertRaises(RuntimeError):
                checker.isolation(frappe)
        frappe.db.sql.return_value = [('REPEATABLE-READ',)]
        self.assertEqual(checker.isolation(frappe), 'REPEATABLE-READ')
        self.assertTrue(all(call.args == ('SELECT @@session.tx_isolation',) for call in frappe.db.sql.call_args_list))


if __name__ == '__main__':
    unittest.main()
