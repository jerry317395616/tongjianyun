import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class KitchenIssueReviewTests(unittest.TestCase):
    def setUp(self):
        self.day = SimpleNamespace(name="DAY", meal_week="WEEK", meal_date="2026-11-30", docstatus=0,
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

    def approve(self):
        return self.kitchen.approve_kitchen_issue("DAY", "TRANSFER", self.token)

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

    def test_future_business_date_or_configured_workflow(self):
        self.kitchen.today = lambda: "2026-11-28"
        with self.assertRaisesRegex(ValueError, "2026-11-30"):
            self.approve()
        self.kitchen.today = lambda: "2026-11-30"
        self.workflow.return_value = "审批流程"
        with self.assertRaisesRegex(ValueError, "工作流"):
            self.approve()
        self.entry.submit.assert_not_called()
