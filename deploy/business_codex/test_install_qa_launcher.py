"""No deployment/model calls: QA installer boundaries and exact-file behavior."""
from contextlib import ExitStack
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SPEC = importlib.util.spec_from_file_location('qa_launcher_installer', Path(__file__).with_name('install_qa_launcher.py'))
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_unit_is_fixed_qa_not_model_or_boot_enable(self):
        text = installer.UNIT_BYTES.decode()
        self.assertIn('/usr/bin/python3 -I -B /opt/tongjianyun-business-codex/native_launcher.py --serve', text)
        self.assertIn('Restart=no', text)
        self.assertNotIn('[Install]', text)
        self.assertNotIn('codex-deepseek-admin', text)
        self.assertNotIn('api-key', text)
        self.assertNotIn('child.myyr.top', text)

    def test_preflight_is_read_only_and_requires_hash(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(installer.os, 'geteuid', return_value=0, create=True))
            stack.enter_context(patch.object(installer.os, 'name', 'posix'))
            stack.enter_context(patch.object(installer.os, 'umask'))
            source = b'# fixed trusted candidate\n'
            stack.enter_context(patch.object(installer, 'read_regular', return_value=source))
            root = stack.enter_context(patch.object(installer, 'root_path'))
            root.return_value.open.return_value.__enter__.return_value = MagicMock()
            stack.enter_context(patch.object(installer.hashlib, 'file_digest', return_value=SimpleNamespace(hexdigest=lambda:'a'*64)))
            stack.enter_context(patch.object(installer, 'HASHES', {'codex':'a'*64}))
            stack.enter_context(patch.object(installer, 'qa_identity', return_value=(1000,1000)))
            stack.enter_context(patch.object(installer, 'exact_existing', return_value=False))
            stack.enter_context(patch.object(installer, 'refuse_live_units'))
            stack.enter_context(patch.object(installer, 'preflight_directories', return_value=[]))
            create = stack.enter_context(patch.object(installer, 'create_exact'))
            directory = stack.enter_context(patch.object(installer, 'root_directory'))
            run = stack.enter_context(patch.object(installer.subprocess, 'run'))
            result = installer.install(hashlib.sha256(source).hexdigest())
            self.assertTrue(result['preflight_passed'])
            self.assertFalse(result['installed'])
            self.assertFalse(result['service_started'])
            self.assertFalse(result['model_started'])
            create.assert_not_called()
            directory.assert_not_called()
            run.assert_not_called()
            with self.assertRaises(PermissionError):
                installer.install('b'*64)

    def test_no_root_no_install(self):
        with patch.object(installer.os, 'geteuid', return_value=1000, create=True), self.assertRaises(PermissionError):
            installer.install('a'*64, apply=True)

    def test_live_or_unresolved_unit_refuses_install(self):
        for line in ('tgy-business-codex-123.service loaded active running',
                     installer.SERVICE + ' loaded active running',
                     installer.SERVICE + ' loaded failed failed', 'unexpected'):
            with self.subTest(line=line), patch.object(installer.subprocess,'run',return_value=SimpleNamespace(stdout=line)), \
                    self.assertRaises(RuntimeError):
                installer.refuse_live_units()

    def test_empty_or_stopped_launcher_without_socket_is_acceptable(self):
        for line in ('', installer.SERVICE + ' loaded inactive dead'):
            with patch.object(installer.subprocess,'run',return_value=SimpleNamespace(stdout=line)), \
                    patch.object(type(installer.RUN),'exists',return_value=False):
                installer.refuse_live_units()

    def test_stale_socket_requires_review_not_unlink(self):
        with patch.object(installer.subprocess,'run',return_value=SimpleNamespace(stdout='')), \
                patch.object(type(installer.RUN),'exists',return_value=True), self.assertRaises(RuntimeError):
            installer.refuse_live_units()

    def test_qa_config_never_allows_production_or_live_backends(self):
        baseline = {'unified_business_acceptance':1, 'db_host':'127.0.0.1','db_port':23316,
            'db_name':'tgy_blueprint_qa','pause_scheduler':1,'disable_scheduler':1,
            'mute_emails':1,'disable_email_queue':1, 'redis_cache':'redis://127.0.0.1:23379/0',
            'redis_queue':'redis://127.0.0.1:23379/1','redis_socketio':'redis://127.0.0.1:23379/2'}
        for change in ({'db_name':'production'}, {'db_port':3306}, {'db_host':'localhost'},
                       {'redis_queue':'redis://127.0.0.1:6379/1'}, {'developer_mode':1},
                       {'pause_scheduler':0}, {'db_user':'root'}, {'disable_email_queue':0}):
            with self.subTest(change=change), patch.object(installer,'read_regular', side_effect=[
                    json.dumps({'owner':installer.QA_ROOT.name}).encode(), b'{}', json.dumps({**baseline,**change}).encode()]), \
                    self.assertRaises(PermissionError):
                installer.qa_identity()

    def test_different_existing_file_is_not_overwritten(self):
        path = MagicMock()
        path.exists.return_value = True
        path.stat.return_value = SimpleNamespace(st_mode=0o600,st_nlink=1)
        with patch.object(installer,'root_path'), patch.object(installer,'read_regular',return_value=b'old'), \
                self.assertRaises(PermissionError):
            installer.exact_existing(path,b'new',0o600)
        path.write_bytes.assert_not_called()

    def test_existing_redis_authentication_does_not_change_endpoint_guard(self):
        config = {'unified_business_acceptance':1, 'db_host':'127.0.0.1','db_port':23316,
            'db_name':'tgy_blueprint_qa','pause_scheduler':1,'disable_scheduler':1,
            'mute_emails':1,'disable_email_queue':1,
            **{key:'redis://:qa-placeholder-only@127.0.0.1:23379/'+db for key,db in
               (('redis_cache','0'),('redis_queue','1'),('redis_socketio','2'))}}
        self.assertIsNone(installer.validate_qa_config(config))
        for url in ('redis://127.0.0.1:23379/1?db=0', 'redis://127.0.0.1:23379/0',
                    'redis://127.0.0.1:6379/1','redis://other.example:23379/1'):
            with self.subTest(url=url), self.assertRaises(PermissionError):
                installer.validate_qa_config({**config,'redis_queue':url})

    @unittest.skipUnless(os.name == 'posix', 'Linux file flags and modes')
    def test_exclusive_private_file_is_idempotent_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(installer,'root_path',side_effect=lambda p,**kw:p):
            path = Path(directory)/'config'
            self.assertTrue(installer.create_exact(path,b'first',0o600))
            self.assertFalse(installer.create_exact(path,b'first',0o600))
            with self.assertRaises(PermissionError):
                installer.create_exact(path,b'second',0o600)
            self.assertEqual(path.read_bytes(),b'first')
            self.assertEqual(path.stat().st_mode & 0o777,0o600)

    @unittest.skipUnless(os.name == 'posix', 'Linux file flags and modes')
    def test_staging_failure_never_publishes_partial_final_file(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(installer,'root_path',side_effect=lambda p,**kw:p):
            path = Path(directory)/'config'
            with patch.object(installer.os,'fsync',side_effect=OSError('test disk failure')), self.assertRaises(OSError):
                installer.create_exact(path,b'complete bytes',0o600)
            self.assertFalse(path.exists())
            self.assertEqual(len(list(Path(directory).glob('.qa-launcher-stage-*'))),1)
            self.assertTrue(installer.create_exact(path,b'complete bytes',0o600))
            self.assertEqual(path.read_bytes(),b'complete bytes')


if __name__ == '__main__':
    unittest.main()
