import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from tongjianyun.asset_history import PreserveAssetHistory


class Native:
    def delete_linked_asset(self):
        return 'native-delete'

    def update_fixed_asset(self, field, delete_asset=False):
        return ('native-update', field, delete_asset)


class Source(PreserveAssetHistory, Native):
    def __init__(self, doctype='Purchase Receipt', status=2, stock=1):
        self.doctype, self.docstatus, self.name, self.update_stock = doctype, status, 'EXACT-SOURCE', stock
        self.items = [SimpleNamespace(is_fixed_asset=1, item_code='EXACT-ITEM')]

    def get(self, field):
        return getattr(self, field, None)


class AssetHistoryTests(unittest.TestCase):
    def test_non_cancellation_and_non_acquisition_keep_native_helpers(self):
        for source in (Source(status=0), Source(status=1), Source(doctype='Purchase Order')):
            self.assertEqual(source.delete_linked_asset(), 'native-delete')
            self.assertEqual(source.update_fixed_asset('field', True), ('native-update', 'field', True))
        self.assertEqual(Source().update_fixed_asset('purchase_receipt'), ('native-update', 'purchase_receipt', False))

    def test_non_stock_invoice_retains_native_no_movement_cleanup(self):
        with patch.object(frappe.db, 'get_value') as read, patch.object(frappe, 'delete_doc') as delete:
            Source('Purchase Invoice', stock=0).delete_linked_asset()
        read.assert_not_called()
        delete.assert_not_called()

    def test_movement_lookup_scopes_reference_type_and_excludes_cancelled_history(self):
        for doctype in ('Purchase Receipt', 'Purchase Invoice'):
            with self.subTest(doctype=doctype), patch.object(frappe.db, 'get_value', return_value=None) as read, \
                 patch.object(frappe, 'delete_doc') as delete:
                Source(doctype).delete_linked_asset()
                read.assert_called_once_with('Asset Movement', {
                    'reference_doctype': doctype, 'reference_name': 'EXACT-SOURCE', 'docstatus': ['!=', 2]}, 'name')
                delete.assert_not_called()

    def test_live_movement_cleanup_keeps_native_delete_permission_and_submitted_check(self):
        with patch.object(frappe.db, 'get_value', return_value='EXACT-MOVEMENT'), \
             patch.object(frappe, 'delete_doc', side_effect=frappe.PermissionError) as delete:
            with self.assertRaises(frappe.PermissionError):
                Source().delete_linked_asset()
        delete.assert_called_once_with('Asset Movement', 'EXACT-MOVEMENT', force=1)

    def exercise(self, status, automatic, history=False, doctype='Purchase Receipt', submitted=None):
        source = Source(doctype)
        asset = MagicMock()
        asset.name, asset.docstatus, asset.flags = 'EXACT-ASSET', status, SimpleNamespace()
        reads = [('Asset', {'filters': {'purchase_receipt' if doctype == 'Purchase Receipt' else 'purchase_invoice': 'EXACT-SOURCE', 'item_code': 'EXACT-ITEM'}})]
        def get_all(kind, **kwargs):
            if kind == 'Asset':
                self.assertEqual((kind, kwargs), reads[0])
                return [SimpleNamespace(name='EXACT-ASSET')]
            self.assertEqual(kind, 'Asset Movement Item')
            self.assertEqual(kwargs, {'filters': {'asset': 'EXACT-ASSET'}, 'pluck': 'parent', 'limit_page_length': 0})
            return ['M1', 'M1', 'M2']
        stack = self.enterContext(__import__('contextlib').ExitStack())
        stack.enter_context(patch.object(frappe.db, 'get_value',
            side_effect=lambda kind, *args, **kwargs: automatic if kind == 'Item' else submitted))
        stack.enter_context(patch.object(frappe.db, 'exists', return_value=history))
        stack.enter_context(patch.object(frappe, 'get_all', side_effect=get_all))
        stack.enter_context(patch.object(frappe, 'get_doc', return_value=asset))
        delete = stack.enter_context(patch.object(frappe, 'delete_doc'))
        return source, asset, delete

    def test_cancelled_asset_is_retained_in_manual_and_auto_modes_without_mutation(self):
        for automatic in (0, 1):
            for doctype in ('Purchase Receipt', 'Purchase Invoice'):
                with self.subTest(automatic=automatic, doctype=doctype):
                    source, asset, delete = self.exercise(2, automatic, doctype=doctype)
                    source.update_fixed_asset('purchase_receipt' if doctype == 'Purchase Receipt' else 'purchase_invoice', True)
                    asset.save.assert_not_called()
                    asset.set.assert_not_called()
                    delete.assert_not_called()

    def test_submitted_asset_is_refused_before_any_cleanup(self):
        for automatic in (0, 1):
            source, asset, delete = self.exercise(1, automatic)
            with patch('tongjianyun.asset_history.get_link_to_form', return_value='ASSET'), \
                 patch('tongjianyun.asset_history._', side_effect=lambda value: value), \
                 patch.object(frappe, 'throw', side_effect=frappe.ValidationError):
                with self.assertRaises(frappe.ValidationError):
                    source.update_fixed_asset('purchase_receipt', True)
            asset.save.assert_not_called()
            delete.assert_not_called()

    def test_auto_draft_without_history_uses_native_cleanup_without_permission_bypass(self):
        source, asset, delete = self.exercise(0, 1)
        source.update_fixed_asset('purchase_receipt', True)
        self.assertEqual(delete.call_args_list, [
            unittest.mock.call('Asset Movement', 'M1', force=1), unittest.mock.call('Asset Movement', 'M2', force=1),
            unittest.mock.call('Asset', 'EXACT-ASSET', force=1)])
        asset.save.assert_not_called()

    def test_auto_draft_with_cancelled_movement_history_is_detached_not_erased(self):
        source, asset, delete = self.exercise(0, 1, history=True)
        source.update_fixed_asset('purchase_receipt', True)
        asset.set.assert_called_once_with('purchase_receipt', None)
        asset.save.assert_called_once_with()
        self.assertIsNone(asset.supplier)
        self.assertFalse(hasattr(asset.flags, 'ignore_permissions'))
        delete.assert_not_called()

    def test_auto_asset_with_submitted_movement_keeps_native_rejection(self):
        for status in (0, 2):
            with self.subTest(status=status):
                source, asset, delete = self.exercise(status, 1, history=True, submitted='M1')
                with patch('tongjianyun.asset_history.check_permission_and_not_submitted',
                           side_effect=frappe.ValidationError) as native_check:
                    with self.assertRaises(frappe.ValidationError):
                        source.update_fixed_asset('purchase_receipt', True)
                native_check.assert_called_once()
                asset.save.assert_not_called()
                delete.assert_not_called()

    def test_manual_draft_keeps_native_detach_and_normal_save_permission(self):
        source, asset, delete = self.exercise(0, 0)
        source.update_fixed_asset('purchase_receipt', True)
        asset.set.assert_called_once_with('purchase_receipt', None)
        asset.save.assert_called_once_with()
        delete.assert_not_called()

    def test_unused_auto_draft_cleanup_does_not_bypass_delete_permission(self):
        source, asset, delete = self.exercise(0, 1)
        delete.side_effect = frappe.PermissionError
        with self.assertRaises(frappe.PermissionError):
            source.update_fixed_asset('purchase_receipt', True)
        asset.save.assert_not_called()
        delete.assert_called_once_with('Asset Movement', 'M1', force=1)

    def test_draft_detach_does_not_bypass_save_permission(self):
        for automatic in (0, 1):
            source, asset, delete = self.exercise(0, automatic, history=True)
            asset.save.side_effect = frappe.PermissionError
            with self.assertRaises(frappe.PermissionError):
                source.update_fixed_asset('purchase_receipt', True)
            asset.save.assert_called_once_with()
            delete.assert_not_called()

    def test_non_fixed_asset_rows_do_not_trigger_cleanup_queries(self):
        source = Source()
        source.items[0].is_fixed_asset = 0
        with patch.object(frappe.db, 'get_value') as read, patch.object(frappe, 'delete_doc') as delete:
            source.update_fixed_asset('purchase_receipt', True)
        read.assert_not_called()
        delete.assert_not_called()

    def test_wrong_reference_field_is_rejected_before_queries(self):
        with patch.object(frappe.db, 'get_value') as read, patch.object(frappe, 'throw', side_effect=frappe.ValidationError), \
             patch('tongjianyun.asset_history._', side_effect=lambda value: value):
            with self.assertRaises(frappe.ValidationError):
                Source().update_fixed_asset('purchase_invoice', True)
        read.assert_not_called()
