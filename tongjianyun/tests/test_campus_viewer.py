import importlib
import unittest
from unittest.mock import patch
from frappe import _dict

viewer = importlib.import_module("tongjianyun.www.tongjianyun_campus")


class CampusViewerTests(unittest.TestCase):
    def test_route_resolves_permission_controller(self):
        from frappe.website.page_renderers.template_page import TemplatePage
        page = TemplatePage("tongjianyun-campus")
        page.set_pymodule()
        self.assertEqual(page.pymodule_name, "tongjianyun.www.tongjianyun_campus")

    def test_guest_redirects_to_login(self):
        with patch.object(viewer.frappe, "session", _dict(user="Guest")), patch.object(viewer.frappe.local, "flags", _dict()):
            with self.assertRaises(viewer.frappe.Redirect):
                viewer.get_context(_dict())
            self.assertEqual(viewer.frappe.local.flags.redirect_location, "/login?redirect-to=/tongjianyun-campus")

    def test_business_role_required(self):
        with patch.object(viewer.frappe, "session", _dict(user="operator")), patch.object(viewer.frappe.db, "get_value", return_value=1), patch.object(viewer.frappe, "get_roles", return_value=["All"]):
            with self.assertRaises(viewer.frappe.PermissionError):
                viewer.get_context(_dict())

    def test_business_role_and_administrator_allowed(self):
        for user, roles in [("Administrator", []), ("operator", [viewer.ROLE])]:
            with self.subTest(user=user), patch.object(viewer.frappe, "session", _dict(user=user)), patch.object(viewer.frappe.db, "get_value", return_value=1), patch.object(viewer.frappe, "get_roles", return_value=roles):
                context = _dict()
                viewer.get_context(context)
                self.assertEqual(context.no_cache, 1)

    def test_disabled_account_rejected(self):
        with patch.object(viewer.frappe, "session", _dict(user="operator")), patch.object(viewer.frappe.db, "get_value", return_value=0):
            with self.assertRaises(viewer.frappe.PermissionError):
                viewer.get_context(_dict())
