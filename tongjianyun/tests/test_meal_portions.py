import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


class Rejected(ValueError):
    pass


class Row(dict):
    __getattr__ = dict.__getitem__

    def precision(self, field):
        return 3


class MealPortionTests(unittest.TestCase):
    def setUp(self):
        frappe = ModuleType("frappe")
        frappe.throw = Mock(side_effect=Rejected)
        frappe.whitelist = lambda **kwargs: lambda fn: fn
        frappe.parse_json = json.loads
        utils = SimpleNamespace(flt=lambda value, precision=None: round(float(value), precision), getdate=str)
        stubs = {
            "frappe": frappe, "frappe.utils": utils,
            "ione_core": SimpleNamespace(meal_planning=SimpleNamespace()),
            "tongjianyun.dish_library": SimpleNamespace(
                _visible=Mock(), _supports_inline_ingredients=lambda recipe: not recipe.percentage,
            ),
            "tongjianyun.recipe_nutrition": SimpleNamespace(SNAPSHOT="snapshot"),
            "tongjianyun.standard_recipes": SimpleNamespace(MARKER="managed", NET_QTY="net", REPLACES="replaces", STATE="state"),
        }
        spec = importlib.util.spec_from_file_location("meal_portion_test", Path(__file__).parents[1] / "meal_portions.py")
        self.portions = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, stubs):
            spec.loader.exec_module(self.portions)
        self.recipe = SimpleNamespace(name="BOM-1", is_active=1, docstatus=1, quantity=1, company="School",
                                      percentage=False, items=[
                                          Row(name="row-a", idx=1, qty=40, net=None, item_code="FOOD"),
                                          Row(name="row-b", idx=2, qty=20, net=15, item_code="FOOD"),
                                      ])

    def test_changes_use_the_recipe_row_and_keep_net_separate(self):
        self.assertEqual(self.portions._changes(self.recipe, [{"row": "row-a", "gross": "35", "net": "30"}]),
                         {"row-a": (35, 30)})
        self.assertEqual(self.portions._changes(self.recipe, [{"row": "row-b", "gross": 20, "net": ""}]),
                         {"row-b": (20, None)})
        self.assertEqual(self.portions._changes(self.recipe, [{"row": "row-a", "gross": "40", "net": ""}]), {})

    def test_malformed_quantities_and_unknown_or_duplicate_rows_are_rejected(self):
        valid = {"row": "row-a", "gross": 35, "net": 30}
        for invalid in ({"gross": 0}, {"gross": "NaN"}, {"gross": "35.0001"}, {"net": 36}, {"row": "another-bom"}):
            with self.subTest(invalid=invalid), self.assertRaises(Rejected):
                self.portions._changes(self.recipe, [{**valid, **invalid}])
        with self.assertRaises(Rejected):
            self.portions._changes(self.recipe, [valid, valid])

    def test_restoring_existing_adjustment_returns_the_standard_recipe(self):
        week = SimpleNamespace(name="WEEK", company="School")
        with patch.object(self.portions, "meal_scope", return_value="scope"), patch.object(
            self.portions, "_recipes", return_value=(Mock(), self.recipe),
        ):
            self.assertEqual(self.portions.resolve(week, "2026-11-24", "早餐", "BOM-ADJUSTED", []), self.recipe.name)
