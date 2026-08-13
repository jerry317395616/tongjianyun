from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile
import xml.etree.ElementTree as ET

from tongjianyun.recipe_analysis import analyze_recipe_payload, build_report_xlsx


def sample_payload() -> dict:
    return {
        "recipe": {"recipeId": "2026-W17", "title": "第十七周食谱", "weekStart": "2026-06-22", "weekEnd": "2026-06-26"},
        "days": [
            {
                "date": "2026-06-22",
                "portions": [
                    {"slot": "breakfast", "dishIngredientRows": [
                        {"ingredient": "纯牛奶", "amount": 200, "unit": "ml"},
                        {"ingredient": "鸡蛋", "amount": 50, "unit": "g"},
                        {"ingredient": "面粉", "amount": 40, "unit": "g"},
                    ]},
                    {"slot": "lunch", "dishIngredientRows": [
                        {"ingredient": "大米", "amount": 60, "unit": "g"},
                        {"ingredient": "西兰花", "amount": 80, "unit": "g"},
                        {"ingredient": "猪肉", "amount": 40, "unit": "g"},
                    ]},
                ],
            },
            {
                "date": "2026-06-23",
                "portions": [
                    {"slot": "breakfast", "dishIngredientRows": [{"ingredient": "小米", "amount": 40, "unit": "g"}]},
                    {"slot": "snack", "dishIngredientRows": [{"ingredient": "苹果", "amount": 100, "unit": "g"}]},
                ],
            },
        ],
    }


def _cell_text(xlsx: bytes, ref: str) -> str:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(BytesIO(xlsx)) as archive:
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    cell = root.find(f".//m:c[@r='{ref}']", ns)
    assert cell is not None
    return "".join(node.text or "" for node in cell.findall(".//m:t", ns)) or str((cell.find("m:v", ns).text if cell.find("m:v", ns) is not None else ""))


def _row_height(xlsx: bytes, row_number: int) -> float:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with ZipFile(BytesIO(xlsx)) as archive:
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    row = root.find(f".//m:row[@r='{row_number}']", ns)
    assert row is not None
    return float(row.attrib["ht"])


def test_analyzes_ingredient_weights_and_nutrients_deterministically() -> None:
    analysis = analyze_recipe_payload(sample_payload())
    ingredients = {item["name"]: item for item in analysis["ingredients"]}
    assert ingredients["纯牛奶"]["grams"] == 100
    assert ingredients["大米"]["grams"] == 30
    assert analysis["nutrients"]["energy"] > 0
    assert analysis["meal_ratio"]["breakfast"] > 0
    assert "临床诊断" in analysis["conclusion"]


def test_generates_template_preserving_xlsx_with_populated_analysis() -> None:
    analysis = analyze_recipe_payload(sample_payload())
    output = build_report_xlsx(analysis)
    assert output[:2] == b"PK"
    assert _cell_text(output, "B4").startswith("粮食类")
    assert _cell_text(output, "N26").startswith("食谱：第十七周食谱")
    assert "临床诊断" in _cell_text(output, "P32")
    with ZipFile(BytesIO(output)) as archive:
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    merges = {node.attrib["ref"] for node in root.findall(".//m:mergeCells/m:mergeCell", ns)}
    assert {"D2:M2", "P32:V37", "B4:B11"}.issubset(merges)


def test_report_food_names_come_only_from_current_recipe() -> None:
    output = build_report_xlsx(analyze_recipe_payload(sample_payload()))
    name_cells = [
        f"{column}{row}"
        for row in range(4, 38)
        for column in ("D", "F", "H", "J", "L")
    ]
    report_names = {_cell_text(output, ref) for ref in name_cells} - {""}
    assert report_names == {"纯牛奶", "鸡蛋", "面粉", "大米", "西兰花", "猪肉", "小米", "苹果"}
    assert "豆腐" not in report_names


def test_report_preserves_foods_when_category_exceeds_template_slots() -> None:
    payload = sample_payload()
    payload["days"][0]["portions"][0]["dishIngredientRows"] = [
        {"ingredient": f"测试蔬菜{index:02d}", "amount": index, "unit": "g"}
        for index in range(1, 27)
    ]

    output = build_report_xlsx(analyze_recipe_payload(payload))
    overflow_names = _cell_text(output, "L20").splitlines()
    overflow_weights = _cell_text(output, "M20").splitlines()

    assert overflow_names == ["测试蔬菜25", "测试蔬菜26"]
    assert overflow_weights == ["12.5", "13"]
    assert _row_height(output, 20) == 22
