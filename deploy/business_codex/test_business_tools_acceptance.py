"""Pure guard checks for the fixed-day synthetic tool acceptance runner."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('business_tools_acceptance', Path(__file__).with_name('check_business_tools.py'))
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class BusinessToolsAcceptanceGuards(unittest.TestCase):
    def test_wrong_isolation_config_stops_before_fixture_or_database(self):
        with patch.object(runner.qa, 'config_guard', side_effect=AssertionError('wrong database')), \
             patch.object(runner.qa, 'safe_target') as read, self.assertRaisesRegex(AssertionError, 'wrong database'):
            runner.fixture_guard()
        read.assert_not_called()

    def test_optimized_python_refused_before_inherited_assertion_guards(self):
        with patch.object(runner.sys, 'flags', SimpleNamespace(optimize=1)), \
             patch.object(runner.qa, 'config_guard') as guard, self.assertRaises(RuntimeError):
            runner.fixture_guard()
        guard.assert_not_called()

    def test_fixture_owner_site_teacher_and_group_all_pinned(self):
        fixture = {'owner': runner.qa.TASK, 'site': runner.qa.SITE, 'teacher': runner.TEACHER, 'group': runner.GROUP}
        for field in fixture:
            bad = {**fixture, field: 'other'}
            path = MagicMock()
            path.read_text.return_value = json.dumps(bad)
            with self.subTest(field=field), patch.object(runner.qa, 'config_guard'), \
                 patch.object(runner.qa, 'safe_target', return_value=path), self.assertRaises(AssertionError):
                runner.fixture_guard()

    def test_an_existing_attempt_prevents_preflight_or_mutating_execution(self):
        marker = MagicMock()
        marker.exists.return_value = True
        for method in (runner.preflight, runner.execute):
            with self.subTest(method=method.__name__), patch.object(runner, 'fixture_guard'), \
                 patch.object(runner, 'MARKER', marker), patch.object(runner, 'connect') as connect, self.assertRaises(AssertionError):
                method()
            connect.assert_not_called()

    def test_any_existing_attendance_class_or_daily_record_blocks_fixed_day(self):
        for wanted, _ in runner.DOCS:
            frappe = MagicMock()
            frappe.db.exists.side_effect = lambda doctype, filters: doctype == wanted
            with self.subTest(doctype=wanted), self.assertRaises(AssertionError):
                runner.untouched_day(frappe)

    def test_any_overlapping_leave_blocks_fixed_day(self):
        frappe = MagicMock()
        frappe.db.exists.side_effect = lambda doctype, filters: doctype == 'Student Leave Application'
        with self.assertRaisesRegex(AssertionError, 'leave overlaps'):
            runner.untouched_day(frappe)

    def test_empty_day_accepts_no_business_writes_and_no_dynamic_date_fallback(self):
        frappe = MagicMock()
        frappe.db.exists.return_value = False
        runner.untouched_day(frappe)
        self.assertEqual(frappe.db.exists.call_count, 4)
        frappe.db.commit.assert_not_called()
        frappe.db.sql.assert_not_called()
        self.assertEqual(runner.DAY, '2026-09-16')


if __name__ == '__main__':
    unittest.main()
