"""Pure/mocked boundary tests. Real stock evidence uses the isolated runner."""
import copy
import json
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
from tongjianyun import stock_operations as service


class StockOperationsTests(unittest.TestCase):
    def test_source_whitelist_before_any_doc_lookup(self):
        with patch.object(frappe, 'get_doc') as get:
            for doctype in ('Bin', 'Sales Invoice', '', None, 'Purchase Receipt;drop'):
                with self.subTest(doctype=doctype), self.assertRaises(frappe.ValidationError):
                    service._source(doctype, 'x')
            get.assert_not_called()

    def test_source_requires_exact_name_and_original_read(self):
        doc = MagicMock()
        with patch.object(frappe, 'get_doc', return_value=doc), patch.object(service, '_read_fields'):
            service._source('Purchase Receipt', 'PR-1')
            doc.check_permission.assert_called_once_with('read')
            for name in ('', ' PR-1', 'x\n', 'a' * 141):
                with self.assertRaises(frappe.ValidationError):
                    service._source('Purchase Receipt', name)

    def test_guest_rejected(self):
        with patch.object(frappe, 'session', SimpleNamespace(user='Guest')):
            with self.assertRaises(frappe.PermissionError):
                service._access()

    def test_disabled_or_missing_actor_rejected_using_current_database_state(self):
        db = MagicMock()
        with patch.object(frappe, 'session', SimpleNamespace(user='reader')), patch.object(frappe, 'db', db):
            for value in (0, None):
                db.get_value.return_value = value
                with self.assertRaises(frappe.PermissionError):
                    service._access()
            db.get_value.return_value = 1
            service._access()
            db.get_value.assert_called_with('User', 'reader', 'enabled')

    def test_targets_only_exact_item_and_warehouse(self):
        row = {'item_code': 'I', 'warehouse': 'W'}
        self.assertEqual(service._targets(json.dumps([row])), [('I', 'W')])
        invalid = [None, [], {}, [row, row], [dict(row, bin='BIN-1')], [{'name': 'BIN'}],
                   [dict(row, warehouse=' W')], [dict(row, item_code=3)], [row] * 21,
                   'not json', 'x' * 16385]
        for value in invalid:
            with self.subTest(value=str(value)[:80]), self.assertRaises(frappe.ValidationError):
                service._targets(value)

    def test_pending_statuses_fail_closed(self):
        rows = [dict(name=str(i), docstatus=status, status=state) for i, (status, state) in enumerate([
            (1, 'Queued'), (1, 'In Progress'), (1, 'Failed'), (0, 'Completed'), (1, 'Unknown'),
            (1, 'Completed'), (1, 'Skipped'), (2, 'Cancelled')])]
        self.assertEqual([row['name'] for row in service._pending(rows)], ['0', '1', '2', '3', '4'])

    def test_numeric_comparison_rejects_nonfinite(self):
        self.assertTrue(service._matches(0.30000000000000004, 0.3))
        self.assertFalse(service._matches(24, 30))
        self.assertFalse(service._matches(1000000, 1000000.01))
        for value in ('NaN', float('inf'), 'not-number', None, ''):
            with self.assertRaises(frappe.ValidationError):
                service._number(value)

    def test_native_field_level_and_mask_permission_fail_closed(self):
        doc = MagicMock()
        doc.get_permlevel_access.return_value = [0]
        doc.meta.get_field.return_value = SimpleNamespace(permlevel=1)
        doc.meta.get_masked_fields.return_value = []
        with patch.object(frappe, 'session', SimpleNamespace(user='reader')):
            with self.assertRaises(frappe.PermissionError):
                service._read_fields(doc, ['stock_value'])
            doc.meta.get_field.return_value = SimpleNamespace(permlevel=0)
            doc.meta.get_masked_fields.return_value = [SimpleNamespace(fieldname='stock_value')]
            with self.assertRaises(frappe.PermissionError):
                service._read_fields(doc, ['stock_value'])
            doc.meta.get_masked_fields.return_value = []
            service._read_fields(doc, ['stock_value'])

    def test_revision_canonical_and_changes_with_job_or_actor(self):
        base = {'user': 'a', 'job': {'status': 'Completed'}, 'source': 'PR'}
        self.assertEqual(service._hash(base), service._hash(dict(reversed(list(base.items())))))
        for value in (dict(base, user='b'), dict(base, job={'status': 'Queued'})):
            self.assertNotEqual(service._hash(base), service._hash(value))

    def harness(self, before=None, after=None, immutable_after='fixed'):
        stack = ExitStack()
        self.addCleanup(stack.close)
        source, bin_doc, db = MagicMock(), MagicMock(), MagicMock()
        row = {'item_code': 'I', 'warehouse': 'W', 'can_repair': True,
               'quantity_matches': True, 'value_matches': False}
        before = before or {'revision': 'a' * 64, 'rows': [row], 'pending_revaluations': []}
        after = after or {'revision': 'b' * 64, 'rows': [dict(row, can_repair=False, value_matches=True)],
                          'pending_revaluations': []}
        stack.enter_context(patch.object(service, '_access'))
        stack.enter_context(patch.object(service, '_repair_environment', return_value=True))
        stack.enter_context(patch.object(frappe, 'request', SimpleNamespace(method='POST')))
        stack.enter_context(patch.object(frappe, 'db', db))
        stack.enter_context(patch.object(service, '_source', return_value=source))
        stack.enter_context(patch.object(service, '_source_pairs', return_value=[('I', 'W')]))
        locks = stack.enter_context(patch.object(service, '_lock_pairs'))
        snapshots = stack.enter_context(patch.object(service, '_snapshot', side_effect=[
            (before, {('I', 'W'): bin_doc}, 'fixed'), (after, {('I', 'W'): bin_doc}, immutable_after)]))
        return source, bin_doc, db, locks, snapshots

    def repair(self, **kwargs):
        params = dict(source_doctype='Purchase Receipt', source_name='PR',
            targets=[{'item_code': 'I', 'warehouse': 'W'}], revision='a' * 64, confirm='recalculate')
        params.update(kwargs)
        return service.repair_stock(**params)

    def test_post_confirm_revision_rejected_before_source_or_locks(self):
        source, bin_doc, _, locks, _ = self.harness()
        for kwargs in ({'confirm': True}, {'confirm': None}, {'revision': 'z' * 64}, {'revision': ''}):
            with self.assertRaises(frappe.ValidationError):
                self.repair(**kwargs)
        with patch.object(frappe, 'request', SimpleNamespace(method='GET')):
            with self.assertRaises(frappe.ValidationError):
                self.repair()
        source.check_permission.assert_not_called()
        locks.assert_not_called()
        bin_doc.recalculate_values.assert_not_called()

    def test_original_source_write_permission_before_locks(self):
        source, bin_doc, db, locks, _ = self.harness()
        source.check_permission.side_effect = frappe.PermissionError
        with self.assertRaises(frappe.PermissionError):
            self.repair()
        locks.assert_not_called()
        db.savepoint.assert_not_called()
        bin_doc.recalculate_values.assert_not_called()

    def test_production_repair_gate_rejects_before_doc_locks_or_mutations(self):
        source, bin_doc, db, locks, _ = self.harness()
        with patch.object(service, '_repair_environment', return_value=False):
            with self.assertRaises(frappe.ValidationError):
                self.repair()
        source.check_permission.assert_not_called()
        locks.assert_not_called()
        db.savepoint.assert_not_called()
        bin_doc.recalculate_values.assert_not_called()

    def test_isolated_repair_gate_requires_exact_site_path_database_and_redis(self):
        conf = {'unified_business_acceptance': 1, 'db_host': '127.0.0.1', 'db_port': 23316,
                'db_name': 'tgy_blueprint_qa', 'pause_scheduler': 1, 'disable_scheduler': 1,
                'redis_cache': 'redis://127.0.0.1:23379/0', 'redis_queue': 'redis://127.0.0.1:23379/1',
                'redis_socketio': 'redis://127.0.0.1:23379/2'}
        with patch.object(frappe, 'conf', conf), patch.object(frappe, 'local', SimpleNamespace(site=service.QA_SITE)), \
             patch.object(frappe, 'get_site_path', return_value=service.QA_SITE_PATH):
            self.assertTrue(service._repair_environment())
            for key, wrong in [('db_host', 'remote'), ('db_port', 3306), ('db_name', 'production'),
                    ('unified_business_acceptance', 0), ('redis_queue', 'redis://127.0.0.1:6379/1'),
                    ('redis_cache', 'redis://127.0.0.1:23379@outside.test/0'), ('db_socket', '/tmp/mysql.sock')]:
                other = dict(conf, **{key: wrong})
                with self.subTest(key=key), patch.object(frappe, 'conf', other):
                    self.assertFalse(service._repair_environment())
            with patch.object(frappe, 'local', SimpleNamespace(site='child.myyr.top')):
                self.assertFalse(service._repair_environment())
            with patch.object(frappe, 'get_site_path', return_value='/tmp/' + service.QA_SITE):
                self.assertFalse(service._repair_environment())

    def test_arbitrary_unrelated_pair_rejected(self):
        _, bin_doc, db, locks, _ = self.harness()
        with self.assertRaises(frappe.ValidationError):
            self.repair(targets=[{'item_code': 'OTHER', 'warehouse': 'W'}])
        locks.assert_not_called()
        bin_doc.recalculate_values.assert_not_called()
        db.rollback.assert_called_once()

    def test_stale_revision_rolls_back_without_native_call(self):
        _, bin_doc, db, _, _ = self.harness()
        with self.assertRaises(frappe.ValidationError):
            self.repair(revision='c' * 64)
        bin_doc.recalculate_values.assert_not_called()
        db.rollback.assert_called_once()

    def test_pending_or_unpermitted_target_cannot_repair(self):
        before = {'revision': 'a' * 64, 'rows': [{'item_code': 'I', 'warehouse': 'W', 'can_repair': False}],
                  'pending_revaluations': [{'status': 'Queued'}]}
        _, bin_doc, db, _, _ = self.harness(before=before)
        with self.assertRaises(frappe.ValidationError):
            self.repair()
        bin_doc.recalculate_values.assert_not_called()
        db.rollback.assert_called_once()

    def test_native_permission_failure_rolls_back(self):
        _, bin_doc, db, _, _ = self.harness()
        bin_doc.check_permission.side_effect = frappe.PermissionError
        with self.assertRaises(frappe.PermissionError):
            self.repair()
        bin_doc.recalculate_values.assert_not_called()
        db.rollback.assert_called_once()

    def test_native_recalculation_and_audit_no_independent_commit(self):
        source, bin_doc, db, locks, _ = self.harness()
        result = self.repair()
        self.assertEqual(result['status'], 'recalculated')
        locks.assert_called_once_with([('I', 'W')])
        bin_doc.check_permission.assert_called_once_with('write')
        bin_doc.recalculate_values.assert_called_once_with()
        source.add_comment.assert_called_once()
        db.commit.assert_not_called()
        db.rollback.assert_not_called()

    def test_failed_postcondition_rolls_back_native_work(self):
        after = {'revision': 'b' * 64, 'rows': [{'item_code': 'I', 'warehouse': 'W',
                 'quantity_matches': True, 'value_matches': False}], 'pending_revaluations': []}
        source, bin_doc, db, _, _ = self.harness(after=after)
        with self.assertRaises(frappe.ValidationError):
            self.repair()
        bin_doc.recalculate_values.assert_called_once()
        db.rollback.assert_called_once()
        source.add_comment.assert_not_called()

    def test_ledger_change_during_recalculation_rolls_back(self):
        source, bin_doc, db, _, _ = self.harness(immutable_after='changed')
        with self.assertRaises(frappe.ValidationError):
            self.repair()
        bin_doc.recalculate_values.assert_called_once()
        db.rollback.assert_called_once()
        source.add_comment.assert_not_called()

    def test_deadlock_whole_transaction_rollback_does_not_mask_original_conflict(self):
        _, bin_doc, db, _, _ = self.harness()
        bin_doc.recalculate_values.side_effect = frappe.QueryDeadlockError('conflict')
        with self.assertRaises(frappe.QueryDeadlockError):
            self.repair()
        db.rollback.assert_called_once_with()
        db.commit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
