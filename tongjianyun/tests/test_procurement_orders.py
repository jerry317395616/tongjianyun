import unittest
from frappe import _dict
from unittest.mock import MagicMock, patch
from contextlib import ExitStack
from tongjianyun import recipe_procurement as service


class OrderTests(unittest.TestCase):
    def run_case(self, status=0, linked=False, fallback='SUP', disabled=False):
        request = MagicMock(docstatus=status, material_request_type='Purchase', company='School')
        mapper = MagicMock()
        mapper.get_item_default_suppliers.return_value = [{'supplier': None, 'pending_qty': 3, 'material_request_item': 'ROW1'}]
        mapped = MagicMock()
        mapped.name = 'PO1'
        mapped.items = [_dict(schedule_date=None), _dict(schedule_date='2026-09-11')]
        mapper.make_purchase_order.return_value = mapped
        order = MagicMock(docstatus=0)
        order.name = 'PO1'
        with ExitStack() as stack:
            stack.enter_context(patch.dict('sys.modules', {'erpnext.stock.doctype.material_request.mapper': mapper}))
            stack.enter_context(patch.object(service, '_permission'))
            stack.enter_context(patch.object(service, '_read', side_effect=lambda dt, n: request if dt == 'Material Request' else order if dt == 'Purchase Order' else MagicMock(disabled=disabled)))
            stack.enter_context(patch.object(service.frappe, 'db', MagicMock()))
            stack.enter_context(patch.object(service.frappe, 'get_all', return_value=[_dict(parent='PO1')] if linked else []))
            stack.enter_context(patch.object(service.frappe.defaults, 'get_global_default', return_value=fallback))
            stack.enter_context(patch.object(service.frappe, 'throw', side_effect=ValueError))
            result = service.complete_purchase_request('MR1')
        return result, request, mapper

    def test_submit_and_map(self):
        result, request, mapper = self.run_case()
        request.submit.assert_called_once()
        self.assertEqual(result['purchase_orders'], ['PO1'])
        self.assertEqual(mapper.make_purchase_order.call_args.kwargs['args']['supplier'], 'SUP')
        import datetime
        self.assertTrue(all(isinstance(r.schedule_date, datetime.date) for r in mapper.make_purchase_order.return_value.items))

    def test_submitted_not_resubmitted(self):
        _, request, _ = self.run_case(status=1)
        request.submit.assert_not_called()

    def test_existing_draft_not_duplicated(self):
        result, request, mapper = self.run_case(linked=True, status=1)
        self.assertTrue(result['existing'])
        mapper.make_purchase_order.assert_not_called()
        request.submit.assert_not_called()

    def test_invalid_supplier_or_request(self):
        for kwargs in ({'fallback': None}, {'disabled': True}, {'status': 2}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_case(**kwargs)
