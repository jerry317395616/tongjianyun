import unittest
from unittest.mock import patch
from frappe import _dict
from tongjianyun import business_access as access
from tongjianyun import recipe_storage


class BusinessAccessTests(unittest.TestCase):
    def test_non_administrator_cannot_install(self):
        with patch.object(access.frappe, "session", _dict(user="operator")):
            with self.assertRaises(access.frappe.PermissionError):
                access.install(["operator"])

    def test_privileged_roles_not_in_profile(self):
        self.assertFalse(set(access.BACKING) & {"System Manager", "Script Manager", "Academics User", "Accounts Manager", "I-ONE Agent Manager"})

    def test_settings_never_in_business_write_allowlist(self):
        self.assertFalse(access.BUSINESS & access.DENIED)
        self.assertTrue({"Company", "Buying Settings", "Accounts Settings", "Stock Settings"} <= access.REFERENCE)

    def test_restore_requires_business_role_and_recipe_write(self):
        for roles, permission, expected in [([access.ROLE], True, True), ([access.ROLE], False, False), (["Instructor"], True, False)]:
            with patch.object(recipe_storage.frappe, "session", _dict(user="operator")), \
                 patch.object(recipe_storage.frappe, "get_roles", return_value=roles), \
                 patch.object(recipe_storage.frappe, "has_permission", return_value=permission):
                self.assertEqual(recipe_storage._can_restore_recipe(), expected)

    def test_administrator_restore_unchanged(self):
        with patch.object(recipe_storage.frappe, "session", _dict(user="Administrator")):
            self.assertTrue(recipe_storage._can_restore_recipe())
