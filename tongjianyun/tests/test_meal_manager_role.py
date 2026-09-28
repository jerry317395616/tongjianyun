"""Meal-manager launcher and entry behavior without creating test accounts."""

import unittest
from unittest.mock import MagicMock, patch

import frappe

from tongjianyun import meal_manager_role, workspace_entry


class MealManagerRoleTests(unittest.TestCase):
    def test_only_assigned_non_system_accounts_are_constrained(self):
        self.assertTrue(meal_manager_role.is_meal_manager("meal@example.test", [meal_manager_role.ROLE]))
        self.assertFalse(meal_manager_role.is_meal_manager("meal@example.test", []))
        self.assertFalse(meal_manager_role.is_meal_manager("Administrator", [meal_manager_role.ROLE]))
        self.assertFalse(meal_manager_role.is_meal_manager("Guest", [meal_manager_role.ROLE]))

    def test_boot_payload_contains_only_tongjianyun_for_role_holder(self):
        apps = [{"app_name": "frappe"}, {"app_name": "education"},
                {"app_name": "tongjianyun"}, {"app_name": "erpnext"}]
        icons = [{"icon_type": "App", "app": "frappe"},
                 {"icon_type": "App", "app": "tongjianyun"},
                 {"icon_type": "Folder", "app": "tongjianyun"}]
        boot = frappe._dict(app_data=list(apps), desktop_icons=list(icons))
        with patch.object(meal_manager_role, "is_meal_manager", return_value=True):
            meal_manager_role.limit_app_launcher(boot)
        self.assertEqual(boot.app_data, [{"app_name": "tongjianyun"}])
        self.assertEqual(boot.desktop_icons, [{"icon_type": "App", "app": "tongjianyun"}])
        self.assertTrue(boot.tongjianyun_meal_manager)
        boot = frappe._dict(app_data=list(apps), desktop_icons=list(icons))
        with patch.object(meal_manager_role, "is_meal_manager", return_value=False):
            meal_manager_role.limit_app_launcher(boot)
        self.assertEqual(boot.app_data, apps)
        self.assertEqual(boot.desktop_icons, icons)

    def test_install_does_not_assign_roles_to_users(self):
        db = MagicMock()
        db.exists.side_effect = lambda dt, name: dt == "DocType"
        with patch.object(meal_manager_role.frappe, "db", db), \
             patch.object(meal_manager_role.frappe, "get_doc", return_value=MagicMock()) as get_doc, \
             patch.object(meal_manager_role.frappe, "clear_cache"), \
             patch("tongjianyun.education_integration._ensure_permission") as ensure:
            meal_manager_role.install()
        self.assertEqual(get_doc.call_args.args[0]["doctype"], "Role")
        self.assertEqual(get_doc.call_args.args[0]["role_name"], meal_manager_role.ROLE)
        self.assertEqual(ensure.call_count, len(meal_manager_role.RECIPE_DOCTYPES))
        self.assertEqual([call.args[0] for call in ensure.call_args_list], list(meal_manager_role.RECIPE_DOCTYPES))

    def test_role_holder_opens_meal_calendar_even_with_other_profiles(self):
        model = {"meal_manager": True, "profiles": [
            {"id": "teacher", "enabled": True},
            {"id": "business", "enabled": True},
            {"id": "meals", "enabled": True},
        ], "groups": []}
        result = workspace_entry.resolve_entry(model)
        self.assertEqual(result["destination"], workspace_entry.SCENE)
        self.assertEqual(result["profile"], "meals")
        self.assertEqual(workspace_entry.resolve_entry(model, choose=True)["view"], "profiles")

    def test_unassigned_role_keeps_existing_profile_picker(self):
        model = {"meal_manager": False, "profiles": [
            {"id": "business", "enabled": True}, {"id": "meals", "enabled": True},
        ], "groups": []}
        self.assertEqual(workspace_entry.resolve_entry(model)["view"], "profiles")


if __name__ == "__main__":
    unittest.main()
