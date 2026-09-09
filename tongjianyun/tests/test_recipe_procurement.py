import unittest
from unittest.mock import MagicMock, patch

from frappe import _dict
from tongjianyun import recipe_procurement as service


class TestRecipeProcurement(unittest.TestCase):
    def test_mass_conversion(self):
        self.assertEqual(service.conversion("克", "Kg"), .001)

    def test_volume_conversion(self):
        self.assertEqual(service.conversion("ml", "L"), .001)

    def test_no_density_guess(self):
        self.assertIsNone(service.conversion("ml", "kg"))

    def test_no_packaging_guess(self):
        self.assertIsNone(service.conversion("盒", "kg"))

    def test_same_unit(self):
        self.assertEqual(service.conversion("盒", "盒"), 1)

    def test_nonfinite_rejected(self):
        for value in ("nan", "inf", "-inf", -1, 0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                service.number(value)

    def test_zero_attendance(self):
        self.assertEqual(service.number(0, zero=True, integer=True), 0)

    def test_fractional_attendance_rejected(self):
        with self.assertRaises(ValueError):
            service.number(3.5, zero=True, integer=True)

    def test_hash_order_independent(self):
        self.assertEqual(service.digest({"a": 1, "b": 2}), service.digest({"b": 2, "a": 1}))

    def test_hash_detects_change(self):
        self.assertNotEqual(service.digest({"count": 1}), service.digest({"count": 2}))

    def make_plan(self, counts=None, unit="kg", factor=.001):
        item = _dict(name="RICE", item_name="大米", stock_uom=unit, disabled=0,
                     is_purchase_item=1, has_variants=0, is_stock_item=1)
        warehouse = _dict(company="School", is_group=0, disabled=0)
        rows = [dict(name="a", key="rice", ingredient_name="大米", date="2099-01-01", slot="breakfast", amount=50),
                dict(name="b", key="rice", ingredient_name="大米", date="2099-01-01", slot="lunch", amount=100)]
        with patch.object(service, "_source", return_value=(_dict(name="WEEK"), rows)), \
             patch.object(service, "_read", side_effect=lambda dt, name: warehouse if dt == "Warehouse" else item), \
             patch.object(service, "_payload", side_effect=lambda v: v), \
             patch.object(service.frappe, "db", new=MagicMock()), \
             patch.object(service, "nowdate", return_value="2026-09-08"), \
             patch.object(service.frappe, "throw", side_effect=ValueError):
            return service._plan("WEEK", "School", "Kitchen",
                {"rice": {"item_code": "RICE", "uom": "kg", "factor": factor}},
                counts if counts is not None else {"2099-01-01:breakfast": 10, "2099-01-01:lunch": 20})

    def test_aggregate_by_day_and_item_with_meal_counts(self):
        plan = self.make_plan()
        self.assertEqual(len(plan["lines"]), 1)
        self.assertEqual(plan["lines"][0]["qty"], 2.5)

    def test_zero_meal_not_replaced_by_enrolled_count(self):
        plan = self.make_plan({"2099-01-01:breakfast": 0, "2099-01-01:lunch": 20})
        self.assertEqual(plan["lines"][0]["qty"], 2)

    def test_missing_count_rejected(self):
        with self.assertRaises((ValueError, TypeError)):
            self.make_plan({})

    def test_empty_requirement_rejected(self):
        with self.assertRaises(ValueError):
            self.make_plan({"2099-01-01:breakfast": 0, "2099-01-01:lunch": 0})

    def test_changed_item_uom_rejected(self):
        with self.assertRaises(ValueError):
            self.make_plan(unit="g")

    def test_edible_yield_is_explicit_factor(self):
        self.assertEqual(self.make_plan(factor=.001 / .8)["lines"][0]["qty"], 3.125)


if __name__ == "__main__":
    unittest.main()
