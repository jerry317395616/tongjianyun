import importlib.util
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class TermProjectTests(unittest.TestCase):
    def setUp(self):
        self.frappe = SimpleNamespace(db=Mock(), get_all=Mock(), whitelist=lambda **kwargs: lambda fn: fn)
        utils = SimpleNamespace(escape_html=str, get_url_to_form=lambda *args: "/", getdate=self.to_date)
        common = SimpleNamespace(**{key: key for key in ("CANTEEN", "DAY", "TASK", "TERM", "WEEK")},
                                 company_doc=Mock(), linked=Mock(), lock_company=Mock(),
                                 permission=Mock(), require=Mock(), submitted=Mock())
        spec = importlib.util.spec_from_file_location("term_projects_test", Path(__file__).parents[1] / "canteen_ops/term_projects.py")
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "frappe": self.frappe, "frappe.utils": utils, "tongjianyun.canteen_ops.common": common,
        }):
            spec.loader.exec_module(self.module)
        self.term = SimpleNamespace(company="School", canteen="Kitchen", from_date="2026-11-25", to_date="2026-12-04")

    @staticmethod
    def to_date(value):
        return date.fromisoformat(value) if isinstance(value, str) else value

    def test_weeks_include_partial_first_and_last_week(self):
        self.assertEqual(self.module._mondays(self.term), [date(2026, 11, 23), date(2026, 11, 30)])

    def test_completion_comes_from_the_business_stage(self):
        week = SimpleNamespace(docstatus=0, kitchen_reconciled=False, kitchen_reconciled_at=None, procurement_snapshot=None)
        self.assertFalse(any(done for done, _ in self.module._week_steps(week, set(), "MR-1")))
        week.docstatus = 1
        steps = self.module._week_steps(week, {1, 2}, "MR-1")
        self.assertEqual(steps, [(True, "已审核"), (True, "已生成申请"), (False, "已日结 2/5 天"), (False, "待核销")])
        week.kitchen_reconciled, week.kitchen_reconciled_at = True, "2026-11-30 10:00:00"
        week.procurement_snapshot = json.dumps({"basis_hash": "frozen", "rows": [{"status": "covered"}]})
        steps = self.module._week_steps(week, set(range(5)), None)
        self.assertTrue(all(done for done, _ in steps))
        self.assertEqual(steps[1], (True, "无需采购"))
        self.assertFalse(self.module._covered_by_stock('{"basis_hash":"x","rows":[{"status":"purchase","purchase_qty":"1"}]}'))
        self.assertFalse(self.module._covered_by_stock('{"rows":[]}'))

    def test_shared_material_warehouse_needs_a_matching_kitchen_or_unique_task_owner(self):
        self.frappe.db.get_value.return_value = SimpleNamespace(raw_warehouse="Raw", kitchen_warehouse="Kitchen WH")
        self.frappe.db.count.return_value = 2
        monday = date(2026, 11, 23)
        week = SimpleNamespace(name="W-1", week_start=monday, kitchen_warehouse=None)
        self.frappe.get_all.side_effect = [[week], []]
        self.assertEqual(self.module._source_weeks(self.term, [monday]), {})
        self.frappe.get_all.side_effect = [[week], [SimpleNamespace(meal_week="W-1", canteen="Kitchen")]]
        self.assertEqual(self.module._source_weeks(self.term, [monday]), {monday: week})
        week.kitchen_warehouse = "Other"
        self.frappe.get_all.side_effect = [[week]]
        self.assertEqual(self.module._source_weeks(self.term, [monday]), {})
