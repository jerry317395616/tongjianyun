import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


class Denied(Exception):
    pass


class ArchiveBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.frappe = ModuleType("frappe")
        self.frappe.session = SimpleNamespace(user="ordinary")
        self.frappe.PermissionError = Denied
        self.frappe.throw = lambda message, error: (_ for _ in ()).throw(error(message))
        self.frappe.get_roles = lambda user: ["System Manager"] if user == "manager" else ["Desk User"]
        document = ModuleType("frappe.model.document")
        document.Document = type("Document", (), {})
        self.modules = patch.dict(sys.modules, {"frappe": self.frappe, "frappe.model": ModuleType("frappe.model"), "frappe.model.document": document})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        spec = importlib.util.spec_from_file_location("report_archive_test", Path(__file__).parents[1] / "archive.py")
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_administrator_and_manager_may_read_history_but_not_authorize_writes(self):
        for user in ("Administrator", "manager"):
            self.assertEqual(self.module.query_condition(user), "")
            self.assertTrue(self.module.document_permission(None, "read", user))
            for action in ("write", "create", "delete", "submit", "cancel"):
                self.assertFalse(self.module.document_permission(None, action, user))

    def test_ordinary_users_cannot_enumerate_or_read_archive(self):
        self.assertEqual(self.module.query_condition("ordinary"), "1=0")
        self.assertFalse(self.module.document_permission(None, "read", "ordinary"))

    def test_all_lifecycle_writes_are_denied_even_for_administrator(self):
        self.frappe.session.user = "Administrator"
        doc = self.module.ReadOnlyArchive()
        for action in ("save", "insert", "delete", "submit", "cancel", "db_update", "db_insert", "before_insert", "before_validate", "validate", "before_submit", "before_cancel", "before_update_after_submit", "on_trash"):
            with self.subTest(action=action), self.assertRaises(Denied):
                getattr(doc, action)()

    def test_ignore_flags_cannot_reactivate_an_archived_document(self):
        doc = self.module.ReadOnlyArchive()
        doc.flags = SimpleNamespace(ignore_validate=True, ignore_permissions=True)
        with self.assertRaises(Denied):
            doc.save(ignore_permissions=True)

    def test_curated_sidebar_exposes_only_the_two_reports(self):
        root = Path(__file__).parents[1]
        doc = json.loads((root / "tongjianyun/sidebar/tongjianyun.json").read_text(encoding="utf-8"))
        self.assertEqual([row["link_to"] for row in doc["items"]], ["Tongjianyun Weekly Menu", "Weekly Recipe Nutrition Analysis"])
        self.assertTrue(all(row["link_type"] == "Report" for row in doc["items"]))

    def test_legacy_schema_and_operational_endpoints_are_absent(self):
        root = Path(__file__).parents[1]
        self.assertFalse(list((root / "tongjianyun/doctype").rglob("*.json")))
        for file in ("recipe_storage.py", "recipe_import.py", "meal_scene.py", "meal_chat.py", "daily_meals.py", "mcp_tools.py", "education_integration.py"):
            self.assertFalse((root / file).exists(), file)
        self.assertFalse(list((root / "tongjianyun/page").rglob("*.json")))
