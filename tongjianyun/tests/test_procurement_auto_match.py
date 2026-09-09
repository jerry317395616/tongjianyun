import unittest
from unittest.mock import patch
from tongjianyun import recipe_procurement as service
from tongjianyun import recipe_item_sync as sync


class TestProcurementAutoMatch(unittest.TestCase):
    def test_active_job_is_reused(self):
        for status in ('queued', 'running'):
            with patch.object(service, '_permission'), patch.object(service, '_source'), \
                 patch.object(sync, 'get_sync_status', return_value={'status': status}), \
                 patch.object(sync, 'schedule_after_save') as queue:
                self.assertEqual(service.auto_match_items('recipe')['status'], status)
                queue.assert_not_called()

    def test_terminal_states_schedule_existing_sync(self):
        for status in ('not_started', 'stale', 'failed', 'partial', 'completed', 'needs_review'):
            with patch.object(service, '_permission') as permission, patch.object(service, '_source') as source, \
                 patch.object(sync, 'get_sync_status', return_value={'status': status}), \
                 patch.object(sync, 'schedule_after_save', return_value={'status': 'queued'}) as queue:
                self.assertEqual(service.auto_match_items('recipe')['status'], 'queued')
                permission.assert_called_once_with('Material Request', 'create')
                source.assert_called_once_with('recipe')
                queue.assert_called_once_with('recipe')

    def test_denied_request_does_not_queue(self):
        with patch.object(service, '_permission', side_effect=PermissionError), \
             patch.object(sync, 'schedule_after_save') as queue:
            with self.assertRaises(PermissionError):
                service.auto_match_items('recipe')
            queue.assert_not_called()

    def test_unpublished_source_does_not_queue(self):
        with patch.object(service, '_permission'), patch.object(service, '_source', side_effect=ValueError), \
             patch.object(sync, 'schedule_after_save') as queue:
            with self.assertRaises(ValueError):
                service.auto_match_items('recipe')
            queue.assert_not_called()

    def test_blocked_sync_is_exposed(self):
        with patch.object(service, '_permission'), patch.object(service, '_source'), \
             patch.object(sync, 'get_sync_status', return_value={'status': 'failed'}), \
             patch.object(sync, 'schedule_after_save', return_value={'status': 'blocked'}):
            self.assertEqual(service.auto_match_items('recipe')['status'], 'blocked')
