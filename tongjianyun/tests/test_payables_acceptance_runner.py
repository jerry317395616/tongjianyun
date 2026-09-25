"""Safety/unit checks for the standalone runner, without loading Frappe or DB."""
import ast
import copy
from decimal import Decimal
from pathlib import Path
import unittest
from urllib.parse import urlparse

SOURCE = Path(__file__).resolve().parents[2] / 'deploy/unified_business/check_payables_lifecycle.py'


class PayablesRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {'guard', 'money'}]
        cls.scope = {'urlparse': urlparse, 'Decimal': Decimal}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), 'exec'), cls.scope)

    def test_guard_accepts_only_exact_qa_database_and_paused_scheduler(self):
        conf = {'unified_business_acceptance': 1, 'db_host': '127.0.0.1', 'db_port': 23316,
                'db_name': 'tgy_blueprint_qa', 'db_user': 'tgy_blueprint_qa',
                'pause_scheduler': 1, 'disable_scheduler': 1,
                **{key: 'redis://127.0.0.1:23379/' + str(i) for i, key in enumerate(
                    ('redis_cache', 'redis_queue', 'redis_socketio'))}}
        self.scope['guard'](conf)
        for key, value in [('unified_business_acceptance', 0), ('db_host', '172.18.112.42'),
                           ('db_port', 3306), ('db_name', 'production'), ('db_user', 'root'),
                           ('db_socket', '/tmp/mysql.sock'), ('developer_mode', 1),
                           ('pause_scheduler', 0), ('disable_scheduler', 0),
                           ('redis_cache', 'redis://127.0.0.1:6379'),
                           ('redis_queue', 'redis://0.0.0.0:23379'),
                           ('redis_socketio', 'rediss://127.0.0.1:23379')]:
            altered = copy.deepcopy(conf)
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(AssertionError):
                self.scope['guard'](altered)

    def test_amount_comparisons_preserve_cents_and_real_zero(self):
        money = self.scope['money']
        self.assertEqual(money('12.50'), Decimal('12.50'))
        self.assertEqual(money(0), Decimal('0.00'))
        self.assertEqual(money(None), Decimal('0.00'))


if __name__ == '__main__':
    unittest.main()
