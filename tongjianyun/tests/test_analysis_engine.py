import unittest

from tongjianyun.analysis_engine import analyze


class AnalysisEngineTests(unittest.TestCase):
    def row(self, **values):
        return {"meal_date": "2026-06-22", "meal_type": "早餐", "ingredient_code": "MILK", "ingredient_name": "牛奶", "uom": "g", "per_child_qty": 125, "headcount": 257, **values}

    def test_quantities_remain_per_child_and_original_units(self):
        result = analyze([self.row(), self.row(uom="Millilitre", per_child_qty=150)], ["2026-06-22", "2026-06-23"])
        self.assertEqual(result["foods"][0]["daily_quantity"], "62.5")
        self.assertEqual(result["foods"][1]["daily_quantity"], "75")
        self.assertEqual(result["food_count"], 1)
        self.assertEqual(result["daily_foods"]["2026-06-23"], 0)
        self.assertNotIn("nutrients", result)

    def test_same_names_keep_distinct_codes_and_invalid_source_is_rejected(self):
        self.assertEqual(analyze([self.row(), self.row(ingredient_code="M2")], ["2026-06-22"])["food_count"], 2)
        for value in (0, -1, "NaN", "Infinity", None, "missing"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                analyze([self.row(per_child_qty=value)], ["2026-06-22"])
        with self.assertRaises(ValueError):
            analyze([self.row()], ["2026-06-23"])

    def test_representative_nutrient_values_are_removed(self):
        import tongjianyun.nutrition_profiles as profiles
        self.assertFalse(hasattr(profiles, "CATEGORY_PROFILES"))
        self.assertNotIn("nutrients", analyze([], ["2026-06-22"]))
