import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


class Rejected(Exception):
    pass


class Recipe(dict):
    def __getattribute__(self, field):
        if field in self:
            return self[field]
        return super().__getattribute__(field)

    def set(self, field, value):
        self[field] = value

    def get_doc_before_save(self):
        return self.get("previous")


class StandardRecipeTests(unittest.TestCase):
    def setUp(self):
        self.frappe = ModuleType("frappe")
        self.frappe._ = lambda text: text
        self.frappe.throw = Mock(side_effect=Rejected)
        self.frappe.whitelist = lambda **kwargs: lambda fn: fn
        self.frappe.PermissionError = Rejected
        self.frappe.session = SimpleNamespace(user="reviewer")
        self.frappe.get_roles = Mock(return_value=["Manufacturing Manager"])
        self.frappe.has_permission = Mock(return_value=True)
        self.frappe.db = SimpleNamespace(get_value=Mock(return_value=SimpleNamespace(disabled=0, is_purchase_item=0)))
        utils = ModuleType("frappe.utils")
        utils.flt = lambda value: float(value or 0)
        utils.cint = lambda value: int(value or 0)
        with patch.dict(sys.modules, {"frappe": self.frappe, "frappe.utils": utils}):
            spec = importlib.util.spec_from_file_location("recipe_rules_test", Path(__file__).parents[1] / "standard_recipes.py")
            self.rules = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.rules)

    def recipe(self):
        rules = self.rules
        return Recipe({
            rules.MARKER: 1, rules.STATE: rules.DRAFT, rules.CATEGORY: "素菜",
            "item": "DISH", "quantity": 1, "is_active": 1, "flags": {},
            "items": [Recipe(item_code="FOOD", qty=45, uom="g", conversion_factor=1, bom_no=None, idx=1)],
        })

    def test_standard_recipe_validates_only_single_serving_and_net_quantity(self):
        doc = self.recipe()
        self.rules.validate_recipe(doc)
        doc["quantity"] = 2
        with self.assertRaises(Rejected):
            self.rules.validate_recipe(doc)
        doc["quantity"] = 1
        doc.items[0][self.rules.NET_QTY] = 46
        with self.assertRaises(Rejected):
            self.rules.validate_recipe(doc)

    def test_regular_bom_is_untouched(self):
        doc = Recipe(item="PART", quantity=50, flags={})
        self.rules.validate_recipe(doc)
        self.rules.save_draft(doc)
        self.rules.publish_recipe(doc)
        self.assertNotIn(self.rules.STATE, doc)
        self.frappe.db.get_value.assert_not_called()

    def test_recipe_revision_belongs_to_same_dish_and_company(self):
        rules = self.rules
        doc = self.recipe()
        doc.update(company="Kitchen A", **{rules.REPLACES: "BOM-ORIGINAL"})
        self.frappe.db.get_value.side_effect = [
            Recipe(disabled=0, is_purchase_item=0),
            Recipe(item="DISH", company="Kitchen B", docstatus=1, **{rules.MARKER: 1}),
        ]
        with self.assertRaises(Rejected):
            rules.validate_recipe(doc)
        previous = self.recipe()
        previous[rules.REPLACES] = "BOM-BASE"
        doc["previous"] = previous
        self.frappe.db.get_value.side_effect = None
        with self.assertRaises(Rejected):
            rules.validate_recipe(doc)

    def test_pending_draft_cannot_be_changed_in_place(self):
        rules = self.rules
        doc = self.recipe()
        previous = self.recipe()
        previous[rules.STATE] = rules.PENDING
        doc["previous"] = previous
        with self.assertRaises(Rejected):
            rules.save_draft(doc)
        doc.flags["tjy_recipe_review_transition"] = rules.DRAFT
        rules.save_draft(doc)
        self.assertEqual(doc[rules.STATE], rules.DRAFT)

    def test_publication_requires_review_and_rejects_bypasses(self):
        rules = self.rules
        doc = self.recipe()
        previous = self.recipe()
        doc["previous"] = previous
        with self.assertRaises(Rejected):
            rules.publish_recipe(doc)
        previous[rules.STATE] = rules.PENDING
        self.frappe.get_roles.return_value = ["Manufacturing User"]
        with self.assertRaises(Rejected):
            rules.publish_recipe(doc)
        self.frappe.get_roles.return_value = ["Manufacturing Manager"]
        doc["items"][0]["qty"] = 46
        with self.assertRaises(Rejected):
            rules.publish_recipe(doc)
        doc["items"][0]["qty"] = 45
        doc[rules.MARKER] = 0
        with self.assertRaises(Rejected):
            rules.publish_recipe(doc)
        doc[rules.MARKER] = 1
        rules.publish_recipe(doc)
        self.assertEqual(doc[rules.STATE], rules.PUBLISHED)
