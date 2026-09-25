"""Pure diagnostic construction/cleanup tests; never execute systemd or bwrap."""
from pathlib import Path
import sys
import unittest
from unittest import mock

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import diagnose_native_start as diagnostic
import native_sandbox as native

TASK = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee'


class DiagnosticTests(unittest.TestCase):
    def test_preserves_all_systemd_boundary_properties(self):
        original = native.build_systemd_command(TASK)
        command = diagnostic.build_command(native, TASK)
        self.assertEqual(command[:-5], original[:-5])
        self.assertEqual(command[-5:], ['/usr/bin/python3', '-I', '-c', diagnostic.CHILD, TASK])
        self.assertIn('--property=DynamicUser=yes', command)
        self.assertIn('--property=NoNewPrivileges=yes', command)

    def test_fixed_child_and_probe_compile_without_execution(self):
        compile(diagnostic.CHILD, '<diagnostic-child>', 'exec')
        compile(diagnostic.PROBE, '<diagnostic-probe>', 'exec')
        self.assertIn('native.export_seccomp_fd()', diagnostic.CHILD)
        self.assertIn('native.build_bwrap_command(', diagnostic.CHILD)
        self.assertIn("argv=argv[:-3]+['/usr/bin/python3','-I','-c'", diagnostic.CHILD)
        for forbidden in ('KEY_FILE', 'read_model_key', 'import frappe', 'Redis', 'requests.', 'codex exec'):
            self.assertNotIn(forbidden, diagnostic.CHILD + diagnostic.PROBE)

    def test_profiles_change_only_the_four_fixed_proc_related_properties(self):
        def legacy_command(task):
            return [item.replace('ProtectKernelTunables=no', 'ProtectKernelTunables=yes')
                    .replace('ProtectKernelLogs=no', 'ProtectKernelLogs=yes')
                    .replace('ProtectHostname=no', 'ProtectHostname=yes')
                    for item in native.build_systemd_command(task)]
        legacy = mock.Mock(spec=['build_systemd_command'])
        legacy.build_systemd_command.side_effect = legacy_command
        baseline = diagnostic.build_command(legacy, TASK)
        protected = ('DynamicUser=yes', 'NoNewPrivileges=yes', 'CapabilityBoundingSet=',
                     'AmbientCapabilities=', 'PrivateNetwork=yes', 'ProtectHome=yes',
                     'ProtectSystem=strict', 'PrivateDevices=yes', 'ProtectKernelModules=yes',
                     'ProtectControlGroups=yes', 'ProtectClock=yes')
        for profile, differences in diagnostic.PROFILES.items():
            with self.subTest(profile=profile):
                command = diagnostic.build_command(legacy, TASK, profile)
                self.assertEqual(command[-5:], baseline[-5:])
                self.assertEqual(len(command), len(baseline))
                self.assertEqual(sum(a != b for a, b in zip(command, baseline)), len(differences))
                for item in protected:
                    self.assertIn('--property=' + item, command)
                for key in differences:
                    self.assertIn(key, {'ProtectProc', 'ProtectKernelTunables', 'ProtectKernelLogs', 'ProtectHostname'})

    def test_historical_matrix_is_refused_after_proc_fix(self):
        for profile in diagnostic.PROFILES:
            if profile != 'baseline':
                with self.subTest(profile=profile), self.assertRaises(ValueError):
                    diagnostic.build_command(native, TASK, profile)
        with mock.patch.object(diagnostic, 'load_native', return_value=native), mock.patch.object(Path, 'mkdir') as mkdir:
            with self.assertRaises(ValueError):
                diagnostic.run('proc-overmounts-off')
            mkdir.assert_not_called()

    def test_unknown_profile_refused_before_runtime_or_files(self):
        with mock.patch.object(diagnostic, 'load_native') as load:
            with self.assertRaises(ValueError):
                diagnostic.run('arbitrary-property')
            load.assert_not_called()
        with self.assertRaises(ValueError):
            diagnostic.build_command(native, TASK, 'DynamicUser=no')

    def test_nonroot_refused_before_file_or_subprocess_access(self):
        with mock.patch.object(diagnostic.sys, 'platform', 'linux'), mock.patch.object(diagnostic.os, 'geteuid', return_value=1000, create=True), mock.patch.object(diagnostic, 'root_path') as paths, mock.patch.object(diagnostic.subprocess, 'run') as process:
            with self.assertRaises(PermissionError):
                diagnostic.run()
            paths.assert_not_called()
            process.assert_not_called()

    def test_cleanup_does_not_touch_unowned_directory_or_unit(self):
        with mock.patch.object(diagnostic.subprocess, 'run') as process, mock.patch.object(Path, 'unlink') as unlink:
            result = diagnostic.cleanup(native, TASK, diagnostic.INPUT / TASK, None, False)
            self.assertFalse(result['owned'])
            process.assert_not_called()
            unlink.assert_not_called()

    def test_cleanup_rejects_wrong_target(self):
        with mock.patch.object(diagnostic.subprocess, 'run') as process:
            with self.assertRaises(ValueError):
                diagnostic.cleanup(native, TASK, Path('/tmp/wrong'), None, True)
            process.assert_not_called()

    def test_failed_stop_still_revokes_inputs_but_retains_directory(self):
        listener = mock.Mock()
        with mock.patch.object(diagnostic.subprocess, 'run', side_effect=OSError), mock.patch.object(Path, 'unlink') as unlink, mock.patch.object(Path, 'rmdir') as rmdir:
            result = diagnostic.cleanup(native, TASK, diagnostic.INPUT / TASK, listener, True)
            self.assertFalse(result['unit_stopped'])
            self.assertFalse(result['inputs_removed'])
            self.assertEqual(unlink.call_count, 3)
            rmdir.assert_not_called()
            listener.close.assert_called_once()

    def test_fixed_error_classes_and_bounded_classification(self):
        self.assertEqual(diagnostic.error_class('bwrap: setting up uid map: Operation not permitted'), 'uid_map')
        self.assertEqual(diagnostic.error_class('bwrap: Creating new namespace failed: Operation not permitted'), 'user_namespace')
        self.assertEqual(diagnostic.error_class('bwrap: Failed to mount /proc: Permission denied'), 'mount')
        self.assertEqual(diagnostic.error_class('x' * 4096 + 'uid_map'), 'other')


if __name__ == '__main__':
    unittest.main()
