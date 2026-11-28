import importlib.util
import unittest
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class KitchenIssueReviewTests(unittest.TestCase):
    def setUp(self):
        self.day = SimpleNamespace(name="DAY", company="School", meal_week="WEEK", meal_date="2026-11-30", docstatus=0,
                                   items=[], source_warehouse="原料仓", kitchen_warehouse="厨房仓")
        self.entry = Mock(name="Stock Entry")
        self.entry.configure_mock(name="TRANSFER", owner="clerk", modified="version-1", docstatus=0,
                                  custom_meal_kitchen_day="DAY", custom_meal_week="WEEK",
                                  custom_meal_action="领用", posting_date=self.day.meal_date)
        self.frappe = SimpleNamespace(
            session=SimpleNamespace(user="reviewer"), get_roles=lambda: ["Stock Manager"],
            get_doc=Mock(return_value=self.entry), whitelist=lambda **kw: lambda fn: fn,
            _=str, PermissionError=PermissionError, ValidationError=ValueError,
            throw=self.reject,
        )
        self.workflow = Mock(return_value=None)
        modules = {"frappe": self.frappe, "frappe.utils": SimpleNamespace(now_datetime=Mock(), today=lambda: "2026-11-30"),
                   "frappe.model.workflow": SimpleNamespace(get_workflow_name=self.workflow)}
        patcher = patch.dict("sys.modules", modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location("kitchen_under_test", Path(__file__).parents[1] / "meal_kitchen.py")
        self.kitchen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.kitchen)
        self.kitchen._day = Mock(return_value=self.day)
        self.token = self.kitchen._issue_review_token(self.day, self.entry)

    @staticmethod
    def reject(message, exc):
        raise exc(message)

    def approve(self, issue_date=None):
        return self.kitchen.approve_kitchen_issue("DAY", "TRANSFER", self.token, issue_date)

    def test_consumption_defaults_to_unconsumed_plan_within_balance(self):
        self.day.meals = []
        self.day.items = [{"item_code": "EGG", "stock_uom": "kg", "planned_qty": "0.624"}]
        self.frappe.db = Mock()
        self.kitchen._carry_confirmation = Mock(return_value=(False, "", False, {}))
        for consumed, balance, expected in [
            ("0", "1", "0.624"), ("0.1", "0.7", "0.524"), ("0.1", "0.28", "0.28"),
            ("0.7", "1", "0"), ("0", "0", "0"),
        ]:
            with self.subTest(consumed=consumed, balance=balance):
                values = {"opening_qty": Decimal("0"), "issued_qty": Decimal(consumed) + Decimal(balance),
                          "consumed_qty": Decimal(consumed), "balance_qty": Decimal(balance)}
                self.kitchen._ledger = Mock(return_value={
                    "allowed_items": {"EGG": ("kg", Decimal("0.624"))}, "totals": {"EGG": values},
                    "entries": [], "drafts": [],
                })
                row, = self.kitchen.get_kitchen_ledger("DAY")["rows"]
                self.assertEqual(row["suggested_consumption_qty"], expected)

    def test_uses_native_submission_and_handles_retry(self):
        self.assertFalse(self.approve()["already_submitted"])
        self.entry.submit.assert_called_once_with()
        self.kitchen._day.assert_called_with("DAY", lock=True)
        self.frappe.get_doc.assert_called_with("Stock Entry", "TRANSFER", for_update=True)
        self.entry.docstatus = 1
        self.assertTrue(self.approve()["already_submitted"])
        self.entry.submit.assert_called_once()

    def test_owner_and_reviewer_without_submit_permission_are_rejected(self):
        self.frappe.session.user = self.entry.owner
        with self.assertRaises(PermissionError):
            self.approve()
        self.frappe.session.user = "reviewer"
        self.entry.has_permission.return_value = False
        with self.assertRaises(PermissionError):
            self.approve()
        self.entry.submit.assert_not_called()

    def test_scope_stale_review_and_cancelled_draft(self):
        for key, other in [("custom_meal_action", "耗用"), ("custom_meal_kitchen_day", "OTHER"),
                           ("custom_meal_week", "OTHER"), ("modified", "version-2"), ("docstatus", 2)]:
            with self.subTest(key=key), patch.object(self.entry, key, other), self.assertRaises(ValueError):
                self.approve()
        self.day.kitchen_warehouse = "另一仓库"
        with self.assertRaises(ValueError):
            self.approve()
        self.entry.submit.assert_not_called()

    def test_actual_handover_can_precede_service_and_cannot_be_in_the_future(self):
        self.kitchen.today = lambda: "2026-11-28"
        with self.assertRaisesRegex(ValueError, "实际领用日期"):
            self.approve()
        self.approve("2026-11-28")
        self.assertEqual(str(self.entry.posting_date), "2026-11-28")
        self.assertEqual(self.day.meal_date, "2026-11-30")
        self.entry.submit.assert_called_once()
        self.kitchen.today = lambda: "2026-12-02"
        with self.assertRaisesRegex(ValueError, "供餐日期"):
            self.approve("2026-12-01")

    def test_configured_workflow_still_applies(self):
        self.kitchen.today = lambda: "2026-11-30"
        self.workflow.return_value = "审批流程"
        with self.assertRaisesRegex(ValueError, "工作流"):
            self.approve()
        self.entry.submit.assert_not_called()

    def test_advance_transfers_do_not_block_earlier_service_or_borrow_its_carry(self):
        self.frappe.db = Mock()
        future = SimpleNamespace(meal_date="2026-12-01", docstatus=0, started_service=0)
        earlier = SimpleNamespace(meal_date="2026-11-29", docstatus=0, started_service=1)
        self.frappe.db.sql.return_value = [future]
        self.kitchen._check_execution_order(self.day)
        self.frappe.db.sql.return_value = [earlier, future]
        self.kitchen._check_execution_order(self.day, advance_issue=True)
        with self.assertRaisesRegex(ValueError, "前一"):
            self.kitchen._check_execution_order(self.day)
        future.started_service = 1
        with self.assertRaisesRegex(ValueError, "后日"):
            self.kitchen._check_execution_order(self.day, advance_issue=True)
