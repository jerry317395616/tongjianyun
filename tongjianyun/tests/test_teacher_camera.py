import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from datetime import datetime, timezone
from tongjianyun.teacher_camera import prepare, Rejected, ingest


class TestTeacherCamera(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 14, 1, 0, tzinfo=timezone.utc)
        self.config = {'cameras': {'gate': {'enabled': True, 'direction': 'IN'}},
                       'subjects': {'teacher': {'consent': True, 'employee': 'EMP-TEST'}},
                       'min_confidence': .9, 'min_margin': .2}
        self.event = {'camera_id': 'gate', 'event_id': '1', 'subject_id': 'teacher',
                      'occurred_at': '2026-09-14T09:00:00+08:00', 'face_count': 1,
                      'liveness_passed': True, 'confidence': .95, 'margin': .3}

    def test_valid_and_stable_id(self):
        a = prepare(self.event, self.config, self.now)
        self.assertEqual(a['log_type'], 'IN')
        self.assertEqual(a['name'], prepare(self.event, self.config, self.now)['name'])

    def test_rejections(self):
        for change in ({'subject_id': 'unknown'}, {'camera_id': 'unknown'},
                       {'confidence': .5}, {'confidence': float('nan')}, {'margin': .1},
                       {'liveness_passed': False}, {'face_count': 2}, {'face_count': True},
                       {'occurred_at': '2026-09-14T09:00:00'},
                       {'occurred_at': '2026-09-14T08:00:00+08:00'},
                       {'occurred_at': '2026-09-14T09:05:00+08:00'}, {'event_id': '../x'}):
            with self.subTest(change=change), self.assertRaises(Rejected):
                prepare({**self.event, **change}, self.config, self.now)

    def test_consent_and_direction_fail_closed(self):
        self.config['subjects']['teacher']['consent'] = False
        with self.assertRaises(Rejected):
            prepare(self.event, self.config, self.now)
        self.config['subjects']['teacher']['consent'] = True
        self.config['cameras']['gate']['direction'] = ''
        with self.assertRaises(Rejected):
            prepare(self.event, self.config, self.now)

    def test_caller_cannot_select_direction(self):
        self.assertEqual(prepare({**self.event, 'log_type': 'OUT'}, self.config, self.now)['log_type'], 'IN')

    def test_threshold_required(self):
        self.config.pop('min_confidence')
        with self.assertRaises(Rejected):
            prepare(self.event, self.config, self.now)

    def fake_frappe(self):
        f = MagicMock()
        f.session.user = 'service-test'
        f.conf.get.return_value = {**self.config, 'enabled': True}
        f.has_permission.return_value = True
        f.utils.get_system_timezone.return_value = 'Asia/Shanghai'
        f.db.get_value.side_effect = [SimpleNamespace(name='EMP-TEST', status='Active'), None, None]
        return f

    def test_preview_does_not_insert(self):
        f = self.fake_frappe()
        with patch.dict('sys.modules', {'frappe': f}), patch('tongjianyun.teacher_camera.prepare', return_value=prepare(self.event, self.config, self.now)):
            self.assertEqual(ingest(self.event)['status'], 'preview')
        f.get_doc.assert_not_called()

    def test_write_keeps_review_and_permissions(self):
        f = self.fake_frappe()
        with patch.dict('sys.modules', {'frappe': f}), patch('tongjianyun.teacher_camera.prepare', return_value=prepare(self.event, self.config, self.now)):
            self.assertEqual(ingest(self.event, dry_run=False)['status'], 'created')
        self.assertEqual(f.get_doc.call_args.args[0]['skip_auto_attendance'], 1)
        self.assertTrue(f.db.get_value.call_args_list[0].kwargs['for_update'])
        self.assertNotIn('ignore_permissions', f.get_doc.return_value.insert.call_args.kwargs)
        f.db.commit.assert_not_called()

    def test_write_disabled(self):
        f = self.fake_frappe()
        f.conf.get.return_value = self.config
        with patch.dict('sys.modules', {'frappe': f}), patch('tongjianyun.teacher_camera.prepare', return_value=prepare(self.event, self.config, self.now)):
            self.assertEqual(ingest(self.event, dry_run=False)['status'], 'disabled')
        f.get_doc.assert_not_called()

    def test_nearby_duplicate(self):
        f = self.fake_frappe()
        f.db.get_value.side_effect = [SimpleNamespace(name='EMP-TEST', status='Active'), None, 'EXISTING']
        with patch.dict('sys.modules', {'frappe': f}), patch('tongjianyun.teacher_camera.prepare', return_value=prepare(self.event, self.config, self.now)):
            self.assertEqual(ingest(self.event, dry_run=False)['status'], 'duplicate')
        f.get_doc.assert_not_called()


if __name__ == '__main__':
    unittest.main()
