"""Keyless tests for the teacher browser evidence runner's immutable baseline."""
import importlib.util
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


class TeacherBrowserEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.qa = SimpleNamespace(ROOT=Path('/qa'), STATE=Path('/qa/browser-fixture.json'),
            TASK='synthetic-task', SITE='qa.localhost', config_guard=MagicMock(),
            safe_target=MagicMock(), connect=MagicMock(), private_json=MagicMock())
        path = Path(__file__).with_name('verify_teacher_browser_readback.py')
        spec = importlib.util.spec_from_file_location('teacher_browser_readback_test_target', path)
        self.runner = importlib.util.module_from_spec(spec)
        with patch.dict('sys.modules', {'serve_isolated_browser': self.qa}):
            spec.loader.exec_module(self.runner)
        self.state = {'owner': self.qa.TASK, 'site': self.qa.SITE, 'teacher': self.runner.TEACHER,
            'group': self.runner.GROUP, 'meal': 'lunch', 'day': '2026-09-18',
            'credentials_file': '/should/not/read/secret.json'}
        self.qa.safe_target.return_value.read_text.return_value = json.dumps(self.state)

    def test_fixture_does_not_read_or_return_credentials_and_keeps_old_date(self):
        result = self.runner.fixture()
        self.qa.config_guard.assert_called_once()
        self.qa.safe_target.assert_called_once_with(self.qa.STATE)
        self.assertNotIn('credentials_file', result)
        self.assertNotIn('day', result)
        self.assertEqual(self.runner.DAY, '2026-09-17')

    def test_fixture_rejects_other_teacher_group_site_and_old_fixture_date(self):
        for key, value in [('teacher', 'Administrator'), ('group', 'another'), ('site', 'production'), ('day', '2026-09-17')]:
            self.qa.safe_target.return_value.read_text.return_value = json.dumps({**self.state, key: value})
            with self.subTest(key=key), self.assertRaises(AssertionError):
                self.runner.fixture()

    def test_existing_baseline_is_preserved_without_any_database_connection(self):
        fixture = {key: self.state[key] for key in ('owner', 'site', 'teacher', 'group', 'meal')}
        saved = {'fixture': fixture, 'day': self.runner.DAY, 'mode': 'pre_save_baseline',
                 'students': list(self.runner.STUDENTS)}
        self.qa.safe_target.return_value.read_text.return_value = json.dumps(saved)
        with patch.object(self.runner, 'fixture', return_value=fixture), patch.object(Path, 'exists', return_value=True), patch('builtins.print'):
            self.assertEqual(self.runner.prepare(), 0)
        self.qa.connect.assert_not_called()
        self.qa.private_json.assert_not_called()

    def test_existing_mismatched_baseline_not_overwritten(self):
        self.qa.safe_target.return_value.read_text.return_value = json.dumps({'fixture': {'wrong': True}, 'day': self.runner.DAY})
        with patch.object(self.runner, 'fixture', return_value={}), patch.object(Path, 'exists', return_value=True):
            with self.assertRaises(AssertionError):
                self.runner.prepare()
        self.qa.connect.assert_not_called()
        self.qa.private_json.assert_not_called()

    def test_baseline_digest_ignores_key_order_not_values(self):
        self.assertEqual(self.runner.digest({'a': 1, 'b': 2}), self.runner.digest({'b': 2, 'a': 1}))
        self.assertNotEqual(self.runner.digest({'a': 1}), self.runner.digest({'a': 2}))

    def test_expected_projection_contains_no_names_or_actual_values(self):
        result = self.runner.expected_fields({'students': [{'student': 'S1', 'student_name': 'Private name',
            'lunch_expected': 1, 'breakfast_expected': 0, 'lunch': '已就餐'}]}, ['breakfast', 'lunch'])
        self.assertEqual(result, {'S1': {'breakfast': 0, 'lunch': 1}})
        self.assertNotIn('Private', str(result))
        self.assertNotIn('已就餐', str(result))

    def test_protected_diagnostic_requires_admin_not_teacher(self):
        frappe = MagicMock(session=SimpleNamespace(user=self.runner.TEACHER))
        with self.assertRaises(AssertionError):
            self.runner.protected_snapshot(frappe)
        frappe.get_all.assert_not_called()


if __name__ == '__main__':
    unittest.main()
