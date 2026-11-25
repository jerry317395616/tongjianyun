from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

MONTH_NUMBERS = {
	"Jan": 1,
	"Feb": 2,
	"Mar": 3,
	"Apr": 4,
	"May": 5,
	"Jun": 6,
	"Jul": 7,
	"Aug": 8,
	"Sep": 9,
	"Oct": 10,
	"Nov": 11,
	"Dec": 12,
}

MONTH_LABEL = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})$")
QUARTER_LABEL = re.compile(r"^Quarter\s+([1-4])\s+(\d{4})$")


def localize_period_label(label: Any, language: str | None) -> Any:
	if not isinstance(label, str) or not _is_chinese(language):
		return label

	if match := MONTH_LABEL.fullmatch(label):
		month, year = match.groups()
		return f"{year}年{MONTH_NUMBERS[month]}月"

	if match := QUARTER_LABEL.fullmatch(label):
		quarter, year = match.groups()
		return f"{year}年第{quarter}季度"

	return label


def localize_chart_config(config: Any, language: str | None) -> Any:
	if not config or not _is_chinese(language):
		return config

	labels = config.get("labels") if hasattr(config, "get") else None
	if not isinstance(labels, list):
		return config

	localized = deepcopy(config)
	localized["labels"] = [localize_period_label(label, language) for label in labels]
	return localized


def _is_chinese(language: str | None) -> bool:
	return bool(language and language.lower().replace("-", "_").split("_", 1)[0] == "zh")
