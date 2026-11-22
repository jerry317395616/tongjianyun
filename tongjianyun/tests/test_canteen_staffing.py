from datetime import date, datetime, time
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


class CanteenStaffingTests(unittest.TestCase):
    def setUp(self):
        frappe = ModuleType("frappe")
        utils = ModuleType("frappe.utils")
        utils.cint = int
        utils.flt = lambda value: float(value or 0)
        utils.get_datetime = lambda value: value if isinstance(value, datetime) else datetime.fromisoformat(value)
        utils.get_time = time.fromisoformat
        utils.getdate = lambda value: value if isinstance(value, date) else date.fromisoformat(value)
        utils.now_datetime = datetime.now
        app = ModuleType("tongjianyun")
        app.meal_ledger = SimpleNamespace()
        special = ModuleType("tongjianyun.special_ingredients")
        special._lock_company = lambda _: None
        path = Path(__file__).parents[1] / "canteen_staffing.py"
        spec = importlib.util.spec_from_file_location("canteen_staffing_test", path)
        self.staffing = importlib.util.module_from_spec(spec)
        modules = {"frappe": frappe, "frappe.utils": utils, "tongjianyun": app,
                   "tongjianyun.special_ingredients": special, spec.name: self.staffing}
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(self.staffing)

    def test_overnight_coverage_uses_the_correct_calendar_day(self):
        rule = SimpleNamespace(coverage_start="00:00:00", coverage_end="02:00:00")
        shift = SimpleNamespace(start_time="22:00:00", end_time="06:00:00")
        day = self.staffing.linked_window(rule, date(2026, 11, 20), shift)
        self.assertEqual(day, (datetime(2026, 11, 21), datetime(2026, 11, 21, 2)))
        row = SimpleNamespace(status="Half Day", in_time="2026-11-20 23:00:00", out_time="2026-11-21 00:30:00")
        self.assertEqual(self.staffing._attendance([row], day, True), ("partial", 0.5))
        row.out_time = "2026-11-21 02:00:00"
        self.assertEqual(self.staffing._attendance([row], day, True), ("present", 2))

    def test_absence_and_missing_confirmation_are_distinct(self):
        window = (datetime(2026, 11, 20, 10), datetime(2026, 11, 20, 12))
        self.assertEqual(self.staffing._attendance([], window, True), ("pending", None))
        self.assertEqual(self.staffing._attendance([SimpleNamespace(status="Absent")], window, True), ("absent", None))
        half_day = SimpleNamespace(status="Half Day", in_time=None, out_time=None)
        self.assertEqual(self.staffing._attendance([half_day], window, True), ("pending", None))
