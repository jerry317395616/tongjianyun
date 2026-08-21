"""Official age- and sex-specific nutrition reference values.

The values below are transcribed from DB4403/T 489—2024, table 5.  Keeping
the table and the pure aggregation helpers together makes the calculation used
by the page, report and exported workbook identical and testable.
"""

from __future__ import annotations

from collections import Counter
from datetime import date
from typing import Any, Iterable


OFFICIAL_SOURCE = "DB4403/T 489—2024《0岁～6岁儿童营养配餐指南》"

REFERENCE_NUTRIENTS = (
	"energy",
	"protein",
	"calcium",
	"iron",
	"zinc",
	"vitamin_a",
	"vitamin_b1",
	"vitamin_b2",
	"vitamin_c",
)

# Table 5: 2–6-year-old children. Values that do not differ by sex are
# deliberately repeated so each student always resolves to one complete row.
FULL_DAY_REFERENCE: dict[str, dict[str, dict[str, float]]] = {
	"2": {
		"男": dict(energy=1100, protein=25, calcium=500, iron=10, zinc=4.0, vitamin_a=340, vitamin_b1=0.6, vitamin_b2=0.7, vitamin_c=40),
		"女": dict(energy=1000, protein=25, calcium=500, iron=10, zinc=4.0, vitamin_a=330, vitamin_b1=0.6, vitamin_b2=0.6, vitamin_c=40),
	},
	"3": {
		"男": dict(energy=1250, protein=30, calcium=500, iron=10, zinc=4.0, vitamin_a=340, vitamin_b1=0.6, vitamin_b2=0.7, vitamin_c=40),
		"女": dict(energy=1150, protein=30, calcium=500, iron=10, zinc=4.0, vitamin_a=330, vitamin_b1=0.6, vitamin_b2=0.6, vitamin_c=40),
	},
	"4": {
		"男": dict(energy=1300, protein=30, calcium=600, iron=10, zinc=5.5, vitamin_a=390, vitamin_b1=0.9, vitamin_b2=0.9, vitamin_c=50),
		"女": dict(energy=1250, protein=30, calcium=600, iron=10, zinc=5.5, vitamin_a=380, vitamin_b1=0.9, vitamin_b2=0.8, vitamin_c=50),
	},
	"5": {
		"男": dict(energy=1400, protein=30, calcium=600, iron=10, zinc=5.5, vitamin_a=390, vitamin_b1=0.9, vitamin_b2=0.9, vitamin_c=50),
		"女": dict(energy=1300, protein=30, calcium=600, iron=10, zinc=5.5, vitamin_a=380, vitamin_b1=0.9, vitamin_b2=0.8, vitamin_c=50),
	},
	"6": {
		"男": dict(energy=1600, protein=35, calcium=600, iron=10, zinc=5.5, vitamin_a=390, vitamin_b1=0.9, vitamin_b2=0.9, vitamin_c=50),
		"女": dict(energy=1450, protein=35, calcium=600, iron=10, zinc=5.5, vitamin_a=380, vitamin_b1=0.9, vitamin_b2=0.8, vitamin_c=50),
	},
}

GENDER_ALIASES = {
	"男": "男",
	"male": "男",
	"m": "男",
	"女": "女",
	"female": "女",
	"f": "女",
}


def normalize_gender(value: Any) -> str | None:
	"""Map Education's ``Male``/``Female`` values to the reference table."""
	return GENDER_ALIASES.get(str(value or "").strip().lower())


def completed_years(date_of_birth: date, reference_date: date) -> int:
	"""Return completed years of age on a deterministic report reference date."""
	return reference_date.year - date_of_birth.year - (
		(reference_date.month, reference_date.day) < (date_of_birth.month, date_of_birth.day)
	)


def standard_profile(age_group: str, gender: str) -> tuple[dict[str, float], str]:
	"""Return the legacy manual-estimation profile for users without roster data."""
	ages = ["4", "5"] if age_group == "4–5岁平均" else ["4" if str(age_group).startswith("4") else "5"]
	genders = ["男", "女"] if gender == "男女平均" else [gender if gender in {"男", "女"} else "男"]
	selected = [FULL_DAY_REFERENCE[age][selected_gender] for age in ages for selected_gender in genders]
	standard = {
		key: sum(float(item[key]) for item in selected) / len(selected)
		for key in REFERENCE_NUTRIENTS
	}
	return standard, f"手动估算·{age_group}·{gender}"


def weighted_standard(population: Iterable[dict[str, Any]]) -> tuple[dict[str, float], dict[str, int]]:
	"""Average the official reference value of every supplied student.

	Each population row must contain a completed age in ``age`` and a normalized
	sex in ``gender``. Invalid rows are rejected by the Frappe integration before
	calling this helper.
	"""
	rows = list(population)
	if not rows:
		raise ValueError("没有可用于计算营养标准的学生。")

	totals = {key: 0.0 for key in REFERENCE_NUTRIENTS}
	composition: Counter[str] = Counter()
	for row in rows:
		age = str(row["age"])
		gender = str(row["gender"])
		values = FULL_DAY_REFERENCE[age][gender]
		for key in REFERENCE_NUTRIENTS:
			totals[key] += float(values[key])
		composition[f"{age}岁{gender}"] += 1

	student_count = len(rows)
	return (
		{key: value / student_count for key, value in totals.items()},
		dict(sorted(composition.items(), key=lambda item: (int(item[0][0]), item[0]))),
	)
