"""Recipe layout regression tests; synthetic workbooks, no database writes."""
import unittest
from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook
from ione_agent.structured import StructuredTaskClient
from tongjianyun.recipe_import import RecipeImportError, _find_date_columns, parse_recipe_workbook


class TestRecipeImport(unittest.TestCase):
    def sheet(self, title="幼儿园2026年9月7日—9月11日食谱", headers=None):
        sheet = Workbook().active
        sheet.merge_cells("A1:G1")
        sheet["A1"] = title
        sheet.append(["餐点", None] + (headers or ["星期一", "星期二", "星期三", "星期四", "星期五"]))
        sheet.append(["早餐", "主食品"] + ["牛奶"] * 5)
        sheet.append([None, "带量"] + ["牛奶125g"] * 5)
        return sheet

    def test_weekday_headers_use_title_range_not_title_column(self):
        columns = _find_date_columns(self.sheet(), 2026)
        self.assertEqual([c["column"] for c in columns], [3, 4, 5, 6, 7])
        self.assertEqual([c["date"].isoformat() for c in columns], [f"2026-09-{i:02d}" for i in range(7, 12)])

    def test_explicit_date_headers_unchanged(self):
        columns = _find_date_columns(self.sheet(headers=[f"9月{i}日 星期{w}" for i, w in zip(range(7, 12), "一二三四五")]), 2026)
        self.assertEqual(len(columns), 5)
        self.assertEqual(columns[0]["column"], 3)

    def test_native_excel_dates(self):
        columns = _find_date_columns(self.sheet(headers=[datetime(2026, 9, i) for i in range(7, 12)]), 2026)
        self.assertEqual(len(columns), 5)

    def test_single_date_does_not_pick_title(self):
        columns = _find_date_columns(self.sheet(headers=["9月7日"]), 2026)
        self.assertEqual([c["column"] for c in columns], [3])

    def test_range_separators_and_abbreviated_end(self):
        for separator in ["—", "--", "至", "～", "到"]:
            with self.subTest(separator=separator):
                columns = _find_date_columns(self.sheet(title=f"幼儿园2026年9月7日{separator}11日食谱"), 2026)
                self.assertEqual(columns[-1]["date"], date(2026, 9, 11))

    def test_cross_month_and_explicit_cross_year(self):
        for title, start, end in [("2026年8月31日—9月4日食谱", date(2026, 8, 31), date(2026, 9, 4)),
                                  ("2026年12月28日—2027年1月1日食谱", date(2026, 12, 28), date(2027, 1, 1))]:
            columns = _find_date_columns(self.sheet(title), 2026)
            self.assertEqual((columns[0]["date"], columns[-1]["date"]), (start, end))

    def test_missing_range_or_year_is_not_guessed(self):
        for title in ["本周食谱", "2026年9月食谱", "9月7日—9月11日食谱"]:
            with self.subTest(title=title), self.assertRaises(RecipeImportError):
                _find_date_columns(self.sheet(title), 2026)

    def test_invalid_reversed_or_long_ranges(self):
        for title in ["2026年9月31日—10月2日食谱", "2026年9月11日—9月7日食谱", "2026年9月7日—9月18日食谱"]:
            with self.subTest(title=title), self.assertRaises(RecipeImportError):
                _find_date_columns(self.sheet(title), 2026)

    def test_duplicate_weekdays_rejected(self):
        with self.assertRaisesRegex(RecipeImportError, "重复"):
            _find_date_columns(self.sheet(headers=["星期一", "周一"]), 2026)

    def test_weekday_outside_range_rejected(self):
        with self.assertRaisesRegex(RecipeImportError, "范围"):
            _find_date_columns(self.sheet(headers=["星期六"]), 2026)

    def test_complete_parser_preserves_meals_and_amounts(self):
        sheet = self.sheet()
        stream = BytesIO()
        sheet.parent.save(stream)
        payload, warnings, summary = parse_recipe_workbook(stream.getvalue(), source_file="食谱.xlsx",
            import_id="a" * 32, agent_client=StructuredTaskClient())
        self.assertEqual(summary["day_count"], 5)
        self.assertEqual(summary["ingredient_count"], 5)
        self.assertEqual(payload["recipe"]["weekEnd"], "2026-09-11")
        for day in payload["days"]:
            row = day["portions"][0]["dishIngredientRows"][0]
            self.assertEqual((row["ingredient"], row["amount"], row["unit"]), ("牛奶", 125, "g"))


if __name__ == "__main__":
    unittest.main()
