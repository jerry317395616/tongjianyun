import unittest
from unittest.mock import patch

from tongjianyun import recipe_procurement as service
from tongjianyun import attendance_scope, daily_meals


class RosterDefaultsTests(unittest.TestCase):
    def test_only_missing_current_and_future_are_estimated(self):
        rows = [dict(date=d, count=n) for d, n in [
            ("2026-09-10", None), ("2026-09-11", None),
            ("2026-09-12", None), ("2026-09-11", 0), ("2026-09-12", 18)]]
        service._fill_roster_estimates(rows, "2026-09-11", 257)
        self.assertEqual([r["count"] for r in rows], [None, 257, 257, 0, 18])
        self.assertEqual(rows[1]["count_source"], "student_roster")
        self.assertNotIn("count_source", rows[3])

    def test_no_roster_is_not_confirmed_zero(self):
        rows = [dict(date="2026-09-11", count=None)]
        service._fill_roster_estimates(rows, "2026-09-11", None)
        self.assertIsNone(rows[0]["count"])

    def estimate(self, manager=True, scope=("A", "B"), readable=("S1", "S2"), students=("S1", "S2")):
        with patch.object(attendance_scope, "is_manager", return_value=manager), \
             patch.object(attendance_scope, "allowed_groups", return_value=list(scope)), \
             patch.object(daily_meals, "_active_groups", return_value=[{"name": "A"}, {"name": "B"}]), \
             patch.object(daily_meals, "_active_students", return_value=list(students)), \
             patch.object(service.frappe, "has_permission", return_value=True), \
             patch.object(service.frappe, "get_list", return_value=list(readable)):
            return service._roster_estimate()

    def test_duplicate_membership_is_deduplicated(self):
        self.assertEqual(self.estimate(), 2)

    def test_teacher_cannot_return_partial_total(self):
        self.assertIsNone(self.estimate(manager=False))

    def test_incomplete_group_visibility_is_not_total(self):
        self.assertIsNone(self.estimate(scope=("A",)))

    def test_incomplete_student_visibility_is_not_total(self):
        self.assertIsNone(self.estimate(readable=("S1",)))

    def test_empty_roster_requires_review(self):
        self.assertIsNone(self.estimate(students=()))
