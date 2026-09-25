"""The readonly regression runner must not execute on multiprocessing import."""
from contextlib import ExitStack
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


SCRIPT = Path(__file__).with_name('check_regression.py')


class RegressionRunnerTests(unittest.TestCase):
    def test_multiprocessing_and_normal_import_never_connect_or_run_tests(self):
        for name in ('__mp_main__', 'imported_regression_runner'):
            with self.subTest(name=name):
                frappe = MagicMock()
                with patch.dict('sys.modules', {'frappe': frappe}), \
                        patch.object(unittest, 'TextTestRunner') as runner:
                    module = runpy.run_path(str(SCRIPT), run_name=name)
                self.assertTrue(callable(module['main']))
                frappe.init.assert_not_called()
                frappe.connect.assert_not_called()
                runner.assert_not_called()

    def test_failed_readonly_enforcement_does_not_load_or_run_tests(self):
        frappe = MagicMock()
        frappe.flags = SimpleNamespace()
        frappe.db.sql.return_value = [(0,)]
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch.dict('os.environ', {'UNIFIED_BUSINESS_SITE': 'qa.localhost',
                'UNIFIED_BUSINESS_SITES_PATH': directory}))
            stack.enter_context(patch.dict('sys.modules', {'frappe': frappe}))
            loader = stack.enter_context(patch.object(unittest.defaultTestLoader, 'loadTestsFromNames'))
            module = runpy.run_path(str(SCRIPT), run_name='test_runner')
            with self.assertRaisesRegex(RuntimeError, 'read-only'):
                module['main']()
            loader.assert_not_called()
            frappe.db.rollback.assert_called_once()
            frappe.destroy.assert_called_once()
            frappe.set_user.assert_not_called()


if __name__ == '__main__':
    unittest.main()
