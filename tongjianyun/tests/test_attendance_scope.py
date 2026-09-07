"""Keyless regression tests; all business records remain untouched."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AttendanceScopeTests(unittest.TestCase):
    def setUp(self):
        self.frappe = ModuleType("frappe")
        self.frappe.session = SimpleNamespace(user="teacher@example.test")
        self.frappe.PermissionError = PermissionError
        self.frappe.get_roles = Mock(return_value=["Instructor"])
        self.frappe.get_all = Mock(side_effect=[["E1"], ["I1"], ["A"]])
        self.frappe.get_list = Mock(return_value=["A"])
        self.frappe._ = lambda value: value
        self.frappe.whitelist = lambda *a, **k: lambda fn: fn
        utils = ModuleType("frappe.utils")
        utils.getdate = lambda value: value
        utils.nowdate = lambda: "2026-09-07"
        with patch.dict(sys.modules, {"frappe": self.frappe, "frappe.utils": utils}):
            self.scope = load_module("scope_test", ROOT / "attendance_scope.py")
            with patch.dict(sys.modules, {"tongjianyun.attendance_scope": self.scope}):
                self.daily = load_module("daily_test", ROOT / "daily_meals.py")

    def test_teacher_scope_uses_own_employee_and_instructor_links(self):
        self.assertEqual(self.scope.allowed_groups(), ["A"])
        self.assertEqual(self.frappe.get_all.call_args_list[0].kwargs["filters"]["user_id"], "teacher@example.test")
        self.assertEqual(self.frappe.get_all.call_args_list[2].kwargs["filters"]["instructor"], ["in", ["I1"]])
        self.assertEqual(self.frappe.get_list.call_args.kwargs["filters"]["name"], ["in", ["A"]])

    def test_unmapped_teacher_has_no_scope(self):
        self.frappe.get_all.side_effect = [[]]
        self.assertEqual(self.scope.allowed_groups(), [])
        self.frappe.get_list.assert_not_called()

    def test_guest_is_denied_before_queries(self):
        self.frappe.session.user = "Guest"
        with self.assertRaises(PermissionError):
            self.scope.allowed_groups()
        self.frappe.get_all.assert_not_called()

    def test_administrator_still_uses_permission_aware_group_list(self):
        self.frappe.session.user = "Administrator"
        self.assertEqual(self.scope.allowed_groups(), ["A"])
        self.frappe.get_all.assert_not_called()
        self.frappe.get_list.assert_called_once()

    def test_other_class_is_denied(self):
        with self.assertRaises(PermissionError):
            self.scope.require_group("B", ["A"])

    def test_teacher_cannot_confirm_reopen_or_recalculate_whole_school(self):
        for fn, args in [(self.daily.confirm_daily_meal, {}), (self.daily.reopen_daily_meal, {"name": "X"}), (self.daily.recalculate_daily_meal, {"name": "X"})]:
            with self.subTest(fn=fn.__name__), self.assertRaises(PermissionError):
                fn(**args)

    def test_cross_class_batch_rejected_before_confirmation_or_student_writes(self):
        with patch.object(self.daily, "allowed_groups", return_value=["A"]), patch.object(self.daily, "_get_confirmation_for_edit") as confirmation, patch.object(self.daily, "_set_student_status") as write:
            with self.assertRaises(PermissionError):
                self.daily.save_student_meal_attendance("2026-09-07", [
                    {"student_group": "A", "student": "S1", "status": "Present"},
                    {"student_group": "B", "student": "S2", "status": "Absent"},
                ])
            confirmation.assert_not_called()
            write.assert_not_called()

    def test_teacher_response_does_not_leak_global_totals_or_other_children(self):
        rows = [SimpleNamespace(student_group=g, as_dict=lambda g=g: {"student_group": g}) for g in ["A", "B"]]
        doc = SimpleNamespace(name="X", doctype="Confirmation", meal_date="2026-09-07", status="draft", get=lambda *a: rows)
        result = self.scope.visible_confirmation(doc, ["A"])
        self.assertEqual(result["details"], [{"student_group": "A"}])
        self.assertEqual(set(result), {"name", "doctype", "meal_date", "status", "details"})


if __name__ == "__main__":
    unittest.main()
