import copy
import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
from tongjianyun import recipe_item_sync as sync
from tongjianyun import recipe_procurement as procurement

class TestRecipeRevision(unittest.TestCase):
    def setUp(self):
        self.meta = {"week_start": "2099-01-01", "workflow_status": "草稿"}
        self.ingredients = [{"ingredient_name": "大米", "unit": "g", "amount": 50, "recipe_dish": "dish"}]
        self.dishes = [{"name": "dish", "dish_name": "米饭", "meal_date": "2099-01-01", "meal_slot": "lunch"}]

    def fingerprint(self, ingredients=None, dishes=None):
        return sync.content_revision(self.meta, self.ingredients if ingredients is None else ingredients,
            self.dishes if dishes is None else dishes)

    def test_quantity_name_unit_and_dish_changes_invalidate(self):
        original = self.fingerprint()
        for field, value in [("amount", 60), ("ingredient_name", "小米"), ("unit", "kg"), ("recipe_dish", "other")]:
            rows = copy.deepcopy(self.ingredients)
            rows[0][field] = value
            self.assertNotEqual(original, self.fingerprint(ingredients=rows))

    def test_date_meal_and_dish_name_changes_invalidate(self):
        original = self.fingerprint()
        for field, value in [("meal_date", "2099-01-02"), ("meal_slot", "breakfast"), ("dish_name", "粥")]:
            dishes = copy.deepcopy(self.dishes)
            dishes[0][field] = value
            self.assertNotEqual(original, self.fingerprint(dishes=dishes))

    def test_delete_and_add_invalidate(self):
        self.assertNotEqual(self.fingerprint(), self.fingerprint(ingredients=[]))
        self.assertNotEqual(self.fingerprint(), self.fingerprint(ingredients=self.ingredients * 2))

    def test_query_order_does_not_invalidate(self):
        rows = self.ingredients + [{"ingredient_name": "猪肉", "amount": 10}]
        self.assertEqual(self.fingerprint(ingredients=rows), self.fingerprint(ingredients=list(reversed(rows))))

    def test_old_plan_rejected_before_item_writes(self):
        with patch.object(sync, "_permission"), patch.object(sync, "_read", return_value=SimpleNamespace(modified="v2")), \
             patch.object(sync.frappe, "db", MagicMock(get_value=MagicMock(return_value="v2"))), \
             patch.object(sync, "source_snapshot", return_value={"revision": "new"}), \
             patch.object(sync.frappe, "throw", side_effect=ValueError), \
             patch.object(sync.frappe, "get_doc") as write:
            with self.assertRaises(ValueError):
                sync.apply_plan({"recipe": "r", "revision": "old"})
            write.assert_not_called()

    def test_purchase_impact_is_read_only(self):
        recipe = SimpleNamespace(is_deleted=False, workflow_status="已发布")
        trace = SimpleNamespace(record_json='{"material_request":"MR-1","revision":"old"}')
        mr = SimpleNamespace(name="MR-1", docstatus=1)
        with patch.object(procurement, "_permission"), \
             patch.object(procurement, "_read", side_effect=[recipe, trace, mr]), \
             patch.object(procurement, "_source", return_value=(recipe, [{"amount": 60}])), \
             patch.object(procurement.frappe, "get_list", return_value=[SimpleNamespace(name="trace")]), \
             patch.object(procurement.frappe, "get_doc") as write:
            result = procurement.revision_impact("r")
            self.assertTrue(result["requests"][0]["changed"])
            self.assertEqual(result["requests"][0]["docstatus"], 1)
            write.assert_not_called()
