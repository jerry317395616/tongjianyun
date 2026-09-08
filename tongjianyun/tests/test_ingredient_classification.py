import unittest
from types import SimpleNamespace
from tongjianyun.ingredient_classification import (
    ClassificationUnavailable, request_classification, validate_proposals,
)


class TestClassification(unittest.TestCase):
    def setUp(self):
        self.source = [{"key": "a", "ingredient": "大米", "unit": "g"}]
        self.groups = [{"name": "根", "is_group": 1}, {"name": "主食", "is_group": 0}]
        self.row = dict(key="a", action="existing", group="主食", parent="", reason="谷物")

    def validate(self, **changes):
        return validate_proposals({"rows": [{**self.row, **changes}]}, self.source, self.groups)

    def test_existing(self):
        self.assertEqual(self.validate()[0]["group"], "主食")

    def test_new(self):
        self.assertEqual(self.validate(action="new", group="谷物", parent="根")[0]["action"], "new")

    def test_no_group_per_ingredient(self):
        with self.assertRaises(ValueError):
            self.validate(action="new", group="大米", parent="根")

    def test_review(self):
        self.assertEqual(self.validate(action="review", group="")[0]["action"], "review")

    def test_bad_actions_and_targets(self):
        for patch in ({"action": "execute"}, {"group": "根"}, {"group": "未知"},
                      {"key": "b"}, {"action": "new", "parent": "主食", "group": "谷物"},
                      {"action": "new", "parent": "根", "group": "../谷物"},
                      {"action": "new", "parent": "根"}, {"reason": ""}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.validate(**patch)

    def test_soup_forces_review(self):
        self.source[0]["ingredient"] = "绿豆银耳汤"
        self.assertEqual(self.validate()[0]["action"], "review")

    def test_missing_extra_duplicate(self):
        for result in ({"rows": []}, {"rows": [self.row, self.row]}, {"rows": [self.row], "code": "x"}):
            with self.assertRaises(ValueError):
                validate_proposals(result, self.source, self.groups)

    def test_no_endpoint_never_falls_back(self):
        with self.assertRaises(ClassificationUnavailable):
            request_classification(SimpleNamespace(endpoint=None), self.source, self.groups)

    def test_strict_model_response(self):
        client = SimpleNamespace(endpoint="http://localhost/v1/chat/completions", model="test",
            _request_json=lambda **kw: {"rows": [self.row]})
        self.assertEqual(request_classification(client, self.source, self.groups)[0], self.row)

    def test_remote_exception_sanitized(self):
        def fail(**kw):
            raise RuntimeError("secret-in-url")
        client = SimpleNamespace(endpoint="http://localhost/v1/chat/completions", model="test", _request_json=fail)
        with self.assertRaises(ClassificationUnavailable) as result:
            request_classification(client, self.source, self.groups)
        self.assertNotIn("secret", str(result.exception))

    def test_local_linking_response_rejected(self):
        with self.assertRaises(ValueError):
            validate_proposals({"portions": []}, self.source, self.groups)

    def test_harness_result_uses_same_validation(self):
        client = SimpleNamespace(classify_ingredients=lambda ingredients, groups: {"rows": [self.row]})
        self.assertEqual(request_classification(client, self.source, self.groups)[0], self.row)
        client.classify_ingredients = lambda ingredients, groups: {"rows": []}
        with self.assertRaises(ValueError):
            request_classification(client, self.source, self.groups)
