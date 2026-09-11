"""Teacher permission hooks are deny-only and do not accept request identities."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / "teacher_permissions.py"
spec = importlib.util.spec_from_file_location("teacher_permissions_test", PATH)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class TeacherPermissionTests(unittest.TestCase):
    def test_administrator_is_not_restricted(self):
        with patch.object(mod.frappe, "get_roles") as roles:
            self.assertFalse(mod.is_scoped_teacher("Administrator"))
            roles.assert_not_called()

    def test_only_teacher_roles_without_manager_roles_are_scoped(self):
        for roles, expected in [(["Instructor"], True), (["Tongjianyun Business Operator"], False), (["Instructor", "System Manager"], False), (["Employee"], False)]:
            with self.subTest(roles=roles), patch.object(mod.frappe, "get_roles", return_value=roles):
                self.assertEqual(mod.is_scoped_teacher("test"), expected)

    def test_missing_identity_link_returns_empty(self):
        for responses in [[[]], [["E"], []], [["E"], ["I"], []], [["E"], ["I"], ["A"], []]]:
            with self.subTest(responses=responses), patch.object(mod.frappe, "get_all", side_effect=responses):
                self.assertEqual(mod.assignment("teacher"), ([], []))

    def test_assignment_uses_explicit_framework_user_and_active_membership(self):
        with patch.object(mod.frappe, "get_all", side_effect=[["E"], ["I"], ["A"], ["A"], ["S", "S"]]) as query:
            self.assertEqual(mod.assignment("teacher"), (["A"], ["S"]))
            self.assertEqual(query.call_args_list[0].kwargs["filters"], {"user_id": "teacher", "status": "Active"})
            self.assertEqual(query.call_args_list[-1].kwargs["filters"]["active"], 1)

    def test_no_groups_produces_deny_all_list_filter(self):
        with patch.object(mod, "is_scoped_teacher", return_value=True), patch.object(mod, "assignment", return_value=([], [])):
            self.assertEqual(mod.query_condition("teacher", "Student Group"), "1=0")
            self.assertEqual(mod.query_condition("teacher", "Student"), "1=0")

    def test_other_roles_keep_existing_permission_checks(self):
        with patch.object(mod, "is_scoped_teacher", return_value=False), patch.object(mod, "assignment") as query:
            self.assertEqual(mod.query_condition("manager", "Student"), "")
            self.assertTrue(mod.document_permission(SimpleNamespace(doctype="Student"), user="manager"))
            query.assert_not_called()

    def test_direct_document_reads_are_scoped(self):
        with patch.object(mod, "is_scoped_teacher", return_value=True), patch.object(mod, "assignment", return_value=(["A"], ["S"])):
            for dt, name, expected in [("Student", "S", True), ("Student", "OTHER", False), ("Student Group", "A", True), ("Student Group", "B", False)]:
                with self.subTest(dt=dt, name=name):
                    self.assertEqual(mod.document_permission(SimpleNamespace(doctype=dt, name=name), ptype="read", user="teacher"), expected)

    def test_attendance_and_leave_require_both_class_and_student(self):
        with patch.object(mod, "is_scoped_teacher", return_value=True), patch.object(mod, "assignment", return_value=(["A"], ["S"])):
            for dt in ["Student Attendance", "Student Leave Application"]:
                for student, group, expected in [("S", "A", True), ("S", "B", False), ("OTHER", "A", False), ("S", None, False)]:
                    row = {"student": student, "student_group": group}
                    with self.subTest(dt=dt, row=row):
                        self.assertEqual(mod.document_permission(SimpleNamespace(doctype=dt, get=row.get), user="teacher"), expected)


if __name__ == "__main__":
    unittest.main()
