from hashlib import sha256
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


def fail(message):
    raise ValueError(message)


class SplitTests(unittest.TestCase):
    def setUp(self):
        frappe = ModuleType("frappe")
        frappe.whitelist = lambda **_: lambda fn: fn
        frappe.throw = fail
        frappe.db = SimpleNamespace(get_value=lambda *_: True)
        utils = ModuleType("frappe.utils")
        utils.getdate = str
        utils.now_datetime = lambda: None
        core = ModuleType("ione_core")
        core.meal_planning = SimpleNamespace(_digest=lambda value: sha256(str(value).encode()).hexdigest())
        core.meal_procurement = SimpleNamespace(_quantity_precision=lambda: 3)
        core.meal_purchasing = SimpleNamespace()
        extension = ModuleType("tongjianyun")
        extension.special_ingredients = SimpleNamespace()
        modules = {"frappe": frappe, "frappe.utils": utils, "ione_core": core, "tongjianyun": extension}
        spec = importlib.util.spec_from_file_location("split_test_module", Path(__file__).parents[1] / "special_orders.py")
        self.orders = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, modules):
            spec.loader.exec_module(self.orders)

    def row(self, stock=30, required=120, special=80, order=90, factor=1):
        raw = {
            "production_plan": "MEAL", "meal_date": "2026-11-23", "meal_type": "午餐",
            "item_code": "EGG", "item_name": "鸡蛋", "warehouse": "仓库", "stock_uom": "个", "purchase_uom": "件",
            "required_qty": required, "allocated_stock_qty": stock, "conversion_factor": factor,
        }
        return self.orders._entry(raw, {"special_qty": special, "plan": "PLAN"}, self.orders._decimal(order))

    def test_shared_stock_proposal_and_reviewed_dedicated_stock_conserve_total(self):
        row = self.row()
        self.assertTrue(row["review_required"])
        self.assertEqual((row["suggested_special"], row["suggested_ordinary"]), ("60", "30"))
        with self.assertRaisesRegex(ValueError, "核对依据"):
            self.orders._decide([row], {})
        choices = {row["key"]: {"special_covered": "30", "reason": "专项已覆盖30个"}}
        saved = self.orders._decide([row], choices)[row["key"]]
        self.assertEqual((saved["special_purchase"], saved["ordinary_purchase"]), ("50", "40"))
        with self.assertRaisesRegex(ValueError, "专用覆盖量"):
            self.orders._decide([row], {row["key"]: {"special_covered": "31", "reason": "核对"}})

    def test_whole_purchase_units_are_rounded_once_and_require_review(self):
        row = self.row(stock=0, required=120, special=80, order=10, factor=12)
        self.assertTrue(row["review_required"])
        self.assertEqual((row["suggested_special"], row["suggested_ordinary"]), ("7", "3"))
        for invalid in ("", "6.5", "11"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.orders._decide([row], {row["key"]: {"special_purchase": invalid, "reason": "核对"}})

    def test_an_ordinary_line_cannot_be_booked_as_special(self):
        row = self.row(special=0)
        with self.assertRaisesRegex(ValueError, "归属一致"):
            self.orders._decide([row], {row["key"]: {"special_purchase": "1", "reason": "核对"}})
