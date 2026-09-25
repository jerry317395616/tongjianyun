"""Read-model and boundary tests; no writes to production business records."""
import unittest
from datetime import date
from unittest.mock import MagicMock, patch

import frappe
from frappe import _dict
from tongjianyun import classroom as service


class ClassroomFactsTests(unittest.TestCase):
    roster = [{"student": "S1", "student_name": "测试一"}, {"student": "S2", "student_name": "测试二"}, {"student": "S3", "student_name": "测试三"}]

    def test_missing_is_unknown_not_present(self):
        students, counts = service.attendance_facts(self.roster, [], [])
        self.assertEqual(counts["Unknown"], 3)
        self.assertEqual(counts["Present"], 0)
        self.assertTrue(all(r["status"] == "Unknown" for r in students))

    def test_counts_partition_roster_and_exclude_other_class(self):
        rows = [{"student": "S1", "status": "Present"}, {"student": "S2", "status": "Absent"}, {"student": "OTHER", "status": "Present"}]
        _, counts = service.attendance_facts(self.roster, rows, [{"student": "S3"}])
        self.assertEqual(counts, {"Present": 1, "Absent": 1, "Leave": 1, "Unknown": 0, "total": 3, "rate": 33.3})

    def test_latest_record_wins(self):
        rows, _ = service.attendance_facts(self.roster, [{"student":"S1","status":"Absent"},{"student":"S1","status":"Present"}], [])
        self.assertEqual(rows[0]["status"], "Absent")

    def test_absence_and_leave_precedence_match_meal_workflow(self):
        rows, _ = service.attendance_facts(self.roster, [{"student":"S1","status":"Absent"},{"student":"S2","status":"Present"}], [{"student":"S1"},{"student":"S2"}])
        self.assertEqual([r["status"] for r in rows], ["Absent","Leave","Unknown"])

    def test_unknown_raw_status_is_not_presence(self):
        rows, _ = service.attendance_facts(self.roster, [{"student":"S1","status":"bad"}], [])
        self.assertEqual(rows[0]["status"], "Unknown")

    def test_zero_roster_has_no_fake_rate(self):
        _, counts = service.attendance_facts([], [], [])
        self.assertIsNone(counts["rate"])

    def test_health_unknown_is_not_explicitly_none(self):
        result = service.health_counts(["S1","S2","S3"], [{"student":"S1","review_status":"已核对","allergy_state":"明确无"}, {"student":"S2","review_status":"待核对","allergy_state":"已登记"}, {"student":"OTHER","allergy_state":"已登记"}])
        self.assertEqual(result, {"total":3,"registered":2,"unregistered":1,"pending":1,"allergy_declared":1})

    def test_date_validation_is_strict(self):
        self.assertEqual(service._day("2026-09-23"), date(2026,9,23))
        with patch.object(service.frappe, "throw", side_effect=ValueError):
            for value in ["tomorrow", "2026-02-31", "20260923", "2026-W39-3", "2026-09-23T08:00", "<script>"]:
                with self.subTest(value=value), self.assertRaises(ValueError): service._day(value)


class ClassroomBoundaryTests(unittest.TestCase):
    def test_attendance_capability_delegates_without_granting_daily_permissions(self):
        for allowed in (True, False):
            with self.subTest(allowed=allowed), patch.object(service.frappe, "get_roles", return_value=["Instructor"]), \
                 patch.object(service.frappe, "db", MagicMock(get_value=MagicMock(return_value=None))), \
                 patch.object(service, "today", return_value="2026-09-23"), patch.object(service, "_can", return_value=False), \
                 patch.object(service, "_health_allowed", return_value=False), \
                 patch("tongjianyun.daily_meals.attendance_write_allowed", return_value=allowed) as capability:
                result = service._capabilities(date(2026, 9, 23))
            self.assertEqual(result["attendance_write"], allowed)
            capability.assert_called_once_with(date(2026, 9, 23))

    def test_single_meal_save_preserves_scope_revision_and_reason(self):
        with patch.object(service, '_scope', return_value=_dict(name='C1')), \
             patch.object(service, '_capabilities', return_value={'meals_write': True}), \
             patch('tongjianyun.student_meals.save_class_meal') as save:
            rows = [{'student': 'S1', 'value': '不就餐'}]
            result = service.save_meal('C1', '2026-09-23', 'lunch', rows, 'revision', 1, '午餐前离园')
        self.assertTrue(result['saved'])
        save.assert_called_once_with('2026-09-23', 'C1', 'lunch', rows, 'revision', 1, '午餐前离园')

    def test_single_meal_locked_cannot_call_save(self):
        with patch.object(service, '_scope', return_value=_dict(name='C1')), \
             patch.object(service, '_capabilities', return_value={'meals_write': False}), \
             patch('tongjianyun.student_meals.save_class_meal') as save:
            with self.assertRaises(frappe.PermissionError):
                service.save_meal('C1', '2026-09-23', 'lunch', [], 'revision', 1)
        save.assert_not_called()

    def test_guest_cannot_read(self):
        with patch.object(service.frappe, "session", _dict(user="Guest"), create=True), patch.object(service.frappe, "db", MagicMock(), create=True):
            with self.assertRaises(frappe.PermissionError): service.require_user()

    def test_disabled_user_cannot_read(self):
        with patch.object(service.frappe, "session", _dict(user="teacher"), create=True), patch.object(service.frappe, "db", MagicMock(get_value=MagicMock(return_value=0)), create=True):
            with self.assertRaises(frappe.PermissionError): service.require_user()

    def test_outside_group_fails_before_document_read(self):
        with patch.object(service, "require_user"), patch.object(service, "allowed_groups", return_value=["C1"]), patch.object(service.frappe, "get_doc") as get_doc:
            with self.assertRaises(frappe.PermissionError): service._scope("C2")
            get_doc.assert_not_called()

    def test_medical_records_are_never_requested_by_general_log_view(self):
        with patch.object(service, "_can", return_value=True), patch.object(service.frappe, "get_list", return_value=[]) as get_list:
            service._logs(["S1"], date(2026,9,23))
            self.assertNotIn("Medical", get_list.call_args.kwargs["filters"]["type"][1])

    def test_health_summary_does_not_query_sensitive_rows_without_role(self):
        with patch.object(service, "_health_allowed", return_value=False), patch.object(service.frappe, "get_list") as get_list:
            result = service._health_summary("C1", date(2026,9,23), ["S1"])
            self.assertFalse(result["available"])
            self.assertNotIn("allergy_declared", result)
            get_list.assert_not_called()

    def test_health_detail_requires_dedicated_role(self):
        with patch.object(service, "_scope"), patch.object(service, "_health_allowed", return_value=False), patch.object(service, "_roster") as roster:
            with self.assertRaises(frappe.PermissionError): service.get_health("C1", "2026-09-23")
            roster.assert_not_called()

    def test_record_foreign_student_fails_before_insert(self):
        with patch.object(service, "_scope"), patch.object(service, "_roster", return_value=[{"student":"S1"}]), patch.object(service, "today", return_value="2026-09-23"), patch.object(service.frappe, "new_doc") as new_doc:
            with self.assertRaises(frappe.PermissionError): service.add_record("C1","S2","2026-09-23","General","内容")
            new_doc.assert_not_called()

    def test_record_future_and_medical_rejected(self):
        with patch.object(service, "_scope"), patch.object(service, "_roster", return_value=[{"student":"S1"}]), patch.object(service, "today", return_value="2026-09-23"), patch.object(service.frappe, "throw", side_effect=ValueError), patch.object(service.frappe, "new_doc") as new_doc:
            with self.assertRaises(ValueError): service.add_record("C1","S1","2026-09-24","General","内容")
            with self.assertRaises(ValueError): service.add_record("C1","S1","2026-09-23","Medical","内容")
            new_doc.assert_not_called()

    def test_record_escapes_text_and_does_not_ignore_permissions(self):
        doc = MagicMock()
        with patch.object(service, "_scope"), patch.object(service, "_roster", return_value=[{"student":"S1"}]), patch.object(service, "today", return_value="2026-09-23"), patch.object(service.frappe, "has_permission"), patch.object(service.frappe, "new_doc", return_value=doc):
            service.add_record("C1","S1","2026-09-23","General","<script>alert(1)</script>\n观察")
            self.assertNotIn("<script>", doc.log)
            self.assertIn("&lt;script&gt;", doc.log)
            doc.insert.assert_called_once_with()

    def test_stale_attendance_fails_before_existing_workflow(self):
        with patch.object(service, "_scope"), patch.object(service, "_capabilities", return_value={"attendance_write":True}), patch.object(service, "_attendance", return_value={"revision":"new","students":[{"student":"S1"}]}), patch.object(service.frappe, "db", MagicMock(), create=True), patch.object(service.frappe, "throw", side_effect=ValueError), patch("tongjianyun.daily_meals.save_student_meal_attendance") as save:
            with self.assertRaises(ValueError): service.save_attendance("C1","2026-09-23",[{"student":"S1","status":"Present"}],"old")
            save.assert_not_called()

    def test_attendance_cross_class_duplicates_and_missing_reason_rejected(self):
        with patch.object(service, "_scope"), patch.object(service, "_capabilities", return_value={"attendance_write":True}), patch.object(service, "_attendance", return_value={"revision":"new","students":[{"student":"S1"}]}), patch.object(service.frappe, "db", MagicMock(), create=True), patch.object(service.frappe, "throw", side_effect=ValueError), patch("tongjianyun.daily_meals.save_student_meal_attendance") as save:
            for changes in [[{"student":"OTHER","status":"Present"}], [{"student":"S1","status":"Unknown"}], [{"student":"S1","status":"Leave"}], [{"student":"S1","status":"Present"}]*2]:
                with self.subTest(changes=changes), self.assertRaises(ValueError): service.save_attendance("C1","2026-09-23",changes,"new")
            save.assert_not_called()

    def test_attendance_delegates_only_validated_class(self):
        with patch.object(service, "_scope"), patch.object(service, "_capabilities", return_value={"attendance_write":True}), patch.object(service, "_attendance", return_value={"revision":"new","students":[{"student":"S1"}]}), patch.object(service.frappe, "db", MagicMock(), create=True), patch("tongjianyun.daily_meals.save_student_meal_attendance") as save:
            result = service.save_attendance("C1","2026-09-23",[{"student":"S1","student_group":"FORGED","status":"Present"}],"new")
            self.assertEqual(result["saved"], 1)
            self.assertEqual(save.call_args.args[1][0]["student_group"], "C1")


if __name__ == "__main__": unittest.main()
