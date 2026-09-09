import unittest
from unittest.mock import AsyncMock, patch

from tongjianyun.codex_ingredient_client import CodexIngredientClient, thread_params
from tongjianyun.ingredient_classification import ClassificationUnavailable

INGREDIENTS = [{"key": "rice", "ingredient": "大米", "unit": "g"}]
GROUPS = [{"name": "粮油及主食", "is_group": 0, "parent_item_group": "所有物料组"}]
VALID = {"rows": [{"key": "rice", "action": "existing", "group": "粮油及主食", "parent": "", "reason": "谷物"}]}


class TestCodexIngredientClient(unittest.TestCase):
    def test_no_environment_or_dynamic_tools(self):
        params = thread_params("/tmp/isolated")
        self.assertEqual(params["environments"], [])
        self.assertEqual(params["dynamicTools"], [])
        self.assertTrue(params["ephemeral"])
        self.assertEqual(params["sandbox"], "read-only")
        self.assertFalse(params["config"]["features.shell_tool"])

    def test_valid_result(self):
        with patch.object(CodexIngredientClient, "_bounded", AsyncMock(return_value=VALID)):
            self.assertEqual(CodexIngredientClient().classify_ingredients(INGREDIENTS, GROUPS), VALID)

    def test_invalid_result_rejected(self):
        with patch.object(CodexIngredientClient, "_bounded", AsyncMock(return_value={"rows": []})):
            with self.assertRaises(ClassificationUnavailable):
                CodexIngredientClient().classify_ingredients(INGREDIENTS, GROUPS)

    def test_provider_error_sanitized(self):
        with patch.object(CodexIngredientClient, "_bounded", AsyncMock(side_effect=RuntimeError("private"))):
            with self.assertRaises(ClassificationUnavailable) as caught:
                CodexIngredientClient().classify_ingredients(INGREDIENTS, GROUPS)
            self.assertNotIn("private", str(caught.exception))

    def test_large_batch_not_sent(self):
        with patch.object(CodexIngredientClient, "_bounded", AsyncMock()) as call:
            with self.assertRaises(ClassificationUnavailable):
                CodexIngredientClient().classify_ingredients(INGREDIENTS * 21, GROUPS)
            call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
