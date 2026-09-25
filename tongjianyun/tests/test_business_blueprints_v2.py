"""Pure/mocked checks; schema and write tests run only in the isolated site."""
import copy
import unittest
from unittest.mock import MagicMock, patch

import frappe
from tongjianyun import business_blueprints as bp
from tongjianyun import business_blueprints_v2 as v2


SPEC = {'version': 2, 'key': 'activity_estimate', 'title': '活动筹备估算单',
        'description': '仅用于估算和复核，不采购、不付款、不扣库存。',
        'fields': [{'fieldname': 'estimated_total', 'label': '估算合计', 'fieldtype': 'Currency'}],
        'tables': [{'fieldname': 'estimate_lines', 'label': '估算明细', 'reqd': 1, 'fields': [
            {'fieldname': 'item_label', 'label': '项目', 'fieldtype': 'Data', 'reqd': 1},
            {'fieldname': 'quantity', 'label': '数量', 'fieldtype': 'Float', 'reqd': 1},
            {'fieldname': 'unit_price', 'label': '单价', 'fieldtype': 'Currency', 'reqd': 1},
            {'fieldname': 'line_amount', 'label': '小计', 'fieldtype': 'Currency'}]}],
        'calculations': [{'op': 'multiply', 'table': 'estimate_lines', 'target': 'line_amount',
                          'sources': ['quantity', 'unit_price']},
                         {'op': 'sum', 'table': 'estimate_lines', 'target': 'estimated_total', 'source': 'line_amount'}],
        'workflow': {'template': 'review'}}


class ComplexBlueprintTests(unittest.TestCase):
    def test_spec_is_canonical_and_roundtrips(self):
        spec = bp.validate_spec(SPEC)
        self.assertEqual(spec, bp.validate_spec(spec))
        self.assertEqual(spec['version'], 2)
        self.assertTrue(bp.doctype_name(spec).startswith(bp.COMPLEX_PREFIX))
        self.assertFalse(bp.doctype_name(spec).startswith(bp.PREFIX))

    def test_complex_namespace_cannot_downgrade_to_legacy_manifest(self):
        meta = frappe._dict(description='Business blueprint legacy\nTitle', is_submittable=0, fields=[])
        with patch.object(frappe, 'get_meta', return_value=meta), \
             patch.object(frappe, 'throw', side_effect=ValueError), self.assertRaises(ValueError):
            v2._runtime_spec(frappe._dict(doctype=bp.COMPLEX_PREFIX + 'example'))

    def test_calculation_graph_and_workflow_cannot_contain_code(self):
        for extra in [{'condition': 'True'}, {'roles': ['Guest']}, {'script': 'print(1)'}]:
            spec = copy.deepcopy(SPEC)
            spec['workflow'].update(extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError):
                bp.validate_spec(spec)
        for change in [{'op': 'eval'}, {'source': '__import__'}, {'target': 'owner'}, {'table': 'User'}]:
            spec = copy.deepcopy(SPEC)
            spec['calculations'][1].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                bp.validate_spec(spec)
        spec = copy.deepcopy(SPEC)
        spec['calculations'][0]['sources'] = ['line_amount', 'quantity']
        with self.assertRaises(ValueError):
            bp.validate_spec(spec)

    def test_limits_and_name_collisions(self):
        for mutate in [lambda s: s.update(tables=s['tables'] * 3),
                       lambda s: s['tables'][0].update(fieldname='estimated_total'),
                       lambda s: s['fields'][0].update(fieldname='workflow_state'),
                       lambda s: s['tables'][0]['fields'][0].update(fieldtype='Table'),
                       lambda s: s.update(calculations=s['calculations'] * 2)]:
            spec = copy.deepcopy(SPEC)
            mutate(spec)
            with self.assertRaises(ValueError):
                bp.validate_spec(spec)

    def test_definition_restricts_fields_permissions_and_review_actions(self):
        spec = bp.validate_spec(SPEC)
        child, parent = v2.definitions(spec)
        self.assertLessEqual(len('tab' + child['name']), 64)
        self.assertEqual(child['permissions'], [])
        self.assertEqual(parent['is_submittable'], 1)
        self.assertEqual(parent['permissions'][0]['cancel'], 1)
        self.assertEqual(parent['permissions'][0]['delete'], 0)
        self.assertEqual(parent['fields'][1]['read_only'], 1)
        self.assertEqual(parent['fields'][1]['precision'], '2')
        workflow = v2.workflow_definition(spec)
        self.assertEqual(workflow['send_email_alert'], 0)
        self.assertTrue(all(r['send_email'] == 0 for r in workflow['states']))
        review = [r for r in workflow['transitions'] if r['next_state'] == '扩展·通过'][0]
        self.assertEqual(review['allow_self_approval'], 0)
        self.assertEqual(review['allowed'], 'System Manager')
        self.assertFalse(any(r.get('condition') or r.get('transition_tasks') for r in workflow['transitions']))

    def test_partial_metadata_cannot_be_active_or_restarted_as_proposed(self):
        spec = bp.validate_spec(SPEC)
        with patch.object(frappe, 'db', MagicMock()) as db:
            db.exists.side_effect = [True, False, False]
            self.assertEqual(v2.state(spec), 'conflict')

    def test_unsafe_numbers_are_rejected(self):
        with patch.object(frappe, 'throw', side_effect=ValueError):
            for value in ['NaN', 'Infinity', '-1', 10**13, None, 'eval(1)']:
                with self.subTest(value=value), self.assertRaises(ValueError):
                    v2._number(value)

    def test_unrelated_doctype_does_not_load_metadata(self):
        with patch.object(frappe, 'get_meta') as meta:
            self.assertIsNone(v2._runtime_spec(frappe._dict(doctype='Purchase Order')))
        meta.assert_not_called()

    def test_direct_child_document_write_is_blocked(self):
        with patch.object(frappe, 'throw', side_effect=ValueError), self.assertRaises(ValueError):
            v2._runtime_spec(frappe._dict(doctype=v2.ROW_PREFIX + 'test'))

    def test_permission_bundle_checked_before_any_ddl(self):
        with patch.object(frappe, 'has_permission', side_effect=[True, frappe.PermissionError]), \
             patch.object(frappe, 'get_doc') as get_doc, self.assertRaises(frappe.PermissionError):
            v2.install(bp.validate_spec(SPEC), 'P')
        get_doc.assert_not_called()
