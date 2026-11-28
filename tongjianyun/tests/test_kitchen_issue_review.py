import importlib.util
import unittest
from datetime import date
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
        modules["tongjianyun.canteen_ops.inventory"] = SimpleNamespace(consumption_lot_warnings=Mock(return_value={}))
        patcher = patch.dict("sys.modules", modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        spec = importlib.util.spec_from_file_location("kitchen_under_test", Path(__file__).parents[1] / "meal_kitchen.py")
        self.kitchen = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.kitchen)
        self.kitchen._day = Mock(return_value=self.day)
        self.token = self.kitchen._stock_review_token(self.day, self.entry)

    @staticmethod
    def reject(message, exc):
        raise exc(message)

    def approve(self, issue_date=None):
        return self.kitchen.approve_kitchen_issue("DAY", "TRANSFER", self.token, issue_date)

    def test_day_close_delegates_only_effective_meal_plans_and_restores_permissions(self):
        day = self.day
        day._action, day.docstatus, day.owner, day.approved_by = "submit", 1, "clerk", "reviewer"
        day.check_permission, day.db_set = Mock(), Mock()
        plan = SimpleNamespace(name="ACTIVE", custom_meal_type="早餐", status="Submitted",
                               flags=SimpleNamespace(ignore_permissions=None))
        meal = SimpleNamespace(production_plan=plan.name, meal_type="早餐", meal_date=day.meal_date)
        adjustments = SimpleNamespace(get_effective_meals=Mock(return_value=[meal]))
        self.kitchen._day_execution = Mock(return_value={})
        self.kitchen._week = Mock()
        self.kitchen._day_plans = Mock(return_value=[plan])
        self.frappe.as_json = str

        def native_close(p):
            self.assertTrue(p.flags.ignore_permissions)
            return p.name

        with patch.dict("sys.modules", {"tongjianyun.meal_adjustments": adjustments}):
            self.kitchen._native_close = Mock(side_effect=native_close)
            self.kitchen.on_submit_day(day)
            self.assertIsNone(plan.flags.ignore_permissions)
            day.db_set.assert_called_once()
            day.db_set.reset_mock()
            self.kitchen._native_close.side_effect = ValueError("有生产工单")
            with self.assertRaisesRegex(ValueError, "生产工单"):
                self.kitchen.on_submit_day(day)
            self.assertIsNone(plan.flags.ignore_permissions)
            plan.name = "UNRELATED"
            self.kitchen._native_close.reset_mock()
            with self.assertRaisesRegex(ValueError, "未被当天有效食谱引用"):
                self.kitchen.on_submit_day(day)
            self.kitchen._native_close.assert_not_called()
            day.db_set.assert_not_called()

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

    def test_consumption_review_checks_date_balance_version_and_independent_authority(self):
        self.entry.custom_meal_action = "耗用"
        self.entry.items = [SimpleNamespace(item_code="RICE", qty=q, custom_meal_issue_detail="LOT") for q in (80, 120)]
        totals = {"RICE": {"balance_qty": Decimal("240")}}
        facts = {"totals": totals, "issues": {"LOT": {"origin_date": "2026-11-28"}}}
        self.kitchen._ledger = Mock(return_value=facts)
        actual = date(2026, 11, 28)

        def preview():
            return self.kitchen._consumption_preview(self.day, self.entry, facts, actual)

        token = preview()["review_token"]
        self.assertEqual(preview()["consumption_lines"]["RICE"], {"before": "240", "qty": "200", "after": "40"})

        def approve(selected=None):
            return self.kitchen.approve_kitchen_consumption(self.day.name, self.entry.name, token, selected or str(actual))

        self.frappe.session.user = self.entry.owner
        with self.assertRaises(PermissionError):
            approve()
        self.frappe.session.user = "reviewer"
        with patch.object(self.kitchen, "today", return_value="2026-11-28"), self.assertRaisesRegex(ValueError, "最晚可选"):
            approve("2026-11-29")
        with self.assertRaisesRegex(ValueError, "不能更早"):
            approve("2026-11-27")
        with self.assertRaisesRegex(ValueError, "重新核对"):
            approve("2026-11-29")
        with patch.object(self.entry, "custom_meal_action", "领用"), self.assertRaisesRegex(ValueError, "本日"):
            approve()
        totals["RICE"]["balance_qty"] = Decimal("220")
        with self.assertRaisesRegex(ValueError, "重新核对"):
            approve()
        totals["RICE"]["balance_qty"] = Decimal("140")
        token = preview()["review_token"]
        with self.assertRaisesRegex(ValueError, "超过厨房结存"):
            approve()
        self.entry.submit.assert_not_called()
        totals["RICE"]["balance_qty"] = Decimal("240")
        token = preview()["review_token"]
        self.assertFalse(approve()["already_submitted"])
        self.assertEqual(self.entry.posting_date, actual)
        self.assertEqual(self.day.meal_date, "2026-11-30")
        self.entry.docstatus = 1
        self.assertTrue(approve()["already_submitted"])
        self.entry.submit.assert_called_once_with()
        self.entry.add_comment.assert_called_once()

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
        self.kitchen._check_execution_order(self.day, advance_prep=True)
        with self.assertRaisesRegex(ValueError, "前一"):
            self.kitchen._check_execution_order(self.day)
        future.started_service = 1
        with self.assertRaisesRegex(ValueError, "后日"):
            self.kitchen._check_execution_order(self.day, advance_prep=True)

    def test_advance_consumption_respects_day_ownership_of_issued_and_carried_stock(self):
        issue = Mock(docstatus=1, custom_meal_action="领用")
        issue.get.return_value = [SimpleNamespace(name="assigned")]
        row = SimpleNamespace(custom_meal_issue_detail="assigned")
        self.entry.configure_mock(custom_meal_action="耗用", posting_date="2026-11-28", items=[row])
        facts = {"opening_day": {"day_name": "previous"}, "opening_sources": [{"issue_detail": "carry"}]}
        self.assertTrue(self.kitchen._is_advance_prep(self.day, self.entry, [issue]))
        self.assertIsNone(self.kitchen._carry_available_from(self.entry, facts))
        row.custom_meal_issue_detail = "carry"
        self.frappe.db = Mock()
        self.frappe.db.get_value.return_value = "2026-11-29"
        self.assertFalse(self.kitchen._is_advance_prep(self.day, self.entry, [issue]))
        self.assertEqual(self.kitchen._carry_available_from(self.entry, facts), date(2026, 11, 29))
