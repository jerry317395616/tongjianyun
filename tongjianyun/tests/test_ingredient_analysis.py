from datetime import date
from decimal import Decimal
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


class IngredientAnalysisTests(unittest.TestCase):
    def setUp(self):
        frappe = ModuleType("frappe")
        utils = ModuleType("frappe.utils")
        utils.cint = int
        utils.flt = float
        utils.getdate = lambda value: value if isinstance(value, date) else date.fromisoformat(value)
        application = ModuleType("tongjianyun")
        application.meal_ledger = SimpleNamespace()
        spec = importlib.util.spec_from_file_location("ingredient_analysis_test", Path(__file__).parents[1] / "ingredient_analysis.py")
        self.analysis = importlib.util.module_from_spec(spec)
        modules = {"frappe": frappe, "frappe.utils": utils, "tongjianyun": application, spec.name: self.analysis}
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(self.analysis)
        self.visible = SimpleNamespace(can_read_orders=True, can_read_purchases=True)

    def kitchen_row(self, planned, actual, closed, loss=0):
        return dict(date="2026-11-20", planned_qty=planned, consumed_qty=actual, issued_qty=actual,
                    returned_qty=0, loss_qty=loss, closed=closed, complete_plan=True)

    def test_missing_execution_stays_unknown_and_cannot_raise_a_variance(self):
        quantities = self.analysis.Totals()
        quantities.add_kitchen(self.kitchen_row(15, None, False), date(2026, 11, 21))
        report = quantities.as_row(self.visible, Decimal(10))
        self.assertIsNone(report["consumed_qty"])
        self.assertIsNone(report["difference"])
        self.assertIn("日结待核对", report["status"])

    def test_closed_usage_and_actual_stock_loss_are_separate(self):
        quantities = self.analysis.Totals()
        quantities.add_kitchen(self.kitchen_row(15, 12, True, loss=3), date(2026, 11, 21))
        quantities.values["received_qty"] = Decimal(20)
        quantities.values["purchase_return_qty"] = Decimal(2)
        report = quantities.as_row(self.visible, Decimal(10))
        self.assertEqual((report["net_received_qty"], report["consumed_qty"], report["difference"]), (18, 12, -3))
        self.assertEqual(report["loss_rate"], 20)
        self.assertIn("有损耗", report["status"])
        self.assertIn("耗用偏差", report["status"])

    def test_unreadable_purchases_remain_blank_and_week_drills_are_clipped(self):
        result = self.analysis.Totals().as_row(SimpleNamespace(can_read_orders=False, can_read_purchases=False), Decimal(0))
        self.assertIsNone(result["ordered_qty"])
        self.assertIsNone(result["net_received_qty"])
        source = SimpleNamespace(start=date(2026, 11, 19), end=date(2026, 11, 21))
        self.assertEqual(self.analysis._bounds(source, "2026-11-16", self.analysis.WEEK), ("2026-11-19", "2026-11-21"))

    def test_trend_does_not_plot_unconfirmed_usage_as_zero(self):
        rows = [
            dict(period="2026-11-19", stock_uom="公斤", net_received_qty=12, planned_qty=8, consumed_qty=6),
            dict(period="2026-11-20", stock_uom="公斤", net_received_qty=0, planned_qty=8, consumed_qty=None),
        ]
        chart = self.analysis._chart(rows)
        self.assertEqual([series["name"] for series in chart["data"]["datasets"]], ["净到货", "计划用量"])
