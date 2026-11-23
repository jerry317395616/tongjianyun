import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch


class IngredientLibraryTests(unittest.TestCase):
    def setUp(self):
        item_module = ModuleType("erpnext.stock.doctype.item.item")
        item_module.get_uom_conv_factor = lambda *_: None
        standard_recipes = ModuleType("tongjianyun.standard_recipes")
        standard_recipes.DISH = "dish"
        standard_recipes.MARKER = "recipe"
        self.frappe = ModuleType("frappe")
        self.frappe.whitelist = lambda **kwargs: lambda fn: fn
        self.frappe.has_permission = Mock()
        with patch.dict(sys.modules, {
            "frappe": self.frappe,
            "erpnext.stock.doctype.item.item": item_module,
            "tongjianyun.standard_recipes": standard_recipes,
        }):
            spec = importlib.util.spec_from_file_location(
                "ingredient_library_test", Path(__file__).parents[1] / "ingredient_library.py",
            )
            self.library = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.library)

    def test_form_code_requires_create_permission_and_missing_code_is_generated_on_insert(self):
        library = self.library

        class Item(SimpleNamespace):
            def get(self, name):
                return getattr(self, name, None)

        code = library.new_ingredient_code()
        self.frappe.has_permission.assert_called_once_with("Item", "create", throw=True)
        self.assertRegex(code, r"^TJY-AUTO-[0-9A-F]{20}$")

        standard = Item(item_code="", **{library.MARKER: 1})
        library.set_ingredient_code(standard)
        self.assertRegex(standard.item_code, r"^TJY-AUTO-[0-9A-F]{20}$")
        self.assertNotEqual(standard.item_code, code)
        library.set_ingredient_code(standard)
        standard.item_code = "EXISTING-22"
        library.set_ingredient_code(standard)
        self.assertEqual(standard.item_code, "EXISTING-22")

        ordinary = Item(item_code="")
        library.set_ingredient_code(ordinary)
        self.assertEqual(ordinary.item_code, "")

    def test_conversion_uses_explicit_package_factor_and_native_mass_factor(self):
        library = self.library
        item = dict(name="X", stock_uom="Kg", variant_of="XT")
        generic = lambda unit, stock: {"g": .001, "箱": 1}.get(unit)
        self.assertEqual(library.configured_conversion(item, "Kg", {}, generic), 1)
        self.assertEqual(library.configured_conversion(item, "g", {}, generic), .001)
        self.assertEqual(library.configured_conversion(item, "箱", {}, generic), 0)
        self.assertEqual(library.configured_conversion(item, "箱", {("XT", "箱"): 8}, generic), 8)
        self.assertEqual(library.configured_conversion(item, "g", {("X", "g"): 0}, generic), 0)

    def test_alias_normalization_and_audit_findings_keep_distinct_item_codes(self):
        library = self.library

        class Item(dict):
            __getattr__ = dict.__getitem__

        item = Item(name="I-1", item_name="土豆", item_group="食谱样例食材", stock_uom="Kg",
                    purchase_uom="箱", variant_of=None)
        item[library.ALIASES] = "马铃薯\n Pot ato \nＰＯＴＡＴＯ"
        duplicate = Item(name="I-2", item_name="马铃薯")
        row = SimpleNamespace(item_code="I-1", uom="g")
        results = list(library.audit_findings(
            [item], [item, duplicate], [row], {"Kg", "箱", "g"}, {}, lambda *_: .001,
        ))
        self.assertEqual(set(library.aliases_for(item[library.ALIASES])), {"马铃薯", "potato"})
        self.assertEqual({r["issue"] for r in results}, {"待确认分类", "疑似重复", "缺少单位换算"})
        self.assertTrue(any("I-2" in r["detail"] for r in results))
        self.assertTrue(all(r["item_code"] == "I-1" for r in results))
