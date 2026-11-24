"""Regression checks for the calendar shared by menu editing and kitchen tasks."""
import importlib.util
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class Week(dict):
    __getattr__ = dict.get


class MealServiceCalendarTests(unittest.TestCase):
    def setUp(self):
        self.db = Mock()
        self.start = date(2026, 11, 23)
        self.week = Week(week_start=self.start, company="园所", custom_tjy_canteen="一食堂", docstatus=0)
        self.term_weeks = Mock()
        path = Path(__file__).parents[1] / "canteen_ops" / "service_calendar.py"
        spec = importlib.util.spec_from_file_location("calendar_under_test", path)
        self.calendar = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "frappe": self.db,
            "frappe.utils": SimpleNamespace(getdate=lambda d: d),
            "tongjianyun.canteen_ops.common": SimpleNamespace(CANTEEN="Canteen", TERM="Term"),
            "tongjianyun.canteen_ops.term_schedule": SimpleNamespace(term_weeks=self.term_weeks),
        }):
            spec.loader.exec_module(self.calendar)

    def test_partial_week_preserves_other_suspensions(self):
        tuesday = date(2026, 11, 24)
        self.db.get_all.return_value = ["Term 1"]
        self.term_weeks.return_value = {self.start: {"days": [tuesday]}}
        closed = SimpleNamespace(meal_date=self.start, service_suspended=0)
        manually_stopped = SimpleNamespace(meal_date=tuesday, service_suspended=1, suspension_reason="临时停餐")
        self.week["meals"] = [closed, manually_stopped]
        self.calendar.apply_calendar(self.week)
        self.assertEqual((closed.service_suspended, closed.suspension_reason), (1, "学期供餐日历停供"))
        self.assertEqual(manually_stopped.suspension_reason, "临时停餐")

    def test_established_five_day_default_outside_term(self):
        self.db.get_all.return_value = []
        self.assertEqual(self.calendar.scheduled_dates(self.week), {date(2026, 11, n) for n in range(23, 28)})

    def test_submitted_week_preserves_approved_service_flags(self):
        self.week.update(docstatus=1, meals=[SimpleNamespace(meal_date=self.start, service_suspended=0)])
        self.calendar.apply_calendar(self.week)
        self.assertEqual(self.week.meals[0].service_suspended, 0)
        self.db.get_all.assert_not_called()
