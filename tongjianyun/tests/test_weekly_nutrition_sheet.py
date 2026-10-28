import unittest
from io import BytesIO

from openpyxl import load_workbook

from tongjianyun.weekly_nutrition_sheet import build_sheet_data, workbook_bytes


class WeeklyNutritionSheetTests(unittest.TestCase):
    def test_sample_preserves_volume_unknowns_and_per_child_basis(self):
        dates = [f"2026-06-{day:02}" for day in range(22, 27)]
        rows = [
            dict(
                meal_date=dates[0],
                meal_type="早餐",
                ingredient_code="RICE",
                ingredient_name="大米",
                uom="g",
                per_child_qty=50,
                headcount=257,
            ),
            dict(
                meal_date=dates[4],
                meal_type="午点",
                ingredient_code="SOUP",
                ingredient_name="绿豆银耳汤",
                uom="Millilitre",
                per_child_qty=150,
                headcount=257,
            ),
        ]
        data = build_sheet_data(
            rows, dates, {"week_start": dates[0], "plan_batch": "historic"}
        )
        items = {
            item["code"]: item for group in data["groups"] for item in group["items"]
        }
        self.assertEqual(items["RICE"]["daily"], "10")
        self.assertEqual(items["SOUP"]["daily"], "30")
        self.assertEqual(items["SOUP"]["unit"], "Millilitre")
        self.assertEqual(data["covered_rows"], 1)
        self.assertEqual(data["missing"][0]["code"], "SOUP")
        energy = next(item for item in data["nutrients"] if item["label"] == "能量")
        self.assertEqual(energy["amount"], 35)
        self.assertEqual((energy["covered_rows"], energy["total_rows"]), (1, 2))
        workbook = load_workbook(BytesIO(workbook_bytes(data)), data_only=False)
        values = [
            str(cell.value)
            for row in workbook.active
            for cell in row
            if cell.value is not None
        ]
        self.assertTrue(
            any(
                cell.value == 30 and "ml" in cell.number_format
                for row in workbook.active
                for cell in row
            )
        )
        self.assertTrue(any("实际摄入" in value for value in values))
        self.assertFalse(
            any(cell.data_type == "f" for row in workbook.active for cell in row)
        )

    def test_formula_like_ingredient_name_is_text_in_export(self):
        rows = [
            dict(
                meal_date="2026-06-22",
                meal_type="早餐",
                ingredient_code="X",
                ingredient_name="=1+1",
                uom="g",
                per_child_qty=1,
            )
        ]
        data = build_sheet_data(rows, ["2026-06-22"], {"week_start": "2026-06-22"})
        sheet = load_workbook(BytesIO(workbook_bytes(data)), data_only=False).active
        name = next(cell for row in sheet for cell in row if cell.value == "=1+1")
        self.assertEqual(name.data_type, "s")


if __name__ == "__main__":
    unittest.main()
