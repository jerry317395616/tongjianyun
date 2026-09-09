import unittest
from unittest.mock import patch
from frappe import _dict
from tongjianyun import recipe_procurement as service


class TestProcurementDefaults(unittest.TestCase):
    def resolve(self, user='School', global_company='Global', warehouse='Stores', **values):
        wh = _dict(company=user or global_company, is_group=0, disabled=0)
        wh.update(values)
        def read(doctype, name):
            if doctype == 'Company':
                return _dict(default_warehouse=warehouse)
            if doctype == 'Warehouse':
                return wh
            return _dict(name=name)
        with patch.object(service, '_permission') as permission, \
             patch.object(service, '_read', side_effect=read) as reader, \
             patch.object(service.frappe.defaults, 'get_user_default', return_value=user), \
             patch.object(service.frappe.defaults, 'get_global_default', return_value=global_company), \
             patch.object(service.frappe, 'throw', side_effect=ValueError):
            result = service.default_scope('Recipe')
            permission.assert_called_once_with('Material Request', 'create')
            self.assertEqual([c.args[0] for c in reader.call_args_list], [service.RECIPE, 'Company', 'Warehouse'])
            return result

    def test_user_default(self):
        self.assertEqual(self.resolve(), {'company': 'School', 'warehouse': 'Stores'})

    def test_global_fallback(self):
        self.assertEqual(self.resolve(user=None)['company'], 'Global')

    def test_missing_company(self):
        with self.assertRaises(ValueError):
            self.resolve(user=None, global_company=None)

    def test_missing_warehouse(self):
        with self.assertRaises(ValueError):
            self.resolve(warehouse=None)

    def test_invalid_warehouse(self):
        for values in [{'company': 'Other'}, {'disabled': 1}, {'is_group': 1}]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                self.resolve(**values)

    def test_permission_error_not_bypassed(self):
        with patch.object(service, '_permission'), patch.object(service, '_read', side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                service.default_scope('Recipe')
