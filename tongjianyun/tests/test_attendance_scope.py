"""Keyless regression tests; all business records remain untouched."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

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
        self.frappe.AuthenticationError = PermissionError
        self.frappe.ValidationError = ValueError
        self.frappe.throw = lambda message, exc=ValueError: (_ for _ in ()).throw(exc(message))
        self.frappe.db = MagicMock(get_value=Mock(return_value=1))
        self.frappe.has_permission = Mock(return_value=True)
        self.frappe.get_doc = Mock(return_value=MagicMock())
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

    def test_disabled_account_cannot_call_direct_service(self):
        self.frappe.db.get_value.return_value = 0
        with patch.object(self.daily, "_get_confirmation_for_edit") as confirmation, patch.object(self.daily, "_set_student_status") as write:
            with self.assertRaises(PermissionError):
                self.daily.save_student_meal_attendance("2026-09-07", [{"student_group": "A", "student": "S1", "status": "Present"}])
        confirmation.assert_not_called()
        write.assert_not_called()

    def test_employee_or_teacher_label_alone_cannot_use_direct_attendance_service(self):
        for roles in (["Employee"], ["Teacher"], ["Academics User", "Employee"]):
            self.frappe.get_roles.return_value = roles
            with self.subTest(roles=roles), patch.object(self.daily, "_get_confirmation_for_edit") as confirmation, patch.object(self.daily, "_set_student_status") as write:
                with self.assertRaises(PermissionError):
                    self.daily.save_student_meal_attendance("2026-09-07", [{"student_group": "A", "student": "S1", "status": "Present"}])
                self.assertFalse(self.daily.attendance_write_allowed("2026-09-07"))
                confirmation.assert_not_called()
                write.assert_not_called()

    def test_direct_service_rejects_future_before_mutation(self):
        with patch.object(self.daily, "_attendance_editor_scope", return_value=["A"]), patch.object(self.daily, "_get_confirmation_for_edit") as confirmation, patch.object(self.daily, "_set_student_status") as write:
            with self.assertRaises(PermissionError):
                self.daily.save_student_meal_attendance("2026-09-08", [{"student_group": "A", "student": "S1", "status": "Present"}])
        confirmation.assert_not_called()
        write.assert_not_called()

    def test_entire_direct_batch_is_validated_before_confirmation_or_first_write(self):
        invalid_rows = [
            {"student_group": "B", "student": "S2", "status": "Present"},
            {"student_group": "A", "student": "S1", "status": "Present"},
            {"student_group": "A", "student": "S2", "status": "Unknown"},
            {"student_group": "A", "student": "S2", "status": "Leave", "leave_reason": "  "},
            {"student_group": ["A"], "student": "S2", "status": "Present"},
        ]
        for invalid in invalid_rows:
            with self.subTest(invalid=invalid), patch.object(self.daily, "_attendance_editor_scope", return_value=["A"]), patch.object(self.daily, "_get_confirmation_for_edit") as confirmation, patch.object(self.daily, "_set_student_status") as write:
                with self.assertRaises((PermissionError, ValueError)):
                    self.daily.save_student_meal_attendance("2026-09-07", [
                        {"student_group": "A", "student": "S1", "status": "Present"}, invalid])
                confirmation.assert_not_called()
                write.assert_not_called()

    def test_direct_foreign_student_rejected_before_any_mutation(self):
        with patch.object(self.daily, "_attendance_editor_scope", return_value=["A"]), patch.object(self.daily, "allowed_groups", return_value=["A"]), patch.object(self.daily, "_assert_active_membership", side_effect=ValueError("outside roster")), patch.object(self.daily, "_get_confirmation_for_edit") as confirmation, patch.object(self.daily, "_set_student_status") as write:
            with self.assertRaises(ValueError):
                self.daily.save_student_meal_attendance("2026-09-07", [{"student_group": "A", "student": "OTHER", "status": "Present"}])
        confirmation.assert_not_called()
        write.assert_not_called()

    def test_direct_teacher_service_uses_checked_group_and_filtered_response(self):
        aggregate = MagicMock()
        with patch.object(self.daily, "_attendance_editor_scope", return_value=["A"]), patch.object(self.daily, "allowed_groups", return_value=["A"]), patch.object(self.daily, "_assert_active_membership") as membership, patch.object(self.daily, "_leave_records", return_value={}), patch.object(self.daily, "_get_confirmation_for_edit") as confirmation, patch.object(self.daily, "_set_student_status") as write, patch.object(self.daily, "refresh_confirmation", return_value=aggregate), patch.object(self.daily, "visible_confirmation", return_value={"details": [{"student_group": "A"}]}) as visible, patch.object(self.daily, "calculate_student_details", return_value=[{"student": "S1"}]) as details:
            result = self.daily.save_student_meal_attendance("2026-09-07", [{"student_group": "A", "student": "S1", "status": "Present"}])
        membership.assert_called_once_with("A", "S1")
        confirmation.assert_called_once_with("2026-09-07", ["A"])
        write.assert_called_once_with("A", "S1", "2026-09-07", "Present", "")
        visible.assert_called_once_with(aggregate, ["A"])
        details.assert_called_once_with("2026-09-07", "A")
        self.assertEqual(result["confirmation"], {"details": [{"student_group": "A"}]})

    def test_teacher_capability_does_not_require_or_grant_daily_docperm(self):
        self.frappe.db.get_value.side_effect = [1, None]
        with patch.object(self.daily, "allowed_groups", return_value=["A"]):
            self.assertTrue(self.daily.attendance_write_allowed("2026-09-07"))
        self.assertFalse(any(call.args[0] == self.daily.CONFIRMATION_DOCTYPE for call in self.frappe.has_permission.call_args_list))

    def test_manager_capability_keeps_original_daily_docperm_requirement(self):
        self.frappe.get_roles.return_value = ["System Manager"]
        self.frappe.db.get_value.side_effect = [1, None]
        self.frappe.has_permission.side_effect = lambda dt, *a, **k: dt != self.daily.CONFIRMATION_DOCTYPE
        with patch.object(self.daily, "allowed_groups", return_value=["A"]):
            self.assertFalse(self.daily.attendance_write_allowed("2026-09-07"))

    def test_teacher_without_assignment_has_no_attendance_capability(self):
        with patch.object(self.daily, "allowed_groups", return_value=[]):
            self.assertFalse(self.daily.attendance_write_allowed("2026-09-07"))

    def test_teacher_without_native_attendance_read_has_no_capability(self):
        self.frappe.has_permission.side_effect = lambda dt, *a, **k: dt != "Student Attendance"
        self.assertFalse(self.daily.attendance_write_allowed("2026-09-07"))

    def test_confirmed_and_locked_days_have_no_teacher_capability(self):
        for state in ("已确认", "已锁定"):
            self.frappe.db.get_value.side_effect = [1, SimpleNamespace(name="D", status=state)]
            with self.subTest(state=state), patch.object(self.daily, "allowed_groups", return_value=["A"]):
                self.assertFalse(self.daily.attendance_write_allowed("2026-09-07"))

    def test_private_confirmation_helper_rechecks_scope_not_caller_flag(self):
        with patch.object(self.daily, "_attendance_editor_scope", return_value=["A"]), patch.object(self.daily, "refresh_confirmation") as refresh:
            with self.assertRaises(PermissionError):
                self.daily._get_confirmation_for_edit("2026-09-07", ["B"])
            with self.assertRaises(ValueError):
                self.daily._get_confirmation_for_edit("2026-09-07", [])
        refresh.assert_not_called()

    def test_teacher_internal_aggregate_retains_confirmed_and_locked_rejection(self):
        for state, exception in (("已确认", ValueError), ("已锁定", PermissionError)):
            doc = MagicMock(status=state)
            self.frappe.get_doc.return_value = doc
            self.frappe.db.exists.return_value = "D"
            with self.subTest(state=state), patch.object(self.daily, "_attendance_editor_scope", return_value=["A"]), patch.object(self.daily, "refresh_confirmation") as refresh:
                with self.assertRaises(exception):
                    self.daily._get_confirmation_for_edit("2026-09-07", ["A"])
            self.frappe.get_doc.assert_called_with(self.daily.CONFIRMATION_DOCTYPE, "D", for_update=True)
            doc.check_permission.assert_not_called()
            refresh.assert_not_called()

    def test_private_helper_creates_only_derived_daily_without_grant(self):
        self.frappe.db.exists.return_value = None
        doc = SimpleNamespace(status="待确认")
        with patch.object(self.daily, "_attendance_editor_scope", return_value=["A"]), patch.object(self.daily, "refresh_confirmation", return_value=doc) as refresh:
            self.assertIs(self.daily._get_confirmation_for_edit("2026-09-07", ["A"]), doc)
        refresh.assert_called_once_with("2026-09-07")
        self.frappe.has_permission.assert_not_called()

    def test_manager_direct_helper_keeps_create_and_write_permission_checks(self):
        self.frappe.get_roles.return_value = ["System Manager"]
        self.frappe.has_permission.return_value = False
        self.frappe.db.exists.return_value = None
        with patch.object(self.daily, "_attendance_editor_scope", return_value=["A"]), patch.object(self.daily, "refresh_confirmation") as refresh:
            with self.assertRaises(PermissionError):
                self.daily._get_confirmation_for_edit("2026-09-07", ["A"])
        refresh.assert_not_called()
        doc = MagicMock(status="待确认")
        doc.check_permission.side_effect = PermissionError
        self.frappe.get_doc.return_value = doc
        self.frappe.db.exists.return_value = "D"
        with patch.object(self.daily, "_attendance_editor_scope", return_value=["A"]):
            with self.assertRaises(PermissionError):
                self.daily._get_confirmation_for_edit("2026-09-07", ["A"])
        doc.check_permission.assert_called_once_with("write")

    def test_disabled_student_is_not_an_active_membership(self):
        self.frappe.db.get_value.return_value = 0
        with self.assertRaises(ValueError):
            self.daily._assert_active_membership("A", "S1")
        self.frappe.db.exists.assert_not_called()

    def test_legacy_daily_read_still_checks_native_read_permission(self):
        doc = MagicMock()
        doc.check_permission.side_effect = PermissionError
        self.frappe.get_doc.return_value = doc
        self.frappe.db.exists.return_value = "D"
        with self.assertRaises(PermissionError):
            self.daily.get_daily_meal_confirmation("2026-09-07")
        doc.check_permission.assert_called_once_with("read")

    def test_missing_hook_compatibility_is_idempotent_without_permission_changes(self):
        module = load_module("meal_roles_test", ROOT / "meal_attendance_roles.py")
        self.assertIsNone(module.install())
        self.assertIsNone(module.install())
        self.frappe.has_permission.assert_not_called()
        self.frappe.get_doc.assert_not_called()
        self.frappe.db.assert_not_called()


if __name__ == "__main__":
    unittest.main()
