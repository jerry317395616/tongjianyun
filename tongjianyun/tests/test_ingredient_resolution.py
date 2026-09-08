import unittest
from tongjianyun.ingredient_resolution import candidate_score, requires_product_confirmation


class TestIngredientResolution(unittest.TestCase):
    def test_exact_name_is_candidate(self):
        self.assertEqual(candidate_score("大米", "大米")[0], 1)

    def test_alias_bidirectional(self):
        self.assertEqual(candidate_score("豆腐干", "豆干")[0], .99)
        self.assertEqual(candidate_score("豆干", "豆腐干")[0], .99)

    def test_tomato_alias(self):
        self.assertEqual(candidate_score("西红柿", "番茄")[0], .99)

    def test_different_specs_not_alias(self):
        self.assertLess(candidate_score("纯牛奶200ml", "纯牛奶250ml")[0], .99)

    def test_organic_not_stripped(self):
        self.assertLess(candidate_score("有机菜花", "菜花")[0], .99)

    def test_soups_require_confirmation(self):
        for name in ("骨汤", "绿豆银耳汤", "小米粥", "番茄炒蛋"):
            with self.subTest(name=name):
                self.assertTrue(requires_product_confirmation(name))

    def test_raw_ingredients(self):
        for name in ("大米", "西兰花", "黑米", "豆腐干"):
            with self.subTest(name=name):
                self.assertFalse(requires_product_confirmation(name))

    def test_unrelated_not_candidate(self):
        self.assertLess(candidate_score("大米", "西兰花")[0], .55)

    def test_processing_state_not_silently_equivalent(self):
        for source, target in (("绿豆", "绿豆芽"), ("芝麻酱", "黑芝麻"), ("面包", "面包棒"), ("玉米", "玉米粒")):
            with self.subTest(source=source, target=target):
                self.assertEqual(candidate_score(source, target)[0], 0)
