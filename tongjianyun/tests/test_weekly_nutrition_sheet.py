import copy
import json
import threading
import time
import unittest
from unittest.mock import MagicMock, patch
from io import BytesIO

from openpyxl import load_workbook

from tongjianyun.ai_nutrition import NUTRIENTS, model_messages, source_data, source_hash, validate_result
from tongjianyun.ephemeral_nutrition import AnalysisStore, make_generator
from tongjianyun.weekly_nutrition_sheet import workbook_bytes


def sample():
    dates = [f"2026-06-{day}" for day in range(22, 27)]
    data = source_data([dict(meal_date=dates[0], meal_type="早餐", ingredient_code="X", ingredient_name="=1+1", uom="Millilitre", per_child_qty=150)], dates,
                       {"week_start": dates[0], "week_name": None, "plan_batch": "synthetic"})
    result = {"categories": [{"food": 0, "category": "成品待核对"}],
              "nutrients": [{"key": key, "daily": [[123, 145]] * 5, "average": [124, 144], "basis": "模型参考估算"} for key in NUTRIENTS],
              "assumptions": ["成品无法核实品牌；一般营养知识估算"], "missing": ["无密度资料，不把毫升换成克"]}
    return data, result


class WeeklyNutritionTests(unittest.TestCase):
    def test_compatible_model_document_tag_is_discarded_before_strict_validation(self):
        data, result = sample()
        tagged = {**result, "type": "nutrition_analysis"}
        response = MagicMock()
        response.status_code = 200
        response.iter_content.return_value = [json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(tagged)}}]}).encode()]
        session = MagicMock()
        session.post.return_value.__enter__.return_value = response
        with patch("tongjianyun.ephemeral_nutrition.requests.Session", return_value=session):
            output = make_generator({"base_url": "https://example.invalid/v1", "api_key": "synthetic", "model": "synthetic", "max_tokens": 10000, "request_timeout": 180})(data)
        self.assertEqual(validate_result(output, data), result)
        self.assertNotIn("type", output)

    def test_model_is_given_only_recipe_source_and_output_is_not_recalculated(self):
        data, result = sample()
        self.assertEqual(data["foods"][0]["daily"], "30")
        self.assertNotIn("nutrients", data)
        self.assertIn("每名幼儿", model_messages(data)[0]["content"])
        self.assertIs(validate_result(result, data), result)
        sheet = load_workbook(BytesIO(workbook_bytes(data, result))).active
        self.assertEqual(sheet["N5"].value, "124–144")
        name = next(cell for row in sheet for cell in row if cell.value == "=1+1")
        self.assertEqual(name.data_type, "s")
        self.assertFalse(any(cell.data_type == "f" for row in sheet for cell in row))

    def test_malformed_or_incomplete_model_output_fails_closed(self):
        data, good = sample()
        mutations = [lambda x: x.update(nutrients=x["nutrients"][:-1]),
                     lambda x: x["nutrients"][0].update(average=[145, 123]),
                     lambda x: x["nutrients"][0].update(average=[float("nan"), 1]),
                     lambda x: x["nutrients"][0].update(average=[True, 1]),
                     lambda x: x["nutrients"][0].update(daily=[None] * 5),
                     lambda x: x["categories"][0].update(food=5),
                     lambda x: x.update(untrusted="extra")]
        for mutation in mutations:
            bad = copy.deepcopy(good)
            mutation(bad)
            with self.assertRaises(ValueError):
                validate_result(bad, data)

    def test_source_fingerprint_binds_dates_quantities_and_selection(self):
        data, _ = sample()
        changed = copy.deepcopy(data)
        changed["lines"][0]["per_child_gross_quantity"] = "151"
        self.assertNotEqual(source_hash(data), source_hash(changed))

    def test_memory_results_are_owner_bound_expire_and_can_be_cleared(self):
        data, result = sample()
        clock = [1000]
        store = AnalysisStore(now=lambda: clock[0], ttl=60, generate=lambda _: result)
        created = store.create("owner", data)
        report_id = created["report_id"]
        for _ in range(100):
            if store.read("owner", report_id)["status"] == "ready":
                break
            time.sleep(.005)
        self.assertNotIn("result", store.read("owner", report_id, metadata=True))
        self.assertEqual(store.read("other", report_id), {"ok": False, "code": "NOT_FOUND"})
        self.assertEqual(store.read("owner", report_id)["result"], result)
        clock[0] = 1060
        self.assertFalse(store.read("owner", report_id)["ok"])
        self.assertEqual(store.records, {})
        second = store.create("owner", data)["report_id"]
        self.assertTrue(store.read("owner", second, discard=True)["ok"])
        self.assertFalse(store.read("owner", second)["ok"])

    def test_capacity_failure_and_provider_errors_retain_no_values(self):
        data, result = sample()
        release = threading.Event()
        def generate(_):
            release.wait(2)
            raise ValueError("PRIVATE PROVIDER BODY 123456")
        store = AnalysisStore(max_concurrent=1, generate=generate)
        report_id = store.create("owner", data)["report_id"]
        self.assertEqual(store.create("another", data), {"ok": False, "code": "BUSY"})
        release.set()
        for _ in range(100):
            if store.read("owner", report_id)["status"] != "pending":
                break
            time.sleep(.005)
        payload = store.read("owner", report_id)
        self.assertEqual(payload["status"], "failed")
        self.assertNotIn("result", payload)
        self.assertNotIn("PRIVATE", str(store.records))
