from __future__ import annotations

import csv
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

TranslationKey = tuple[str, str]


def read_translation_catalog(path: str | Path | None = None) -> dict[TranslationKey, str]:
	"""Read the packaged Frappe CSV catalog keyed by source text and context."""
	core_path = Path(__file__).with_name("translations") / "zh.csv"
	catalog_path = Path(path) if path else core_path
	catalog: dict[TranslationKey, str] = {}
	with catalog_path.open(encoding="utf-8-sig", newline="") as handle:
		for line_number, row in enumerate(csv.reader(handle), start=1):
			if not row:
				continue
			if len(row) not in {2, 3}:
				raise ValueError(f"invalid translation row {line_number}: expected 2 or 3 columns")
			source = row[0].replace("\\n", "\n")
			translated = row[1].replace("\\n", "\n")
			context = row[2].strip() if len(row) == 3 else ""
			if not source or not translated:
				raise ValueError(
					f"invalid translation row {line_number}: source and translation are required"
				)
			catalog[(source, context)] = translated
	return catalog


def write_translation_catalog(
	catalog: Mapping[TranslationKey, str],
	path: str | Path | None = None,
) -> Path:
	"""Write a portable Frappe translation catalog while preserving mapping order."""
	core_path = Path(__file__).with_name("translations") / "zh.csv"
	catalog_path = Path(path) if path else core_path
	catalog_path.parent.mkdir(parents=True, exist_ok=True)
	with catalog_path.open("w", encoding="utf-8", newline="") as handle:
		writer = csv.writer(handle, lineterminator="\n")
		for (source, context), translated in catalog.items():
			row = [source.replace("\n", "\\n"), translated.replace("\n", "\\n")]
			if context:
				row.append(context)
			writer.writerow(row)
	return catalog_path


def merge_site_translations(
	catalog: Mapping[TranslationKey, str],
	rows: Iterable[Any],
	*,
	overwrite: bool = False,
) -> tuple[dict[TranslationKey, str], dict[str, int]]:
	"""Append site translations without replacing curated packaged values by default."""
	merged = dict(catalog)
	site_catalog: dict[TranslationKey, str] = {}
	for row in rows:
		source = _normalize_catalog_text(_row_value(row, "source_text"))
		translated = _normalize_catalog_text(_row_value(row, "translated_text"))
		context = str(_row_value(row, "context") or "").strip()
		if source and translated:
			site_catalog[(source, context)] = translated

	added = 0
	overwritten = 0
	for key in sorted(site_catalog):
		if key not in merged:
			merged[key] = site_catalog[key]
			added += 1
		elif overwrite and merged[key] != site_catalog[key]:
			merged[key] = site_catalog[key]
			overwritten += 1

	return merged, {
		"site_unique": len(site_catalog),
		"added": added,
		"overwritten": overwritten,
	}


def export_site_translation_catalog(
	language: str = "zh",
	path: str | Path | None = None,
	overwrite: bool = False,
) -> dict[str, int | str]:
	"""Append site-level translations to the packaged application catalog."""
	import frappe

	catalog = read_translation_catalog(path)
	packaged = len(catalog)
	rows = frappe.get_all(
		"Translation",
		filters={"language": language},
		fields=["source_text", "translated_text", "context", "creation", "name"],
		order_by="creation asc, name asc",
		limit_page_length=0,
	)
	catalog, stats = merge_site_translations(catalog, rows, overwrite=overwrite)

	output = write_translation_catalog(catalog, path)
	return {
		"packaged": packaged,
		"site_rows": len(rows),
		**stats,
		"exported": len(catalog),
		"path": str(output),
	}


def build_translation_sync_plan(
	catalog: Mapping[TranslationKey, str],
	existing_rows: Iterable[Any],
) -> dict[str, list[Any]]:
	"""Build an idempotent plan and collapse duplicate site overrides."""
	grouped: dict[TranslationKey, list[Any]] = defaultdict(list)
	for row in existing_rows:
		key = (
			_normalize_catalog_text(_row_value(row, "source_text")),
			str(_row_value(row, "context") or "").strip(),
		)
		if key in catalog:
			grouped[key].append(row)

	inserts: list[tuple[TranslationKey, str]] = []
	updates: list[tuple[str, str]] = []
	duplicates: list[str] = []
	for key, translated in catalog.items():
		rows = sorted(
			grouped.get(key, ()),
			key=lambda row: (
				str(_row_value(row, "source_text") or "") != key[0],
				str(_row_value(row, "creation") or ""),
				str(_row_value(row, "name") or ""),
			),
		)
		if not rows:
			inserts.append((key, translated))
			continue
		keeper = rows[0]
		if str(_row_value(keeper, "translated_text") or "") != translated:
			updates.append((str(_row_value(keeper, "name")), translated))
		duplicates.extend(str(_row_value(row, "name")) for row in rows[1:])

	return {"inserts": inserts, "updates": updates, "duplicates": duplicates}


def sync_translation_overrides(language: str = "zh") -> dict[str, int]:
	"""Synchronize packaged translations as deterministic site-level overrides."""
	import frappe
	from frappe.core.doctype.translation.translation import clear_user_translation_cache
	from frappe.utils import now_datetime

	if not frappe.db.exists("DocType", "Translation"):
		return {"catalog": 0, "inserted": 0, "updated": 0, "duplicates_removed": 0}

	# This catalog is trusted application data. Preserve literal technical tags such as
	# <head> and <agent_memory>, which Frappe's HTML sanitizer would otherwise remove.
	catalog = read_translation_catalog()
	existing = frappe.get_all(
		"Translation",
		filters={"language": language},
		fields=["name", "source_text", "translated_text", "context", "creation"],
		limit_page_length=0,
	)
	plan = build_translation_sync_plan(catalog, existing)

	for name, translated in plan["updates"]:
		frappe.db.set_value(
			"Translation",
			name,
			"translated_text",
			translated,
			update_modified=False,
		)

	if plan["duplicates"]:
		frappe.db.delete("Translation", {"name": ["in", plan["duplicates"]]})

	now = now_datetime()
	insert_rows = []
	for (source, context), translated in plan["inserts"]:
		insert_rows.append(
			(
				frappe.generate_hash(length=16),
				"Administrator",
				now,
				now,
				"Administrator",
				0,
				0,
				language,
				source,
				translated,
				context or None,
				0,
			)
		)
	if insert_rows:
		frappe.db.bulk_insert(
			"Translation",
			fields=[
				"name",
				"owner",
				"creation",
				"modified",
				"modified_by",
				"docstatus",
				"idx",
				"language",
				"source_text",
				"translated_text",
				"context",
				"contributed",
			],
			values=insert_rows,
			ignore_duplicates=True,
			chunk_size=1000,
		)

	if insert_rows or plan["updates"] or plan["duplicates"]:
		clear_user_translation_cache(language)
		frappe.clear_cache()

	return {
		"catalog": len(catalog),
		"inserted": len(insert_rows),
		"updated": len(plan["updates"]),
		"duplicates_removed": len(plan["duplicates"]),
	}


def _row_value(row: Any, fieldname: str) -> Any:
	if isinstance(row, Mapping):
		return row.get(fieldname)
	return getattr(row, fieldname, None)


def _normalize_catalog_text(value: Any) -> str:
	return str(value or "").replace("\\n", "\n")
