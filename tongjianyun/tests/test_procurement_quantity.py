import unittest
from unittest.mock import patch
from tongjianyun import recipe_procurement as service

class TestProcurementQuantity(unittest.TestCase):
    def check(self, factor=1, count=100, amount=50):
        def fail(message, *args):
            raise ValueError(message)
        with patch.object(service.frappe, 'throw', side_effect=fail):
            return service.checked_quantity({'ingredient_name': '骨汤', 'date': '2026-09-07', 'slot': 'lunch', 'unit': 'g', 'amount': amount},
                {'factor': factor, 'uom': 'Nos'}, {'2026-09-07:lunch': count})

    def test_missing_factor_is_not_count_error(self):
        with self.assertRaisesRegex(ValueError, '骨汤.*g.*Nos.*不是备餐人数问题'):
            self.check(factor=None)

    def test_count_error(self):
        with self.assertRaisesRegex(ValueError, '备餐人数未填写'):
            self.check(count='')

    def test_amount_error(self):
        with self.assertRaisesRegex(ValueError, '食谱用量无效'):
            self.check(amount=-1)

    def test_zero_count_preserved(self):
        self.assertEqual(self.check(count=0), (1, 0, 50))

    def test_overflow(self):
        with self.assertRaisesRegex(ValueError, '超出有效范围'):
            self.check(factor=1e300, amount=1e300)
