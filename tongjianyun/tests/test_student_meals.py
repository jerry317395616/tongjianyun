import unittest
from unittest.mock import patch, MagicMock
from datetime import date

import frappe
from frappe import _dict
from tongjianyun import student_meals as service
from tongjianyun import daily_meals as daily


class MealRow(_dict):
    def set(self, key, value):
        self[key] = value


class StudentMealsTests(unittest.TestCase):
    def test_new_snapshot_does_not_assume_zero_expected_dinner_is_not_served(self):
        doc = _dict(students=[])
        doc.append = lambda key, row: doc.students.append(MealRow(row))
        roster = [{"student": "S1", "student_name": "学生", "attendance_status": "Unknown",
                   **{meal: int(meal != "dinner") for meal in service.MEALS}}]
        with patch.object(service.frappe, "db", MagicMock(exists=MagicMock(return_value=False))), \
             patch.object(service.frappe, "new_doc", return_value=doc), \
             patch.object(service, "_roster", return_value=roster):
            result = service._load("2026-09-11", "C1")
        self.assertTrue(all(result.students[0][meal] == "未确认" for meal in service.MEALS))
        self.assertEqual(result.students[0].dinner_expected, 0)
        self.assertIsNone(service.meal_facts(result.students)["dinner"]["actual"])

    def row(self, state="已就餐"):
        row = MealRow(student="S1", student_name="学生", attendance_hint="Present")
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
        self.assertIsNone(service.meal_counts(rows)["lunch_count"])
        self.assertEqual(service.meal_counts(rows, True)["lunch_count"], 4)
        self.assertEqual(service.meal_facts(rows)["lunch"]["confirmed_subtotal"], 1)
        self.assertEqual(service.meal_facts(rows)["lunch"]["pending_count"], 1)

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

    def test_pending_day_can_contain_one_confirmed_meal(self):
        doc = self.doc("待确认"); doc.students[0].lunch = "已就餐"
        self.validate(doc)
        self.assertEqual(doc.status, "待确认")
        self.assertIsNone(doc.confirmed_at)
        self.assertEqual(service.meal_facts(doc.students)["lunch"]["actual"], 1)
        self.assertIsNone(service.meal_facts(doc.students)["dinner"]["actual"])

    def test_partial_future_actual_cannot_hide_behind_pending_day(self):
        doc = self.doc("待确认"); doc.meal_date = "2026-09-12"; doc.students[0].lunch = "已就餐"
        with self.assertRaises(ValueError): self.validate(doc)

    def test_partial_confirmed_meal_change_requires_reason(self):
        old = self.doc("待确认"); old.students[0].lunch = "已就餐"
        doc = self.doc("待确认", old=old); doc.students[0].lunch = "未就餐"
        with self.assertRaises(ValueError): self.validate(doc)
        doc.change_reason = "离园后没有就餐"
        self.validate(doc)

    def test_confirming_another_meal_preserves_prior_fact_without_correction_reason(self):
        old = self.doc("待确认"); old.students[0].breakfast = "已就餐"
        doc = self.doc("待确认", old=old)
        doc.students[0].breakfast = "已就餐"; doc.students[0].lunch = "未就餐"
        self.validate(doc)
        self.assertEqual(doc.students[0].breakfast, "已就餐")

    def test_final_served_meal_automatically_completes_day(self):
        doc = self.doc("待确认")
        for meal in service.MEALS:
            doc.students[0][meal] = "已就餐" if meal != "dinner" else "不供餐"
        self.validate(doc)
        self.assertEqual(doc.status, "已确认")
        self.assertEqual(doc.confirmed_by, "teacher")

    def test_unchecked_dinner_prevents_auto_confirmation_even_if_expected_zero(self):
        doc = self.doc("待确认")
        for meal in service.MEALS:
            doc.students[0][meal] = "已就餐" if meal != "dinner" else "未确认"
        doc.students[0].dinner_expected = 0
        self.validate(doc)
        self.assertEqual(doc.status, "待确认")
        self.assertIsNone(service.meal_facts(doc.students)["dinner"]["actual"])

    def test_nonservice_and_empty_roster_are_distinct(self):
        no_service = service.meal_facts([self.row("不供餐")])["dinner"]
        self.assertEqual(no_service["status"], "不供餐")
        self.assertTrue(no_service["complete"])
        self.assertEqual(no_service["actual"], 0)
        empty = service.meal_facts([])["dinner"]
        self.assertFalse(empty["complete"])
        self.assertIsNone(empty["actual"])

    def test_planning_counts_mix_only_complete_actuals_with_expected(self):
        row = self.row("未确认")
        row.lunch = "未就餐"
        counts = service.planning_counts([row])
        self.assertEqual(counts["lunch_count"], 0)
        self.assertEqual(counts["breakfast_count"], 1)
        self.assertIsNone(service.meal_counts([row])["breakfast_count"])

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
            with self.assertRaises(PermissionError): service.save_class_meal("2026-09-11", "C2", "lunch", [])
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

    def editable_doc(self, status="待确认"):
        doc = self.doc(status)
        doc.modified = "r1"
        doc.is_new = lambda: False
        doc.save = MagicMock()
        doc.add_comment = MagicMock()
        doc.check_permission = MagicMock()
        return doc

    def save_one(self, doc, *, confirm=1, value="不就餐", revision="r1", students=None):
        students = students if students is not None else [{"student": "S1", "value": value}]
        with patch.object(service, "_editor"), patch.object(service, "_load", return_value=doc), \
             patch.object(service, "get_class_meals", return_value={"saved": True}), \
             patch.object(service, "nowdate", return_value="2026-09-11"), \
             patch.object(service.frappe, "db", MagicMock()), patch.object(service.frappe, "throw", side_effect=ValueError):
            return service.save_class_meal("2026-09-11", "C1", "lunch", students, revision, confirm)

    def test_single_confirmation_changes_only_the_selected_meal(self):
        doc = self.editable_doc()
        before = {meal: (doc.students[0][meal], doc.students[0][meal + "_expected"])
                  for meal in service.MEALS if meal != "lunch"}
        self.assertEqual(self.save_one(doc), {"saved": True})
        self.assertEqual(doc.students[0].lunch, "未就餐")
        self.assertEqual(doc.status, "待确认")
        self.assertEqual(before, {meal: (doc.students[0][meal], doc.students[0][meal + "_expected"])
                                  for meal in before})
        doc.save.assert_called_once_with()
        doc.add_comment.assert_called_once()

    def test_save_estimate_does_not_erase_single_confirmed_actual(self):
        doc = self.editable_doc()
        doc.students[0].lunch = "已就餐"
        self.save_one(doc, confirm=0)
        self.assertEqual(doc.students[0].lunch, "已就餐")
        doc.add_comment.assert_not_called()

    def test_confirming_four_actual_preserves_five_expected(self):
        doc = self.editable_doc()
        doc.students = [self.row("未确认") for _ in range(5)]
        for i, row in enumerate(doc.students):
            row.student = "S" + str(i + 1)
        values = [{"student": row.student, "value": "就餐" if i < 4 else "不就餐"}
                  for i, row in enumerate(doc.students)]
        self.save_one(doc, students=values)
        facts = service.meal_facts(doc.students)["lunch"]
        self.assertEqual(facts["expected"], 5)
        self.assertEqual(facts["actual"], 4)
        doc.check_permission.assert_called_once_with("write")

    def test_record_read_permission_checked_before_serializing(self):
        doc = self.editable_doc()
        doc.check_permission.side_effect = PermissionError
        doc.as_dict = MagicMock()
        with patch.object(service.frappe, "has_permission", return_value=True), \
             patch.object(service, "allowed_groups", return_value=["C1"]), \
             patch.object(service, "require_group"), patch.object(service.frappe, "db", MagicMock()), \
             patch.object(service, "_load", return_value=doc):
            with self.assertRaises(PermissionError):
                service.get_class_meals("2026-09-11", "C1")
        doc.as_dict.assert_not_called()

    def test_single_stale_duplicate_and_extra_meal_rejected(self):
        cases = [{'revision': 'stale'}, {'students': [{'student': 'S2', 'value': '就餐'}]},
                 {'students': [{'student': 'S1', 'value': '就餐'}, {'student': 'S1', 'value': '就餐'}]},
                 {'students': [{'student': 'S1', 'value': '就餐', 'dinner': '就餐'}]},
                 {'students': [{'student': 'S1', 'value': []}]},
                 {'students': [{'student': [], 'value': '就餐'}]}]
        for case in cases:
            doc = self.editable_doc()
            with self.subTest(case=case), self.assertRaises(ValueError):
                self.save_one(doc, **case)
            doc.save.assert_not_called()

    def test_legacy_estimate_preserves_already_confirmed_meal(self):
        doc = self.editable_doc(); doc.students[0].lunch = "已就餐"
        students = [{"student": "S1", **{meal: "就餐" for meal in service.MEALS}}]
        with patch.object(service, "_editor"), patch.object(service, "_load", return_value=doc), \
             patch.object(service, "get_class_meals", return_value={}), patch.object(service.frappe, "db", MagicMock()), \
             patch.object(service, "nowdate", return_value="2026-09-11"):
            service.save_class_meals("2026-09-11", "C1", students, revision="r1", confirm=0)
        self.assertEqual(doc.students[0].lunch, "已就餐")
        self.assertEqual(doc.students[0].breakfast, "未确认")

    def test_legacy_explicit_all_meal_confirmation_remains_supported(self):
        doc = self.editable_doc()
        students = [{"student": "S1", **{meal: "就餐" for meal in service.MEALS}}]
        with patch.object(service, "_editor"), patch.object(service, "_load", return_value=doc), \
             patch.object(service, "get_class_meals", return_value={}), patch.object(service.frappe, "db", MagicMock()):
            service.save_class_meals("2026-09-11", "C1", students, revision="r1", confirm=1)
        self.assertEqual(doc.status, "已确认")
        self.assertTrue(all(doc.students[0][meal] == "已就餐" for meal in service.MEALS))

    def test_class_completion_is_per_meal_and_does_not_trust_legacy_day_label(self):
        doc = self.doc("待确认"); doc.students[0].lunch = "未就餐"
        rows = [{"student_group": "C1", "enrolled_count": 1}]
        with patch.object(service.frappe, "db", MagicMock()), patch.object(service.frappe, "get_doc", return_value=doc), \
             patch.object(service, "nowdate", return_value="2026-09-11"):
            self.assertTrue(service.all_classes_confirmed(rows, "2026-09-11", "lunch"))
            self.assertFalse(service.all_classes_confirmed(rows, "2026-09-11"))
            self.assertFalse(service.all_classes_confirmed(rows, "2026-09-12", "lunch"))


class DailyMealCompatibilityTests(unittest.TestCase):
    def test_legacy_daily_confirm_only_refreshes_and_never_unlocks_or_saves_twice(self):
        doc = MagicMock()
        doc.status = "已锁定"
        doc.as_dict.return_value = {"status": "已锁定"}
        with patch.object(daily, "require_manager"), patch.object(daily, "calculate_rows", return_value=[]), \
             patch.object(service, "all_classes_confirmed", return_value=True), \
             patch.object(daily.frappe, "db", MagicMock()), patch.object(daily.frappe, "get_doc", return_value=doc), \
             patch.object(daily, "refresh_confirmation", return_value=doc) as refresh:
            result = daily.confirm_daily_meal("2026-09-11")
        self.assertEqual(result["status"], "已锁定")
        refresh.assert_called_once_with("2026-09-11", force=True)
        doc.save.assert_not_called()

    def test_daily_cannot_confirm_expected_counts_as_actual(self):
        with patch.object(daily, "require_manager"), patch.object(daily, "calculate_rows", return_value=[]), \
             patch.object(service, "all_classes_confirmed", return_value=False), \
             patch.object(daily.frappe, "throw", side_effect=ValueError), patch.object(daily, "refresh_confirmation") as refresh:
            with self.assertRaises(ValueError):
                daily.confirm_daily_meal("2026-09-11")
        refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
