import unittest
from frappe import _dict
from unittest.mock import MagicMock, patch
from contextlib import ExitStack
from tongjianyun import recipe_procurement as service


class OrderTests(unittest.TestCase):
    def setUp(self):
        # Exercise Frappe's real rounding without requiring an initialized site.
        settings = patch.object(service.frappe, "get_system_settings", return_value="Banker's Rounding")
        settings.start()
        self.addCleanup(settings.stop)

    @staticmethod
    def reject(message, *args, **kwargs):
        raise ValueError(message)

    def run_case(self, status=0, linked=False, fallback='SUP', disabled=False):
        request = MagicMock(docstatus=status, material_request_type='Purchase', company='School',
                            buying_price_list='Standard Buying')
        request.items = [_dict(name='ROW1', schedule_date='2026-09-07')]
        mapper = MagicMock()
        mapper.get_item_default_suppliers.return_value = [{'supplier': None, 'pending_qty': 3, 'material_request_item': 'ROW1'}]
        mapped = MagicMock()
        mapped.name = 'PO1'
        mapped.items = [_dict(schedule_date=None), _dict(schedule_date='2026-09-11')]
        mapper.make_purchase_order.return_value = mapped
        order = MagicMock(docstatus=0)
        order.name = 'PO1'
        with ExitStack() as stack:
            stack.enter_context(patch.object(service, 'nowdate', return_value='2026-09-09'))
            stack.enter_context(patch.dict('sys.modules', {'erpnext.stock.doctype.material_request.mapper': mapper}))
            stack.enter_context(patch.object(service, '_permission'))
            stack.enter_context(patch.object(service, '_default_buying_price_list', return_value='Standard Buying'))
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
        self.assertEqual(mapper.make_purchase_order.return_value.buying_price_list, 'Standard Buying')
        import datetime
        self.assertTrue(all(isinstance(r.schedule_date, datetime.date) for r in mapper.make_purchase_order.return_value.items))
        self.assertTrue(mapper.make_purchase_order.return_value.title.startswith('2026-09-07'))
        self.assertIn('食谱日期：2026-09-07', mapper.make_purchase_order.return_value.items[0].description)

    def test_default_buying_price_list_must_be_enabled_for_buying(self):
        db = MagicMock()
        db.get_single_value.return_value = 'Standard Buying'
        db.get_value.return_value = _dict(enabled=1, buying=1)
        with patch.object(service.frappe.defaults, 'get_user_default', return_value=None), \
             patch.object(service.frappe.defaults, 'get_global_default', return_value=None), \
             patch.object(service.frappe, 'db', db):
            self.assertEqual(service._default_buying_price_list(), 'Standard Buying')

        db = MagicMock()
        db.get_single_value.return_value = 'Wrong'
        db.get_value.return_value = _dict(enabled=1, buying=0)
        with patch.object(service.frappe.defaults, 'get_user_default', return_value=None), \
             patch.object(service.frappe.defaults, 'get_global_default', return_value=None), \
             patch.object(service.frappe, 'db', db), \
             patch.object(service.frappe, 'throw', side_effect=ValueError), \
             self.assertRaises(ValueError):
            service._default_buying_price_list()

    def test_upsert_buying_prices_creates_generic_item_price(self):
        plan = {"company": "School", "buying_price_list": "Standard Buying",
                "lines": [_dict(item_code="ITEM-1", item_name="苹果", uom="g", qty=10)]}
        price_key = service._price_key("ITEM-1", "g")
        created = []

        def make_doc(payload, name=None):
            doc = MagicMock()
            for key, value in payload.items():
                setattr(doc, key, value)
            doc.insert.side_effect = lambda: created.append(doc)
            return doc

        db = MagicMock()
        db.get_value.return_value = "CNY"
        with patch.object(service, "_permission"), \
             patch.object(service.frappe, "get_all", return_value=[]), \
             patch.object(service.frappe, "get_doc", side_effect=make_doc), \
             patch.object(service.frappe, "db", db):
            result = service._upsert_buying_prices(plan, {price_key: "0.02"})

        self.assertEqual(result["created"], 1)
        self.assertEqual(created[0].doctype, "Item Price")
        self.assertEqual(created[0].item_code, "ITEM-1")
        self.assertEqual(created[0].price_list_rate, 0.02)
        self.assertEqual(created[0].uom, "g")
        created[0].insert.assert_called_once()

    def test_upsert_buying_prices_updates_existing_generic_item_price(self):
        plan = {"company": "School", "buying_price_list": "Standard Buying",
                "lines": [_dict(item_code="ITEM-1", item_name="苹果", uom="g", qty=10)]}
        price_doc = MagicMock(price_list_rate=0.01, currency="CNY")
        price_doc.get.return_value = None
        db = MagicMock()
        db.get_value.return_value = "CNY"
        with patch.object(service, "_permission"), \
             patch.object(service.frappe, "get_all", return_value=[_dict(name="PRICE-1")]), \
             patch.object(service.frappe, "get_doc", return_value=price_doc), \
             patch.object(service.frappe, "db", db):
            result = service._upsert_buying_prices(plan, {service._price_key("ITEM-1", "g"): 0.03})

        self.assertEqual(result["updated"], 1)
        self.assertEqual(price_doc.price_list_rate, 0.03)
        price_doc.check_permission.assert_called_once_with("write")
        price_doc.save.assert_called_once()

    def test_date_and_supplier_partition(self):
        request = MagicMock()
        request.items = [_dict(name=str(i), schedule_date=date) for i, date in enumerate(
            ['2026-09-07', '2026-09-08', '2026-09-07', '2026-09-07'])]
        rows = [dict(material_request_item=str(i), supplier=supplier, qty=2) for i, supplier in enumerate(['A', 'A', 'B', 'A'])]
        grouped = service._daily_order_groups(request, rows)
        self.assertEqual(len(grouped), 3)
        self.assertEqual(grouped[('2026-09-07', 'A')], {'0': 2, '3': 2})
        self.assertEqual(grouped[('2026-09-08', 'A')], {'1': 2})

    def test_tiny_submitted_rate_rejected_before_any_price_or_order_write(self):
        plan = {"token": "current", "company": "School", "buying_price_list": "Standard Buying",
                "lines": [_dict(item_code="CELERY", item_name="西芹", uom="g", qty=1650)]}
        with patch.object(service, "_plan", return_value=plan), \
             patch.object(service, "_purchase_rate_precision", return_value=2), \
             patch.object(service, "_upsert_buying_prices") as save_prices, \
             patch.object(service, "create_request") as create_request, \
             patch.object(service.frappe, "throw", side_effect=self.reject), \
             self.assertRaisesRegex(ValueError, "西芹.*舍入为 0"):
            service.create_purchase("R", "School", "W", {}, {}, "current", confirmed=1,
                                    prices={service._price_key("CELERY", "g"): 0.000003})
        save_prices.assert_not_called()
        create_request.assert_not_called()

    def test_existing_price_also_checked_for_rounding_to_zero(self):
        plan = {"company": "School", "buying_price_list": "Standard Buying",
                "lines": [_dict(item_code="CELERY", item_name="西芹", uom="g", qty=1650)]}
        with patch.object(service, "_purchase_rate_precision", return_value=2), \
             patch.object(service, "_current_buying_price", return_value=0.000003), \
             patch.object(service.frappe, "throw", side_effect=self.reject), \
             self.assertRaisesRegex(ValueError, "舍入为 0"):
            service._validate_plan_prices(plan)

    def test_rate_validation_uses_site_precision_and_accepts_supported_prices(self):
        plan = {"company": "School", "buying_price_list": "Standard Buying",
                "lines": [_dict(item_code="CELERY", item_name="西芹", uom="g", qty=1650)]}
        for precision, rate in [(2, 0.02), (6, 0.000003)]:
            with self.subTest(precision=precision), \
                 patch.object(service, "_purchase_rate_precision", return_value=precision), \
                 patch.object(service.frappe, "throw", side_effect=ValueError):
                service._validate_plan_prices(plan, {service._price_key("CELERY", "g"): rate})

    def test_missing_source_date_rejected(self):
        request = MagicMock(items=[])
        with patch.object(service.frappe, 'throw', side_effect=ValueError), self.assertRaises(ValueError):
            service._daily_order_groups(request, [dict(material_request_item='missing', supplier='A', qty=1)])

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

    def test_complete_purchase_cycle_submits_all_documents(self):
        request = MagicMock(docstatus=1, material_request_type="Purchase")
        order = MagicMock(doctype="Purchase Order", docstatus=0)
        order.name = "PO1"
        receipt = MagicMock(docstatus=1)
        receipt.name = "PR1"
        invoice = MagicMock(docstatus=1, outstanding_amount=0)
        invoice.name = "PI1"
        payment = MagicMock(docstatus=1)
        payment.name = "PE1"
        with patch.object(service, "_permission"), \
             patch.object(service, "_read", return_value=request), \
             patch.object(service, "_active_purchase_orders", return_value=[order]), \
             patch.object(service, "_ensure_purchase_receipt", return_value=receipt), \
             patch.object(service, "_ensure_purchase_invoice", return_value=invoice), \
             patch.object(service, "_ensure_payment_entry", return_value=payment), \
             patch.object(service.frappe, "db", MagicMock()):
            result = service.complete_purchase_cycle("MR1")

        order.check_permission.assert_called_once_with("submit")
        order.submit.assert_called_once()
        self.assertEqual(result["purchase_orders"], ["PO1"])
        self.assertEqual(result["purchase_receipts"], ["PR1"])
        self.assertEqual(result["purchase_invoices"], ["PI1"])
        self.assertEqual(result["payment_entries"], ["PE1"])
        self.assertEqual(result["status"], "已完成")

    def test_zero_rate_invoice_is_rejected_before_insert(self):
        order = MagicMock(per_billed=0)
        order.name = "PO1"
        invoice = MagicMock(items=[_dict(qty=1, rate=0)])
        mapper = MagicMock()
        mapper.make_purchase_invoice.return_value = invoice
        with patch.dict("sys.modules", {"erpnext.buying.doctype.purchase_order.mapper": mapper}), \
             patch.object(service, "_linked_active_documents", return_value=[]), \
             patch.object(service.frappe, "throw", side_effect=ValueError), \
             self.assertRaises(ValueError):
            service._ensure_purchase_invoice(order)
        invoice.insert.assert_not_called()
