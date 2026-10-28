import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


class Denied(Exception):
    pass


class EphemeralPermissionTests(unittest.TestCase):
    def setUp(self):
        fake = ModuleType("frappe")
        fake.session = SimpleNamespace(user="meal-user")
        fake.AuthenticationError = Denied
        fake.whitelist = lambda **kw: lambda fn: fn
        fake.throw = lambda message, error=Denied: (_ for _ in ()).throw(error(message))
        report = ModuleType("frappe.desk.query_report")
        report.get_report_doc = Mock()
        sources = ModuleType("tongjianyun.report_sources")
        sources.load_source = Mock()
        modules = {"frappe": fake, "frappe.desk": ModuleType("frappe.desk"),
                   "frappe.desk.query_report": report, "tongjianyun.report_sources": sources}
        context = patch.dict(sys.modules, modules)
        context.start()
        self.addCleanup(context.stop)
        spec = importlib.util.spec_from_file_location("ephemeral_api_test", Path(__file__).parents[1] / "weekly_nutrition_api.py")
        self.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.api)
        self.fake, self.report, self.sources = fake, report, sources

    def test_guest_or_revoked_report_permission_cannot_reach_worker(self):
        for guest in (True, False):
            self.fake.session.user = "Guest" if guest else "meal-user"
            self.report.get_report_doc.side_effect = None if guest else Denied("revoked")
            with patch.object(self.api, "_rpc") as rpc, self.assertRaises(Denied):
                self.api._access("a" * 64)
            rpc.assert_not_called()

    def test_source_change_blocks_result_before_any_values_are_read(self):
        with patch.object(self.api, "_rpc", return_value={"source": {"week_start": "2026-06-22"}, "fingerprint": "old"}) as rpc:
            with patch.object(self.api, "_source", return_value={"source": "changed"}), self.assertRaises(Denied):
                self.api._access("a" * 64)
        rpc.assert_called_once_with("/meta", report_id="a" * 64)

    def test_chat_contract_contains_only_metadata_and_links(self):
        source = {"source": {"week_start": "2026-06-22", "week_name": None, "plan_batch": "synthetic"}, "dates": ["2026-06-22"], "lines": [{}], "foods": [{"code": "X"}]}
        with patch.object(self.api, "_source", return_value=source), patch.object(self.api, "_rpc", return_value={"report_id": "a" * 64, "expires_at": 123456}):
            result = self.api.report_data("2026-06-22")
        self.assertEqual(set(result), {"source", "dates", "line_count", "food_count", "report_id", "expires_at", "status", "preview_url", "download_url"})
        self.assertEqual(result["status"], "pending")
        self.assertNotIn("nutrients", result)
