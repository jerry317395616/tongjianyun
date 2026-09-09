import unittest
from unittest.mock import patch, MagicMock
from types import SimpleNamespace
from tongjianyun import recipe_product_decisions as decisions
from tongjianyun import recipe_item_sync as sync

class TestProductDecisions(unittest.TestCase):
    def test_recipe_specific_key(self):
        self.assertNotEqual(decisions.record_key("a", "rice"), decisions.record_key("b", "rice"))

    def test_unconfirmed_soup_stays_blocked(self):
        with patch.object(decisions, "read_decision", return_value=None):
            mapping, reason = sync._match({"key": "x", "ingredient": "骨汤", "unit": "g"}, "recipe")
            self.assertIsNone(mapping)
            self.assertTrue(reason)

    def test_homemade_and_skipped_stay_unresolved(self):
        for mode in ("自制", "暂时跳过"):
            with patch.object(decisions, "read_decision", return_value={"mode": mode}), \
                 patch.object(decisions, "external_mapping") as external:
                mapping, reason = sync._match({"key": "x", "ingredient": "骨汤", "unit": "g"}, "recipe")
                self.assertIsNone(mapping)
                self.assertTrue(reason)
                external.assert_not_called()

    def test_external_mapping_revalidates(self):
        with patch.object(decisions, "read_decision", return_value={"mode": "外购", "item_code": "i"}), \
             patch.object(decisions, "external_mapping", return_value={"item_code": "i"}) as external:
            mapping, reason = sync._match({"key": "x", "ingredient": "骨汤", "unit": "g"}, "recipe")
            self.assertEqual(mapping["item_code"], "i")
            external.assert_called_once()

    def test_stale_confirmation_rejected_before_writes(self):
        with patch.object(sync, "source_snapshot", return_value={"revision": "new"}), \
             patch.object(decisions.frappe, "throw", side_effect=ValueError), \
             patch.object(decisions.frappe, "get_doc") as write:
            with self.assertRaises(ValueError):
                decisions.confirm("r", "old", [])
            write.assert_not_called()
