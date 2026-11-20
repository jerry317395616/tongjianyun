"""Exercise the pre-connect QA guard without importing Frappe or the runner."""
import ast
import copy
import unittest
from pathlib import Path
from urllib.parse import urlparse

RUNNER = Path(__file__).with_name('check_asset_lifecycle.py')
module = ast.parse(RUNNER.read_text(encoding='utf-8'))
guard_node = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'guard')
namespace = {'urlparse': urlparse}
exec(compile(ast.Module(body=[guard_node], type_ignores=[]), str(RUNNER), 'exec'), namespace)
guard = namespace['guard']


class AssetLifecycleGuard(unittest.TestCase):
    def setUp(self):
        self.conf = {'unified_business_acceptance': 1, 'db_host': '127.0.0.1',
            'db_port': 23316, 'db_name': 'tgy_blueprint_qa', 'db_user': 'tgy_blueprint_qa',
            'developer_mode': 0, 'pause_scheduler': 1, 'disable_scheduler': 1,
            'redis_cache': 'redis://127.0.0.1:23379/0',
            'redis_queue': 'redis://127.0.0.1:23379/1',
            'redis_socketio': 'redis://127.0.0.1:23379/2'}

    def test_exact_isolated_configuration_is_accepted(self):
        guard(self.conf)

    def test_missing_marker_is_denied(self):
        self.conf.pop('unified_business_acceptance')
        with self.assertRaises(AssertionError):
            guard(self.conf)

    def test_non_qa_database_coordinates_are_denied(self):
        for field, value in [('db_host', '172.18.112.42'), ('db_port', 3306),
                             ('db_name', 'child'), ('db_user', 'root'), ('db_socket', '/var/run/mysql.sock')]:
            with self.subTest(field=field):
                changed = {**self.conf, field: value}
                with self.assertRaises(AssertionError):
                    guard(changed)

    def test_scheduler_and_developer_mode_must_remain_disabled(self):
        for field, value in [('pause_scheduler', 0), ('disable_scheduler', 0), ('developer_mode', 1)]:
            with self.subTest(field=field):
                with self.assertRaises(AssertionError):
                    guard({**self.conf, field: value})

    def test_each_redis_endpoint_must_be_exact_loopback_port(self):
        for field in ('redis_cache', 'redis_queue', 'redis_socketio'):
            for endpoint in ('redis://127.0.0.1:6379/0', 'redis://172.18.112.42:23379/0',
                             'rediss://127.0.0.1:23379/0', ''):
                with self.subTest(field=field, endpoint=endpoint):
                    changed = copy.deepcopy(self.conf)
                    changed[field] = endpoint
                    with self.assertRaises(AssertionError):
                        guard(changed)

    def test_effective_guard_is_called_before_database_connect(self):
        connect = next(node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == 'connect')
        calls = [ast.unparse(node.value) for node in connect.body if isinstance(node, ast.Expr)]
        self.assertLess(calls.index('guard(frappe.conf)'), calls.index('frappe.connect()'))


if __name__ == '__main__':
    unittest.main()
