import unittest

from tongjianyun.analysis_engine import analyze
from tongjianyun.nutrition_profiles import classify_ingredient


class AnalysisEngineTests(unittest.TestCase):
    def row(self, **values):
        return {"meal_date": "2026-06-22", "meal_type": "早餐", "ingredient_code": "MILK", "ingredient_name": "牛奶", "uom": "g", "per_child_qty": 125, "headcount": 257, "total_qty": 32125, **values}

    def test_per_child_average_never_multiplies_headcount(self):
        result = analyze([self.row()], ["2026-06-22"])
        self.assertEqual(result["nutrients"]["energy"], 77.5)
        self.assertEqual(result["nutrients"]["protein"], 4)
        self.assertIsNone(result["compliance_conclusion"])

    def test_week_averages_over_all_dates_including_days_without_food(self):
        result = analyze([self.row()], ["2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26"])
        self.assertEqual(result["nutrients"]["energy"], 15.5)
        self.assertEqual(result["daily_foods"]["2026-06-23"], 0)

    def test_ml_is_retained_and_not_assumed_grams(self):
        result = analyze([self.row(ingredient_name="绿豆银耳汤", uom="Millilitre", per_child_qty=150)], ["2026-06-22"])
        self.assertIsNone(result["nutrients"]["energy"])
        self.assertEqual(result["foods"][0]["quantity"], "150")
        self.assertEqual(result["foods"][0]["uom"], "Millilitre")
        self.assertEqual(result["used_rows"], 0)

    def test_unknown_and_broth_are_not_vegetables_or_water(self):
        for name in ("未识别食物", "骨汤", "绿豆银耳汤", "鲜面条", "核桃仁"):
            with self.subTest(name=name):
                self.assertEqual(classify_ingredient(name)[0], "unclassified")

    def test_longest_specific_keyword_precedes_generic_oil(self):
        self.assertEqual(classify_ingredient("油麦菜")[0], "green_veg")
        self.assertEqual(classify_ingredient("鸡蛋")[0], "egg")
        self.assertEqual(classify_ingredient("饮用水")[0], "water")

    def test_mass_units_convert_but_native_summary_units_stay_distinct(self):
        result = analyze([self.row(), self.row(uom="Kilogram", per_child_qty="0.125")], ["2026-06-22"])
        self.assertEqual(result["nutrients"]["energy"], 155)
        self.assertEqual(len(result["foods"]), 2)
        self.assertEqual(result["food_count"], 1)

    def test_missing_nutrient_value_is_null_instead_of_zero(self):
        result = analyze([self.row(ingredient_name="大米")], ["2026-06-22"])
        self.assertIsNone(result["nutrients"]["vitamin_a"])
        self.assertEqual(result["coverage"]["vitamin_a"], 0)

    def test_same_name_different_item_codes_are_not_merged(self):
        result = analyze([self.row(), self.row(ingredient_code="MILK-2")], ["2026-06-22"])
        self.assertEqual(result["food_count"], 2)

    def test_invalid_quantities_or_mismatched_dates_are_rejected(self):
        for value in (0, -1, "NaN", "Infinity", None, "missing"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                analyze([self.row(per_child_qty=value)], ["2026-06-22"])
        with self.assertRaises(ValueError):
            analyze([self.row()], ["2026-06-23"])

    def test_empty_suspended_week_has_no_fake_zero_nutrients(self):
        result = analyze([], ["2026-06-22"])
        self.assertTrue(all(value is None for value in result["nutrients"].values()))
        self.assertEqual(result["food_count"], 0)
