import unittest
from unittest.mock import patch, MagicMock
from datetime import date

import frappe
from frappe import _dict
from tongjianyun import student_meals as service


class StudentMealsTests(unittest.TestCase):
    def row(self, state="已就餐"):
        row = _dict(student="S1", student_name="学生", attendance_hint="Present")
        for meal in service.MEALS:
            row[meal] = state
            row[meal + "_expected"] = 1
        return row

    def doc(self, status="已确认", old=None):
        return _dict(meal_date="2026-09-11", student_group="C1", status=status,
                     students=[self.row("未确认" if status == "待确认" else "已就餐")],
                     change_reason="", get_doc_before_save=lambda: old)

    def validate(self, doc, locked=None):
        with patch.object(service, "_editor"), patch.object(service, "_roster", return_value=[_dict(student="S1", student_name="学生", attendance_status="Present")]), \
                patch.object(service.frappe, "db", MagicMock(get_value=MagicMock(return_value=locked))), \
                patch.object(service, "nowdate", return_value="2026-09-11"), \
                patch.object(service, "now_datetime", return_value="2026-09-11 18:00:00"), \
                patch.object(service.frappe, "session", _dict(user="teacher")), \
                patch.object(service.frappe, "throw", side_effect=ValueError):
            service.validate(doc)

    def test_counts_distinguish_unknown_not_eating_and_outside_service(self):
        rows = [self.row(s) for s in ["已就餐", "未就餐", "未确认", "不供餐"]]
        self.assertEqual(service.meal_counts(rows)["lunch_count"], 1)
        self.assertEqual(service.meal_counts(rows, True)["lunch_count"], 4)

    def test_specific_meal_does_not_change_other_meals(self):
        row = self.row()
        row.lunch = "未就餐"
        self.assertEqual(service.meal_counts([row])["lunch_count"], 0)
        self.assertEqual(service.meal_counts([row])["breakfast_count"], 1)

    def test_future_actual_confirmation_rejected(self):
        doc = self.doc(); doc.meal_date = "2026-09-12"
        with self.assertRaises(ValueError): self.validate(doc)

    def test_future_expected_allowed(self):
        doc = self.doc("待确认"); doc.meal_date = "2026-09-12"
        self.validate(doc)
        self.assertIsNone(doc.confirmed_at)

    def test_unknown_cannot_be_confirmed(self):
        doc = self.doc(); doc.students[0].lunch = "未确认"
        with self.assertRaises(ValueError): self.validate(doc)

    def test_plan_cannot_contain_actual_facts(self):
        doc = self.doc("待确认"); doc.students[0].lunch = "已就餐"
        with self.assertRaises(ValueError): self.validate(doc)

    def test_duplicate_student_rejected(self):
        doc = self.doc(); doc.students.append(self.row())
        with self.assertRaises(ValueError): self.validate(doc)

    def test_out_of_class_student_rejected(self):
        doc = self.doc(); doc.students[0].student = "S2"
        with self.assertRaises(ValueError): self.validate(doc)

    def test_locked_date_rejected(self):
        with self.assertRaises(ValueError): self.validate(self.doc(), "已锁定")

    def test_confirmed_edit_requires_reason(self):
        old = self.doc()
        with self.assertRaises(ValueError): self.validate(self.doc(old=old))
        doc = self.doc(old=old); doc.change_reason = "午餐临时未吃"
        self.validate(doc)
        self.assertEqual(doc.confirmed_by, "teacher")

    def test_identity_and_attendance_hint_cannot_be_forged(self):
        doc = self.doc(); doc.students[0].student_name = "伪造"; doc.students[0].attendance_hint = "Absent"
        self.validate(doc)
        self.assertEqual(doc.students[0].student_name, "学生")
        self.assertEqual(doc.students[0].attendance_hint, "Present")

    def test_record_key_cannot_move(self):
        old = self.doc(); doc = self.doc(old=old); doc.student_group = "C2"
        with self.assertRaises(ValueError): self.validate(doc)

    def test_permission_checked_before_any_write(self):
        with patch.object(service, "_editor", side_effect=PermissionError), patch.object(service, "_load") as load:
            with self.assertRaises(PermissionError): service.save_class_meals("2026-09-11", "C2", [])
            load.assert_not_called()

    def test_stale_revision_rejected_before_save(self):
        doc = self.doc(); doc.modified = "new"; doc.is_new = lambda: False; doc.save = MagicMock()
        with patch.object(service, "_editor"), patch.object(service, "_load", return_value=doc), \
                patch.object(service.frappe, "db", MagicMock()), patch.object(service.frappe, "throw", side_effect=ValueError):
            with self.assertRaises(ValueError): service.save_class_meals("2026-09-11", "C1", [], "old")
            doc.save.assert_not_called()

    def test_record_names_are_stable_and_class_scoped(self):
        self.assertEqual(service.record_name(date(2026, 9, 11), "C1"), service.record_name("2026-09-11", "C1"))
        self.assertNotEqual(service.record_name("2026-09-11", "C1"), service.record_name("2026-09-11", "C2"))

    def test_zero_students_not_automatically_confirmed(self):
        with patch.object(service.frappe, "db", MagicMock()):
            self.assertFalse(service.all_classes_confirmed([], "2026-09-11"))
            self.assertFalse(service.all_classes_confirmed([{"student_group":"C1", "enrolled_count":0}], "2026-09-11"))


if __name__ == "__main__":
    unittest.main()
