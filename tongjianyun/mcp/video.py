from __future__ import annotations

import hashlib
import json
from typing import Any

ALLOWED_KINDS = {
	"cover",
	"context",
	"challenge",
	"solution",
	"capability",
	"roadmap",
	"value",
	"closing",
}
KIND_LABELS = {
	"cover": "开场",
	"context": "客户现状",
	"challenge": "核心痛点",
	"solution": "解决方案",
	"capability": "核心能力",
	"roadmap": "实施路径",
	"value": "预期价值",
	"closing": "结束",
}
LABEL_KINDS = {value: key for key, value in KIND_LABELS.items()}
ALLOWED_TEMPLATES = {"medical-enterprise", "enterprise"}
TEMPLATE_LABELS = {"medical-enterprise": "医疗企业", "enterprise": "通用企业"}
LABEL_TEMPLATES = {value: key for key, value in TEMPLATE_LABELS.items()}
ALLOWED_ASPECT_RATIOS = {"16:9", "9:16"}
MAX_SCENES = 12
MIN_SCENES = 6


def _text(value: Any, *, field: str, maximum: int, required: bool = False) -> str:
	text = " ".join(str(value or "").split())
	if required and not text:
		raise ValueError(f"{field} is required")
	if len(text) > maximum:
		raise ValueError(f"{field} must not exceed {maximum} characters")
	return text


def normalize_video_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
	if not isinstance(manifest, dict):
		raise ValueError("manifest must be an object")
	template = str(manifest.get("template") or "medical-enterprise").strip()
	template = LABEL_TEMPLATES.get(template, template)
	if template not in ALLOWED_TEMPLATES:
		raise ValueError(f"Unsupported video template: {template}")
	aspect_ratio = str(manifest.get("aspect_ratio") or "16:9").strip()
	if aspect_ratio not in ALLOWED_ASPECT_RATIOS:
		raise ValueError(f"Unsupported aspect ratio: {aspect_ratio}")
	scenes = manifest.get("scenes")
	if not isinstance(scenes, list) or len(scenes) < MIN_SCENES:
		raise ValueError(f"A promotional video requires at least {MIN_SCENES} scenes")
	if len(scenes) > MAX_SCENES:
		raise ValueError(f"A promotional video supports at most {MAX_SCENES} scenes")

	normalized_scenes = []
	for index, raw in enumerate(scenes, start=1):
		if not isinstance(raw, dict):
			raise ValueError(f"Scene {index} must be an object")
		kind = str(raw.get("kind") or "").strip()
		kind = LABEL_KINDS.get(kind, kind)
		if kind not in ALLOWED_KINDS:
			raise ValueError(f"Scene {index} has unsupported kind: {kind}")
		bullets = raw.get("bullets") or []
		if not isinstance(bullets, list) or len(bullets) > 6:
			raise ValueError(f"Scene {index} supports at most 6 bullets")
		duration = float(raw.get("duration_seconds") or 8)
		if duration < 3 or duration > 30:
			raise ValueError(f"Scene {index} duration must be between 3 and 30 seconds")
		asset_file = _text(
			raw.get("asset_file"), field=f"scenes[{index}].asset_file", maximum=180
		)
		if "://" in asset_file or asset_file.lower().startswith(("data:", "javascript:")):
			raise ValueError(f"Scene {index} asset must reference an attached Frappe File")
		normalized_scenes.append(
			{
				"code": f"scene-{index:02d}",
				"kind": kind,
				"title": _text(
					raw.get("title"), field=f"scenes[{index}].title", maximum=100, required=True
				),
				"subtitle": _text(
					raw.get("subtitle"), field=f"scenes[{index}].subtitle", maximum=220
				),
				"bullets": [
					_text(item, field=f"scenes[{index}].bullets", maximum=140, required=True)
					for item in bullets
				],
				"narration": _text(
					raw.get("narration"), field=f"scenes[{index}].narration", maximum=800
				),
				"duration_seconds": round(duration, 2),
				"asset_file": asset_file,
				"evidence": _text(
					raw.get("evidence"), field=f"scenes[{index}].evidence", maximum=500
				),
			}
		)
	if normalized_scenes[0]["kind"] != "cover":
		raise ValueError("The first scene must use the cover layout")
	if normalized_scenes[-1]["kind"] != "closing":
		raise ValueError("The last scene must use the closing layout")
	total_duration = round(sum(scene["duration_seconds"] for scene in normalized_scenes), 2)
	if total_duration < 30 or total_duration > 180:
		raise ValueError("Total video duration must be between 30 and 180 seconds")

	return {
		"schema_version": 1,
		"title": _text(manifest.get("title"), field="title", maximum=140, required=True),
		"customer": _text(manifest.get("customer"), field="customer", maximum=140),
		"brand": _text(manifest.get("brand") or "I-ONE AI", field="brand", maximum=80),
		"template": template,
		"aspect_ratio": aspect_ratio,
		"language": _text(manifest.get("language") or "zh-CN", field="language", maximum=16),
		"call_to_action": _text(
			manifest.get("call_to_action"), field="call_to_action", maximum=180
		),
		"duration_seconds": total_duration,
		"scenes": normalized_scenes,
	}


def manifest_hash(manifest: dict[str, Any], *source_values: Any) -> str:
	payload = {
		"manifest": normalize_video_manifest(manifest),
		"sources": [str(value or "") for value in source_values],
	}
	encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
	return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def manifest_from_video_document(doc) -> dict[str, Any]:
	template = LABEL_TEMPLATES.get(str(doc.template or ""), str(doc.template or ""))
	return normalize_video_manifest(
		{
			"title": doc.title,
			"customer": doc.customer,
			"brand": doc.brand or "I-ONE AI",
			"template": template or "medical-enterprise",
			"aspect_ratio": doc.aspect_ratio or "16:9",
			"language": doc.language or "zh-CN",
			"call_to_action": doc.call_to_action,
			"scenes": [
				{
					"kind": LABEL_KINDS.get(str(row.scene_type or ""), str(row.scene_type or "")),
					"title": row.title,
					"subtitle": row.subtitle,
					"bullets": [item.strip() for item in str(row.bullets or "").splitlines() if item.strip()],
					"narration": row.narration,
					"duration_seconds": row.duration_seconds,
					"asset_file": row.asset_file,
					"evidence": row.evidence,
				}
				for row in doc.scenes
			],
		}
	)
