import unittest
from unittest.mock import patch
from frappe import _dict
from tongjianyun import single_business_role as migration
from tongjianyun import business_access, attendance_scope, nutrition_rule_service


class SingleBusinessRoleTests(unittest.TestCase):
    def test_one_tongjianyun_role_in_profile(self):
        roles=[business_access.ROLE,*business_access.BACKING]
        self.assertEqual([r for r in roles if r.startswith('Tongjianyun ')],[business_access.ROLE])

    def test_legacy_roles_are_not_runtime_managers(self):
        self.assertFalse(set(migration.LEGACY) & attendance_scope.MANAGERS)
        self.assertIn(business_access.ROLE,attendance_scope.MANAGERS)
        self.assertIn(business_access.ROLE,nutrition_rule_service.PUBLISHER_ROLES)

    def test_preview_is_administrator_only(self):
        with patch.object(migration.frappe,'session',_dict(user='ordinary')):
            with self.assertRaises(migration.frappe.PermissionError):migration.preview()

    def test_official_and_ione_roles_not_deleted(self):
        self.assertEqual(len(migration.LEGACY),11)
        self.assertTrue(all(r.startswith('Tongjianyun ') for r in migration.LEGACY))
        self.assertNotIn(business_access.ROLE,migration.LEGACY)
