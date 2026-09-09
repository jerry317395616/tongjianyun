"""Synthetic classification only. No Frappe connection or business writes."""
import json
import asyncio
from tongjianyun.codex_ingredient_client import CodexIngredientClient

def run():
    ingredients = [{"key": str(i), "ingredient": name, "unit": "g"}
                   for i, name in enumerate(["大米", "青椒", "鸡蛋", "骨汤"])]
    groups = [{"name": "所有物料组", "is_group": 1, "parent_item_group": None},
              {"name": "粮油及主食", "is_group": 0, "parent_item_group": "所有物料组"},
              {"name": "蔬菜", "is_group": 0, "parent_item_group": "所有物料组"},
              {"name": "蛋类", "is_group": 0, "parent_item_group": "所有物料组"}]
    raw = asyncio.run(CodexIngredientClient()._bounded(json.dumps({"ingredients": ingredients, "groups": groups}, ensure_ascii=False)))
    from tongjianyun.ingredient_classification import validate_proposals
    result = {"rows": validate_proposals(raw, ingredients, groups)}
    assert len(result["rows"]) == 4
    assert result["rows"][3]["action"] == "review"
    print(json.dumps({"validated": len(result["rows"]), "business_writes": 0, "result": result}, ensure_ascii=False))

if __name__ == "__main__":
    run()
