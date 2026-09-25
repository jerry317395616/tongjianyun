"""OS identity only: no root commands or live site writes in these tests."""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tongjianyun import meal_view_tool as tool


class SiteIdentityTests(unittest.TestCase):
    def setUp(self):
        self.site = MagicMock()
        self.site.stat.return_value = SimpleNamespace(st_uid=1000, st_gid=1000)

    def test_root_drops_groups_and_identity_before_using_site(self):
        calls = []
        with patch.object(tool.os, 'geteuid', return_value=0), \
             patch('pwd.getpwuid', return_value=SimpleNamespace(pw_name='site-owner')), \
             patch.object(tool.os, 'initgroups', side_effect=lambda *args: calls.append(('groups', args))), \
             patch.object(tool.os, 'setgid', side_effect=lambda value: calls.append(('gid', value))), \
             patch.object(tool.os, 'setuid', side_effect=lambda value: calls.append(('uid', value))), \
             patch.object(tool.os, 'umask', side_effect=lambda value: calls.append(('umask', value))):
            tool.use_site_os_identity(self.site)
        self.assertEqual(calls, [('groups', ('site-owner', 1000)), ('gid', 1000), ('uid', 1000), ('umask', 0o077)])

    def test_service_owner_uses_private_file_umask_without_changing_identity(self):
        with patch.object(tool.os, 'geteuid', return_value=1000), \
             patch.object(tool.os, 'setuid') as setuid, patch.object(tool.os, 'umask') as umask:
            tool.use_site_os_identity(self.site)
        setuid.assert_not_called()
        umask.assert_called_once_with(0o077)

    def test_other_unix_user_cannot_create_unreadable_site_files(self):
        with patch.object(tool.os, 'geteuid', return_value=2000), patch.object(tool.os, 'umask') as umask:
            with self.assertRaises(RuntimeError):
                tool.use_site_os_identity(self.site)
        umask.assert_not_called()

    def test_root_owned_site_is_not_a_reason_to_keep_root(self):
        self.site.stat.return_value = SimpleNamespace(st_uid=0, st_gid=0)
        with self.assertRaises(RuntimeError):
            tool.use_site_os_identity(self.site)
