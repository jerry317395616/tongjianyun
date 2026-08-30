"""Resolve the real class roster used by a weekly nutrition analysis."""

from __future__ import annotations

from datetime import date
from typing import Any

import frappe
from frappe.utils import getdate

from tongjianyun.nutrition_standards import (
	FULL_DAY_REFERENCE,
	OFFICIAL_SOURCE,
	completed_years,
	normalize_gender,
	weighted_standard,
)


RECIPE_DOCTYPE = "Tongjianyun Recipe"
AUTO_MODE = "自动（按学生档案）"
MANUAL_MODE = "手动估算"
SNAPSHOT_VERSION = 1


class PopulationDataError(frappe.ValidationError):
	"""Raised when a roster cannot safely produce a nutrition standard."""


def parse_student_groups(value: Any) -> list[str]:
	"""Accept a Frappe MultiSelectList value, JSON string, or normal list."""
	if not value:
		return []
	if isinstance(value, str):
		try:
			value = frappe.parse_json(value)
		except (TypeError, ValueError):
			value = [item.strip() for item in value.split(",") if item.strip()]
	if not isinstance(value, (list, tuple, set)):
		return []
	return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


def _allowed_groups(requested_groups: Any = None) -> list[dict[str, str]]:
	frappe.has_permission("Student Group", "read", throw=True)
	filters: dict[str, Any] = {"disabled": 0}
	requested = parse_student_groups(requested_groups)
	if requested:
		filters["name"] = ["in", requested]
	groups = frappe.get_list(
		"Student Group",
		filters=filters,
		fields=["name", "student_group_name"],
		order_by="student_group_name asc, name asc",
		limit_page_length=0,
	)
	if not groups:
		frappe.throw("未找到可统计的启用班级，请检查统计班级筛选和权限。")
	return [dict(group) for group in groups]


def _population_rows(
	groups: list[dict[str, str]],
	*,
	include_all_enabled_students: bool = False,
) -> list[dict[str, Any]]:
	frappe.has_permission("Student", "read", throw=True)
	if include_all_enabled_students:
		students = frappe.get_list(
			"Student",
			filters={"enabled": 1},
			fields=["name", "gender", "date_of_birth"],
			order_by="name asc",
			limit_page_length=0,
		)
		if not students:
			frappe.throw("当前没有启用学生，无法计算营养标准。")
		return [dict(row) for row in students]

	group_names = [group["name"] for group in groups]
	memberships = frappe.get_all(
		"Student Group Student",
		filters={
			"parent": ["in", group_names],
			"parenttype": "Student Group",
			"active": 1,
		},
		fields=["student"],
		limit_page_length=0,
	)
	student_names = sorted({str(row.student) for row in memberships if row.student})
	if not student_names:
		frappe.throw("所选班级暂无启用学生，无法计算营养标准。")
	return [
		dict(row)
		for row in frappe.get_list(
			"Student",
			filters={"name": ["in", student_names], "enabled": 1},
			fields=["name", "gender", "date_of_birth"],
			order_by="name asc",
			limit_page_length=0,
		)
	]


def _reference_date(recipe) -> date:
	if not recipe.week_start:
		frappe.throw("食谱未设置开始日期，无法按学生年龄计算营养标准。")
	return getdate(recipe.week_start)


def _quality_error(total: int, missing_birth: int, missing_gender: int) -> None:
	problems = []
	if missing_birth:
		problems.append(f"出生日期缺失 {missing_birth} 人")
	if missing_gender:
		problems.append(f"性别缺失或无法识别 {missing_gender} 人")
	if problems:
		raise PopulationDataError(
			f"自动营养标准需要完整的学生档案：统计到 {total} 名学生，"
			f"{'；'.join(problems)}。请补全学生档案，或切换为“手动估算”。"
		)


def build_population_standard(recipe, student_groups: Any = None) -> dict[str, Any]:
	"""Build a full-day standard by averaging every student's official row."""
	requested_groups = parse_student_groups(student_groups)
	groups = _allowed_groups(requested_groups) if requested_groups else []
	students = _population_rows(groups, include_all_enabled_students=not requested_groups)
	reference_date = _reference_date(recipe)
	valid_population: list[dict[str, Any]] = []
	missing_birth = 0
	missing_gender = 0
	unsupported_ages: dict[int, int] = {}

	for student in students:
		date_of_birth = student.get("date_of_birth")
		if not date_of_birth:
			missing_birth += 1
			continue
		gender = normalize_gender(student.get("gender"))
		if not gender:
			missing_gender += 1
			continue
		age = completed_years(getdate(date_of_birth), reference_date)
		if str(age) not in FULL_DAY_REFERENCE:
			unsupported_ages[age] = unsupported_ages.get(age, 0) + 1
			continue
		valid_population.append({"age": age, "gender": gender})

	_quality_error(len(students), missing_birth, missing_gender)
	if not valid_population:
		ages = "、".join(f"{age}岁 {count}人" for age, count in sorted(unsupported_ages.items()))
		raise PopulationDataError(
			"自动营养标准没有可用学生：当前官方参考表覆盖 2–6 岁，"
			f"统计到的学生均不在可计算范围（{ages or '年龄不适用'}）。"
			"请检查学生档案或切换为“手动估算”。"
		)
	standard, composition = weighted_standard(valid_population)
	group_labels = [group.get("student_group_name") or group["name"] for group in groups]
	scope_label = f"{len(group_labels)}个班级" if requested_groups else "全园启用学生"
	if not group_labels:
		group_labels = ["全园启用学生"]
	composition_rows = [{"label": label, "count": count} for label, count in composition.items()]
	composition_text = "、".join(f"{label}×{count}" for label, count in composition.items())
	excluded_count = sum(unsupported_ages.values())
	warnings = []
	if excluded_count:
		ages = "、".join(f"{age}岁 {count}人" for age, count in sorted(unsupported_ages.items()))
		warnings.append(
			f"已排除标准表未覆盖的学生：{ages}；全日标准按其余 {len(valid_population)} 名学生逐名平均。"
		)
	return {
		"values": standard,
		"profile": f"自动计算·{scope_label}·{len(valid_population)}名学生",
		"source": OFFICIAL_SOURCE,
		"population": {
			"reference_date": str(reference_date),
			"student_count": len(valid_population),
			"source_student_count": len(students),
			"excluded_student_count": excluded_count,
			"excluded_age_counts": [
				{"age": age, "count": count} for age, count in sorted(unsupported_ages.items())
			],
			"warnings": warnings,
			"group_count": len(groups),
			"scope": scope_label,
			"groups": group_labels,
			"group_labels": group_labels,
			"composition": composition_rows,
			"composition_text": composition_text,
			"calculation": "逐名按食谱开始日年龄及性别取推荐值后平均",
		},
	}


def snapshot_key(student_groups: Any = None) -> str:
	groups = parse_student_groups(student_groups)
	return ",".join(sorted(groups)) if groups else "__all_enabled_students__"


def read_snapshot(recipe, student_groups: Any = None) -> dict[str, Any] | None:
	"""Read a frozen standard matching the selected class scope, if any."""
	raw = recipe.get("nutrition_population_snapshots")
	if not raw:
		return None
	try:
		payload = frappe.parse_json(raw)
	except (TypeError, ValueError):
		return None
	entry = payload.get(snapshot_key(student_groups)) if isinstance(payload, dict) else None
	if not isinstance(entry, dict) or entry.get("version") != SNAPSHOT_VERSION:
		return None
	return entry


def freeze_snapshot(recipe, calculated: dict[str, Any], student_groups: Any = None) -> None:
	"""Save an immutable population and reference-value snapshot on the recipe."""
	raw = recipe.get("nutrition_population_snapshots") or "{}"
	try:
		snapshots = frappe.parse_json(raw)
	except (TypeError, ValueError):
		snapshots = {}
	if not isinstance(snapshots, dict):
		snapshots = {}
	snapshots[snapshot_key(student_groups)] = {
		"version": SNAPSHOT_VERSION,
		"values": calculated["values"],
		"profile": calculated["profile"],
		"source": calculated["source"],
		"population": calculated["population"],
	}
	recipe.db_set("nutrition_population_snapshots", frappe.as_json(snapshots), update_modified=False)
