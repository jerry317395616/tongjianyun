"""Read-only stock canvas protocol; no real inventory or database mutations."""
import copy
import unittest
from unittest.mock import patch

import frappe
from tongjianyun import stock_operations, stock_reconciliation


CHOICE = {'view': 'stock_reconciliation', 'source_doctype': 'Purchase Receipt', 'source_name': 'QA-PR-1'}
INFO = {'source_doctype': 'Purchase Receipt', 'source_name': 'QA-PR-1', 'source_docstatus': 2,
        'company': 'Synthetic Company', 'currency': 'CNY', 'revision': 'a' * 64,
        'can_repair': True, 'warnings': ['金额需核对，不代表全部库存完成'], 'pending_revaluations': [],
        'rows': [{'item_code': 'Synthetic Item <script>', 'warehouse': 'Synthetic Warehouse',
                  'stock_uom': 'Kg', 'bin_qty': 10, 'ledger_qty': 10, 'bin_value': 24, 'ledger_value': 30,
                  'quantity_matches': True, 'value_matches': False, 'can_repair': True, 'reason': ''},
                 {'item_code': 'Synthetic Item B', 'warehouse': 'Synthetic Warehouse B',
                  'stock_uom': 'Nos', 'bin_qty': 0, 'ledger_qty': 0, 'bin_value': 0, 'ledger_value': 0,
                  'quantity_matches': True, 'value_matches': True, 'can_repair': False, 'reason': '一致'}],
        'summary': {'checked_pairs': 2, 'mismatched_pairs': 1, 'status': 'mismatch'}}


class StockReconciliationTests(unittest.TestCase):
    def view(self, info=None):
        with patch.object(stock_operations, 'inspect_stock', return_value=copy.deepcopy(info or INFO)) as inspect, \
             patch.object(stock_operations, 'repair_stock') as repair:
            result = stock_reconciliation.get_view(dict(CHOICE))
            inspect.assert_called_once_with('Purchase Receipt', 'QA-PR-1')
            repair.assert_not_called()
            return result

    def test_selection_accepts_only_two_native_sources_and_binds_an_exact_name(self):
        self.assertEqual(stock_reconciliation.selection(dict(CHOICE)), CHOICE)
        self.assertEqual(stock_reconciliation.selection(dict(CHOICE, source_doctype='Stock Entry'))['source_doctype'], 'Stock Entry')
        self.assertEqual(stock_reconciliation.selection(dict(CHOICE, source_name=' QA-PR-1 '))['source_name'], 'QA-PR-1')
        with patch.object(frappe, 'throw', side_effect=frappe.ValidationError):
            for update in [{'source_doctype': 'Bin'}, {'source_doctype': 'Purchase Invoice'},
                           {'source_name': ''}, {'source_name': ' '}, {'source_name': None},
                           {'source_name': 'x' * 141}]:
                with self.subTest(update=update), self.assertRaises(frappe.ValidationError):
                    stock_reconciliation.selection(dict(CHOICE, **update))

    def test_model_cannot_filter_away_warnings_or_supply_arbitrary_repair_targets(self):
        with patch.object(frappe, 'throw', side_effect=frappe.ValidationError):
            for key, value in [('components', ['table']), ('item_code', 'I'), ('warehouse', 'W'),
                               ('targets', []), ('revision', 'a' * 64), ('company', 'Other'),
                               ('day', '2026-09-25'), ('bin', 'BIN-1'), ('amount', 0)]:
                with self.subTest(key=key), self.assertRaises(frappe.ValidationError):
                    stock_reconciliation.selection(dict(CHOICE, **{key: value}))

    def test_view_reads_once_never_repairs_and_preserves_exact_source_revision_targets(self):
        result = self.view()
        repair = next(block for block in result['components'] if block['type'] == 'stock_repair')
        self.assertEqual(repair, {'type': 'stock_repair', 'source_doctype': 'Purchase Receipt',
            'source_name': 'QA-PR-1', 'revision': 'a' * 64, 'can_repair': True,
            'targets': [{'item_code': 'Synthetic Item <script>', 'warehouse': 'Synthetic Warehouse'}], 'status': 'mismatch'})
        self.assertEqual(result['actions'][0]['selection'], CHOICE)
        self.assertEqual(result['actions'][1]['selection'],
                         {'view': 'frappe_document', 'doctype': 'Purchase Receipt', 'document': 'QA-PR-1'})
        self.assertIn('尚未执行修复', result['summary']['answer'])

    def test_quantities_and_values_remain_per_pair_instead_of_cross_unit_sum(self):
        result = self.view()
        table = next(block for block in result['components'] if block['type'] == 'table')
        self.assertEqual(table['rows'][0]['cells'][:7],
            ['Synthetic Item <script>', 'Synthetic Warehouse', 'Kg', 10, 10, 24, 30])
        self.assertEqual(table['rows'][1]['cells'][2:7], ['Nos', 0, 0, 0, 0])
        self.assertEqual(table['columns'][5:7], ['库存汇总价值（CNY）', '有效流水价值（CNY）'])
        self.assertIn('Synthetic Company', result['subtitle'])
        self.assertEqual([item['unit'] for item in result['components'][0]['items']], ['组', '组'])
        self.assertTrue(any('不跨物料' in block.get('text', '') for block in result['components']))

    def test_missing_bin_values_stay_unknown_not_zero(self):
        info = copy.deepcopy(INFO)
        info['rows'][0].update(bin_qty=None, bin_value=None, can_repair=False,
                               reason='缺少原生库存记录，不能由核验接口新建')
        info['can_repair'] = False
        info['summary']['status'] = 'blocked'
        result = self.view(info)
        table = next(block for block in result['components'] if block['type'] == 'table')
        self.assertIsNone(table['rows'][0]['cells'][3])
        self.assertIsNone(table['rows'][0]['cells'][5])
        self.assertEqual(result['components'][-1]['targets'], [])
        self.assertFalse(result['components'][-1]['can_repair'])

    def test_pending_and_unposted_or_consistent_views_offer_no_repair(self):
        for status in ('pending', 'not_posted', 'consistent', 'blocked'):
            info = copy.deepcopy(INFO)
            info['summary']['status'] = status
            info['can_repair'] = False
            for row in info['rows']:
                row['can_repair'] = False
            if status == 'pending':
                info['pending_revaluations'] = [{'name': 'QA-Repost-1', 'status': 'Failed'}]
            result = self.view(info)
            with self.subTest(status=status):
                self.assertFalse(result['components'][-1]['can_repair'])
                self.assertEqual(result['components'][-1]['targets'], [])
                if status == 'pending':
                    self.assertTrue(any('不会强行执行队列' in block.get('text', '') for block in result['components']))

    def test_many_service_warnings_survive_bounded_component_protocol(self):
        info = copy.deepcopy(INFO)
        info['warnings'] = ['Warning ' + str(i) for i in range(40)]
        result = self.view(info)
        self.assertEqual([block['type'] for block in result['components']], ['stats', 'notice', 'table', 'stock_repair'])
        notices = [block for block in result['components'] if block['type'] == 'notice']
        self.assertTrue(notices[0]['warning'])
        for warning in info['warnings']:
            self.assertIn(warning, notices[0]['text'])

    def test_blocked_overall_can_still_offer_only_service_approved_subset(self):
        info = copy.deepcopy(INFO)
        info['summary'].update(status='blocked', mismatched_pairs=2)
        info['rows'][1].update(value_matches=False, can_repair=False,
                               reason='此估值方法需使用原生专项核验，本入口不进行重算')
        result = self.view(info)
        component = result['components'][-1]
        self.assertEqual(component['status'], 'blocked')
        self.assertTrue(component['can_repair'])
        self.assertEqual(component['targets'], [{'item_code': 'Synthetic Item <script>', 'warehouse': 'Synthetic Warehouse'}])
        table = next(block for block in result['components'] if block['type'] == 'table')
        self.assertIn('专项核验', table['rows'][1]['cells'][-1])

    def test_service_permission_failure_is_not_translated_to_zero_or_consistent(self):
        with patch.object(stock_operations, 'inspect_stock', side_effect=frappe.PermissionError('denied')), \
             patch.object(stock_operations, 'repair_stock') as repair:
            with self.assertRaises(frappe.PermissionError):
                stock_reconciliation.get_view(CHOICE)
            repair.assert_not_called()
