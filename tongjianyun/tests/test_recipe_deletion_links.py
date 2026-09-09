import json
import unittest
from unittest.mock import patch, MagicMock
from frappe import _dict
from tongjianyun import recipe_storage as service


class DeletionLinksTests(unittest.TestCase):
    def check(self, kind='erp_recipe_request', payload=None, exists=None):
        row = _dict(record_type=kind, record_json=json.dumps({'material_request': 'MR1'}) if payload is None else payload)
        with patch.object(service.frappe, 'db', MagicMock()) as db:
            db.exists.side_effect = exists or (lambda *args: False)
            return service._purchase_trace_blocks_deletion(row)

    def test_deleted_request_without_downstream_does_not_block(self):
        self.assertFalse(self.check())

    def test_existing_request_blocks(self):
        self.assertTrue(self.check(exists=lambda dt, value: dt == 'Material Request'))

    def test_each_downstream_blocks(self):
        for child in ('Purchase Order Item', 'Purchase Receipt Item', 'Purchase Invoice Item'):
            with self.subTest(child=child):
                self.assertTrue(self.check(exists=lambda dt, value: dt == child))

    def test_corrupt_and_incomplete_remain_blocked(self):
        for payload in ('{', '[]', '{}', '{"material_request": null}'):
            with self.subTest(payload=payload):
                self.assertTrue(self.check(payload=payload))

    def test_other_records_preserve_policy(self):
        self.assertTrue(self.check(kind='food_purchase'))
        self.assertFalse(self.check(kind='erp_recipe_auto_mapping'))

    def test_integration_count_and_actions(self):
        doc = _dict(name='R1', recipe_id='R1', title='Recipe', week_start=None,
                    week_end=None, workflow_status='已归档', is_deleted=0)
        row = _dict(record_type='erp_recipe_request', record_json='{"material_request":"MR1"}')
        with patch.object(service.frappe, 'db', MagicMock()) as db, \
             patch.object(service.frappe, 'get_all', return_value=[row]), \
             patch.object(service, '_can_restore_recipe', return_value=True):
            db.exists.return_value = False
            self.assertEqual(service._recipe_business_links(doc), [])
            self.assertTrue(service._recipe_actions(doc)['can_delete'])
            db.exists.return_value = True
            self.assertEqual(service._recipe_business_links(doc)[0]['count'], 1)
            self.assertFalse(service._recipe_actions(doc)['can_delete'])
