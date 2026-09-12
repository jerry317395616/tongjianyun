import unittest
from unittest.mock import patch
import frappe
from tongjianyun.health_registration import validate_declaration, record_name, access

class HealthRegistrationTests(unittest.TestCase):
    def valid(self):
        return frappe._dict(history_state='明确无', allergy_state='明确无', review_status='已核对', information_source='test')

    def test_unknown_not_confirmed(self):
        doc = self.valid(); doc.allergy_state = '未登记'
        with self.assertRaises(frappe.ValidationError): validate_declaration(doc)

    def test_registered_requires_text(self):
        doc = self.valid(); doc.history_state = '已登记'
        with self.assertRaises(frappe.ValidationError): validate_declaration(doc)

    def test_none_cannot_include_text(self):
        doc = self.valid(); doc.allergy_history = 'test'
        with self.assertRaises(frappe.ValidationError): validate_declaration(doc)

    def test_confirm_requires_source(self):
        doc = self.valid(); doc.information_source = ''
        with self.assertRaises(frappe.ValidationError): validate_declaration(doc)

    def test_pending_can_be_empty(self):
        validate_declaration(frappe._dict(history_state='未登记', allergy_state='未登记', review_status='待核对'))

    def test_month_identity(self):
        self.assertEqual(record_name('S1','2026-09-01'), record_name('S1','2026-09-30'))
        self.assertNotEqual(record_name('S1','2026-09-01'), record_name('S1','2026-10-01'))

    def test_business_role_does_not_grant_health_access(self):
        with patch.object(frappe, 'session', frappe._dict(user='test')), patch.object(frappe.db, 'get_value', return_value=1), patch.object(frappe, 'get_roles', return_value=['Tongjianyun Business Operator']):
            with self.assertRaises(frappe.PermissionError): access()
