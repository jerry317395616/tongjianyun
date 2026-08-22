from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
import math
from typing import Any, Mapping, Sequence


DEFAULT_FORMULA = "per_100g * grams / 100 / day_count * edible_ratio * retention_rate"
FORMULA_VARIABLES = frozenset(
    {"per_100g", "grams", "day_count", "edible_ratio", "retention_rate"}
)
NUTRIENT_KEYS = (
    "energy",
    "protein",
    "fat",
    "carbohydrate",
    "calcium",
    "vitamin_a",
    "vitamin_b1",
    "vitamin_b2",
    "vitamin_c",
    "vitamin_e",
    "niacin",
    "potassium",
    "magnesium",
    "iron",
    "zinc",
    "phosphorus",
    "selenium",
    "carotene",
    "fiber",
    "cholesterol",
)
NUTRIENT_UNITS = {
    "energy": "kcal",
    "protein": "g",
    "fat": "g",
    "carbohydrate": "g",
    "calcium": "mg",
    "vitamin_a": "μg RAE",
    "vitamin_b1": "mg",
    "vitamin_b2": "mg",
    "vitamin_c": "mg",
    "vitamin_e": "mg α-TE",
    "niacin": "mg NE",
    "potassium": "mg",
    "magnesium": "mg",
    "iron": "mg",
    "zinc": "mg",
    "phosphorus": "mg",
    "selenium": "μg",
    "carotene": "μg",
    "fiber": "g",
    "cholesterol": "mg",
}

_MAX_FORMULA_LENGTH = 300
_MAX_AST_NODES = 64
_BINARY_OPERATORS = {
    ast.Add: lambda left, right: left + right,
    ast.Sub: lambda left, right: left - right,
    ast.Mult: lambda left, right: left * right,
    ast.Div: lambda left, right: left / right,
}
_UNARY_OPERATORS = {
    ast.UAdd: lambda value: value,
    ast.USub: lambda value: -value,
}


class NutritionFormulaError(ValueError):
    """A formula is invalid or cannot be evaluated safely."""


def default_rule_set() -> dict[str, Any]:
    return {
        "rule_code": "DEFAULT-V1",
        "title": "默认营养计算规则 V1",
        "version": "1.0",
        "status": "系统默认",
        "source": "童健云内置规则",
        "rules": {
            key: {
                "nutrient": key,
                "unit": NUTRIENT_UNITS[key],
                "formula": DEFAULT_FORMULA,
                "edible_ratio": 1.0,
                "retention_rate": 1.0,
                "lower_percent": 90.0 if key == "energy" else 80.0,
                "upper_percent": 110.0
                if key == "energy"
                else (120.0 if key == "protein" else None),
                "enabled": True,
            }
            for key in NUTRIENT_KEYS
        },
        "macro_factors": {"carbohydrate": 4.0, "fat": 9.0, "protein": 4.0},
        "macro_ranges": {
            "carbohydrate": [50.0, 65.0],
            "fat": [20.0, 30.0],
            "protein": [10.0, 20.0],
        },
        "animal_protein_target": 30.0,
        "animal_soy_protein_target": 50.0,
    }


def validate_formula(formula: str) -> str:
    expression = str(formula or "").strip()
    if not expression:
        raise NutritionFormulaError("计算公式不能为空")
    if len(expression) > _MAX_FORMULA_LENGTH:
        raise NutritionFormulaError(f"计算公式不能超过 {_MAX_FORMULA_LENGTH} 个字符")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise NutritionFormulaError(f"计算公式语法错误：{exc.msg}") from exc

    nodes = list(ast.walk(tree))
    if len(nodes) > _MAX_AST_NODES:
        raise NutritionFormulaError("计算公式过于复杂")

    allowed_nodes = (
        ast.Expression,
        ast.BinOp,
        ast.UnaryOp,
        ast.Constant,
        ast.Name,
        ast.Load,
        ast.Call,
        *tuple(_BINARY_OPERATORS),
        *tuple(_UNARY_OPERATORS),
    )
    for node in nodes:
        if not isinstance(node, allowed_nodes):
            raise NutritionFormulaError(
                f"计算公式包含不允许的语法：{type(node).__name__}"
            )
        if isinstance(node, ast.Name) and node.id not in FORMULA_VARIABLES | {
            "min",
            "max",
            "abs",
            "round",
        }:
            raise NutritionFormulaError(f"计算公式使用了不允许的变量：{node.id}")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in {
                "min",
                "max",
                "abs",
                "round",
            }:
                raise NutritionFormulaError("计算公式只能调用 min、max、abs 或 round")
            if node.keywords:
                raise NutritionFormulaError("计算函数不支持命名参数")
    return expression


def evaluate_formula(formula: str, variables: Mapping[str, float]) -> float:
    expression = validate_formula(formula)
    missing = FORMULA_VARIABLES.difference(variables)
    if missing:
        raise NutritionFormulaError(f"计算公式缺少变量：{', '.join(sorted(missing))}")
    context = {key: _finite_number(variables[key], key) for key in FORMULA_VARIABLES}
    try:
        result = _evaluate_node(ast.parse(expression, mode="eval").body, context)
    except ZeroDivisionError as exc:
        raise NutritionFormulaError("计算公式发生除零错误") from exc
    except (OverflowError, ValueError) as exc:
        raise NutritionFormulaError(f"计算公式无法得到有效数值：{exc}") from exc
    return _finite_number(result, "计算结果")


def _evaluate_node(node: ast.AST, context: Mapping[str, float]) -> float:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in FORMULA_VARIABLES:
        return context[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        return _BINARY_OPERATORS[type(node.op)](
            _evaluate_node(node.left, context),
            _evaluate_node(node.right, context),
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        return _UNARY_OPERATORS[type(node.op)](_evaluate_node(node.operand, context))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        args = [_evaluate_node(argument, context) for argument in node.args]
        if node.func.id == "min" and args:
            return min(args)
        if node.func.id == "max" and args:
            return max(args)
        if node.func.id == "abs" and len(args) == 1:
            return abs(args[0])
        if node.func.id == "round" and len(args) in {1, 2}:
            digits = int(args[1]) if len(args) == 2 else 0
            if len(args) == 2 and args[1] != digits:
                raise NutritionFormulaError("round 的小数位数必须是整数")
            if not -12 <= digits <= 12:
                raise NutritionFormulaError("round 的小数位数必须在 -12 到 12 之间")
            return round(args[0], digits)
    raise NutritionFormulaError(f"计算公式包含不允许的表达式：{type(node).__name__}")


def normalize_rule_set(value: Mapping[str, Any] | None) -> dict[str, Any]:
    result = default_rule_set()
    if not value:
        result["rule_hash"] = rule_set_hash(result)
        return result

    for key in (
        "rule_code",
        "title",
        "version",
        "status",
        "source",
        "animal_protein_target",
        "animal_soy_protein_target",
    ):
        if key in value and value[key] is not None:
            result[key] = deepcopy(value[key])

    for group in ("macro_factors", "macro_ranges"):
        supplied = value.get(group)
        if isinstance(supplied, Mapping):
            result[group].update(deepcopy(dict(supplied)))

    supplied_rules = value.get("rules")
    rows: Sequence[Mapping[str, Any]]
    if isinstance(supplied_rules, Mapping):
        rows = [dict(row, nutrient=key) for key, row in supplied_rules.items()]
    elif isinstance(supplied_rules, Sequence) and not isinstance(
        supplied_rules, (str, bytes)
    ):
        rows = supplied_rules
    else:
        rows = []

    seen: set[str] = set()
    for supplied_row in rows:
        row = dict(supplied_row)
        nutrient = str(row.get("nutrient") or "").strip()
        if nutrient not in NUTRIENT_KEYS:
            raise NutritionFormulaError(f"不支持的营养指标：{nutrient or '空值'}")
        if nutrient in seen:
            raise NutritionFormulaError(f"营养指标重复：{nutrient}")
        seen.add(nutrient)
        current = result["rules"][nutrient]
        for key in (
            "unit",
            "formula",
            "edible_ratio",
            "retention_rate",
            "lower_percent",
            "upper_percent",
            "enabled",
        ):
            if key in row and row[key] is not None:
                current[key] = row[key]

    _validate_rule_set(result)
    result["rule_hash"] = rule_set_hash(result)
    return result


def _validate_rule_set(rule_set: dict[str, Any]) -> None:
    for nutrient, row in rule_set["rules"].items():
        row["formula"] = validate_formula(str(row.get("formula") or ""))
        row["edible_ratio"] = _bounded_ratio(
            row.get("edible_ratio", 1), f"{nutrient} 可食部比例"
        )
        row["retention_rate"] = _bounded_ratio(
            row.get("retention_rate", 1), f"{nutrient} 保留率"
        )
        row["lower_percent"] = _finite_number(
            row.get("lower_percent", 80), f"{nutrient} 下限"
        )
        upper = row.get("upper_percent")
        row["upper_percent"] = (
            None
            if upper in (None, "", 0, 0.0)
            else _finite_number(upper, f"{nutrient} 上限")
        )
        row["enabled"] = bool(row.get("enabled", True))
        if row["lower_percent"] < 0:
            raise NutritionFormulaError(f"{nutrient} 下限不能小于 0")
        if (
            row["upper_percent"] is not None
            and row["upper_percent"] <= row["lower_percent"]
        ):
            raise NutritionFormulaError(f"{nutrient} 上限必须大于下限")

    for nutrient, factor in rule_set["macro_factors"].items():
        rule_set["macro_factors"][nutrient] = _finite_number(
            factor, f"{nutrient} 供能系数"
        )
    for nutrient, limits in rule_set["macro_ranges"].items():
        if not isinstance(limits, (list, tuple)) or len(limits) != 2:
            raise NutritionFormulaError(f"{nutrient} 供能比范围必须包含下限和上限")
        low = _finite_number(limits[0], f"{nutrient} 供能比下限")
        high = _finite_number(limits[1], f"{nutrient} 供能比上限")
        if low < 0 or high <= low:
            raise NutritionFormulaError(f"{nutrient} 供能比范围无效")
        rule_set["macro_ranges"][nutrient] = [low, high]
    for key in ("animal_protein_target", "animal_soy_protein_target"):
        rule_set[key] = _finite_number(rule_set[key], key)


def calculate_nutrient_value(
    nutrient: str,
    *,
    per_100g: float,
    grams: float,
    day_count: int,
    rule_set: Mapping[str, Any] | None = None,
) -> float:
    rules = (
        rule_set
        if isinstance(rule_set, Mapping)
        and rule_set.get("rule_hash")
        and isinstance(rule_set.get("rules"), Mapping)
        else normalize_rule_set(rule_set)
    )
    row = rules["rules"].get(nutrient)
    if not row or not row["enabled"]:
        return 0.0
    return evaluate_formula(
        row["formula"],
        {
            "per_100g": per_100g,
            "grams": grams,
            "day_count": day_count,
            "edible_ratio": row["edible_ratio"],
            "retention_rate": row["retention_rate"],
        },
    )


def evaluate_nutrient(
    nutrient: str, percent: float, rule_set: Mapping[str, Any] | None = None
) -> str:
    rules = normalize_rule_set(rule_set)
    row = rules["rules"].get(nutrient) or rules["rules"]["energy"]
    current = _finite_number(percent, "达标率")
    if current < row["lower_percent"]:
        return "偏低"
    if row["upper_percent"] is not None and current > row["upper_percent"]:
        return "偏高"
    return "适宜"


def public_rule_metadata(rule_set: Mapping[str, Any] | None) -> dict[str, Any]:
    rules = normalize_rule_set(rule_set)
    return {
        "rule_code": rules["rule_code"],
        "title": rules["title"],
        "version": rules["version"],
        "status": rules["status"],
        "source": rules["source"],
        "rule_hash": rules["rule_hash"],
        "evaluation_rules": {
            key: {
                "lower_percent": row["lower_percent"],
                "upper_percent": row["upper_percent"],
            }
            for key, row in rules["rules"].items()
        },
        "macro_factors": deepcopy(rules["macro_factors"]),
        "macro_ranges": deepcopy(rules["macro_ranges"]),
        "animal_protein_target": rules["animal_protein_target"],
        "animal_soy_protein_target": rules["animal_soy_protein_target"],
    }


def rule_set_hash(rule_set: Mapping[str, Any]) -> str:
    payload = {
        "rules": rule_set.get("rules"),
        "macro_factors": rule_set.get("macro_factors"),
        "macro_ranges": rule_set.get("macro_ranges"),
        "animal_protein_target": rule_set.get("animal_protein_target"),
        "animal_soy_protein_target": rule_set.get("animal_soy_protein_target"),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _bounded_ratio(value: Any, label: str) -> float:
    number = _finite_number(value, label)
    if not 0 <= number <= 1:
        raise NutritionFormulaError(f"{label}必须在 0 到 1 之间")
    return number


def _finite_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise NutritionFormulaError(f"{label}必须是数字") from exc
    if not math.isfinite(number):
        raise NutritionFormulaError(f"{label}必须是有限数字")
    return number
