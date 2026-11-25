from __future__ import annotations

import html
import json
import secrets
from typing import Any

SLIDE_WIDTH = 960
SLIDE_HEIGHT = 540
MAX_SLIDES = 20
MAX_BULLETS = 6
MAX_METRICS = 4
ALLOWED_KINDS = {"cover", "section", "content", "metrics", "timeline", "closing"}

COLORS = {
	"ink": "#101828FF",
	"muted": "#667085FF",
	"brand": "#2457E6FF",
	"teal": "#0E9384FF",
	"amber": "#F79009FF",
	"surface": "#F7F9FCFF",
	"white": "#FFFFFFFF",
	"line": "#D0D5DDFF",
	"dark": "#0B1220FF",
}


def _clean_text(value: Any, *, field: str, maximum: int, required: bool = False) -> str:
	text = " ".join(str(value or "").split())
	if required and not text:
		raise ValueError(f"{field} is required")
	if len(text) > maximum:
		raise ValueError(f"{field} must not exceed {maximum} characters")
	return text


def normalize_slide_specs(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
	if not isinstance(slides, list) or len(slides) < 4:
		raise ValueError("A customer presentation requires at least 4 slides")
	if len(slides) > MAX_SLIDES:
		raise ValueError(f"A customer presentation supports at most {MAX_SLIDES} slides")

	normalized = []
	for index, raw in enumerate(slides, start=1):
		if not isinstance(raw, dict):
			raise ValueError(f"Slide {index} must be an object")
		kind = _clean_text(raw.get("kind") or "content", field=f"slides[{index}].kind", maximum=20)
		if kind not in ALLOWED_KINDS:
			raise ValueError(f"Slide {index} has unsupported kind: {kind}")
		bullets = raw.get("bullets") or []
		metrics = raw.get("metrics") or []
		if not isinstance(bullets, list) or len(bullets) > MAX_BULLETS:
			raise ValueError(f"Slide {index} supports at most {MAX_BULLETS} bullets")
		if not isinstance(metrics, list) or len(metrics) > MAX_METRICS:
			raise ValueError(f"Slide {index} supports at most {MAX_METRICS} metrics")

		clean_metrics = []
		for metric_index, metric in enumerate(metrics, start=1):
			if not isinstance(metric, dict):
				raise ValueError(f"Slide {index} metric {metric_index} must be an object")
			clean_metrics.append(
				{
					"value": _clean_text(
						metric.get("value"),
						field=f"slides[{index}].metrics[{metric_index}].value",
						maximum=28,
						required=True,
					),
					"label": _clean_text(
						metric.get("label"),
						field=f"slides[{index}].metrics[{metric_index}].label",
						maximum=36,
						required=True,
					),
					"detail": _clean_text(
						metric.get("detail"),
						field=f"slides[{index}].metrics[{metric_index}].detail",
						maximum=80,
					),
				}
			)

		normalized.append(
			{
				"kind": kind,
				"title": _clean_text(
					raw.get("title"), field=f"slides[{index}].title", maximum=90, required=True
				),
				"subtitle": _clean_text(raw.get("subtitle"), field=f"slides[{index}].subtitle", maximum=240),
				"bullets": [
					_clean_text(item, field=f"slides[{index}].bullets", maximum=180, required=True)
					for item in bullets
				],
				"metrics": clean_metrics,
				"callout": _clean_text(raw.get("callout"), field=f"slides[{index}].callout", maximum=180),
				"footer": _clean_text(raw.get("footer"), field=f"slides[{index}].footer", maximum=100),
			}
		)
	return normalized


def _id() -> str:
	return secrets.token_hex(5)[:9]


def _shape(
	x: float,
	y: float,
	width: float,
	height: float,
	fill: str,
	*,
	z_index: int,
	border_radius: int = 0,
	stroke: str | None = None,
	stroke_width: int = 0,
	shape_type: str = "rectangle",
) -> dict[str, Any]:
	return {
		"id": _id(),
		"zIndex": z_index,
		"width": width,
		"height": height,
		"left": x,
		"top": y,
		"opacity": 100,
		"rotation": 0,
		"type": "shape",
		"shapeType": shape_type,
		"fillColor": fill,
		"strokeColor": stroke or fill,
		"strokeWidth": stroke_width,
		"borderRadius": border_radius,
		"markerStart": False,
		"markerEnd": False,
		"shadowOffsetX": 0,
		"shadowOffsetY": 0,
		"shadowSpread": 0,
		"shadowColor": "#00000000",
	}


def _text(
	value: str,
	x: float,
	y: float,
	width: float,
	font_size: int,
	color: str,
	*,
	z_index: int,
	bold: bool = False,
	align: str = "left",
	line_height: float = 1.35,
	default_style: str | None = None,
) -> dict[str, Any]:
	content = html.escape(value)
	if bold:
		content = f"<strong>{content}</strong>"
	content = (
		f'<p style="text-align: {align};"><span style="color: {color}; font-size: {font_size}px; '
		f'font-family: Noto Sans SC; letter-spacing: 0px; opacity: 1;">{content}</span></p>'
	)
	element = {
		"id": _id(),
		"zIndex": z_index,
		"left": x + width / 2,
		"top": y,
		"type": "text",
		"content": content,
		"lineHeight": line_height,
		"width": width,
		"transform": "translate(-50%, 0%)",
		"transformOrigin": "center center",
	}
	if default_style:
		element["defaultStyle"] = default_style
	return element


def _bullet_text(items: list[str], color: str, font_size: int = 24) -> str:
	rows = []
	for item in items:
		text = html.escape(item)
		rows.append(
			f'<li style="font-size: {font_size}px; font-family: Noto Sans SC; color: {color}; opacity: 1;">'
			f'<p style="text-align: left;"><span style="color: {color}; font-size: {font_size}px; '
			f'font-family: Noto Sans SC; letter-spacing: 0px; opacity: 1;">{text}</span></p></li>'
		)
	return f"<ul>{''.join(rows)}</ul>"


def _bullet_element(items: list[str], *, y: float, color: str, z_index: int) -> dict[str, Any]:
	font_size = 22 if len(items) <= 4 else 19
	return {
		"id": _id(),
		"zIndex": z_index,
		"left": 480,
		"top": y,
		"type": "text",
		"content": _bullet_text(items, color, font_size),
		"lineHeight": 1.45,
		"width": 810,
		"transform": "translate(-50%, 0%)",
		"transformOrigin": "center center",
	}


def _footer(text: str, index: int, color: str) -> list[dict[str, Any]]:
	return [
		_shape(64, 499, 832, 1, COLORS["line"], z_index=20),
		_text(text or "I-ONE AI", 64, 507, 740, 12, color, z_index=21),
		_text(str(index), 846, 507, 50, 12, color, z_index=21, align="right"),
	]


def _render_cover(spec: dict[str, Any], index: int) -> dict[str, Any]:
	elements = [
		_shape(0, 0, SLIDE_WIDTH, SLIDE_HEIGHT, COLORS["dark"], z_index=1),
		_shape(0, 0, 16, SLIDE_HEIGHT, COLORS["brand"], z_index=2),
		_shape(64, 88, 72, 8, COLORS["teal"], z_index=3, border_radius=4),
		_text("客户解决方案", 64, 54, 300, 16, "#98A2B3FF", z_index=4, bold=True),
		_text(spec["title"], 64, 126, 820, 48, COLORS["white"], z_index=5, bold=True, line_height=1.15),
	]
	if spec["subtitle"]:
		elements.append(_text(spec["subtitle"], 64, 294, 760, 23, "#D0D5DDFF", z_index=6))
	if spec["callout"]:
		elements.extend(
			[
				_shape(64, 390, 620, 62, "#182230FF", z_index=7, border_radius=8),
				_text(spec["callout"], 86, 406, 576, 17, "#EAECF0FF", z_index=8),
			]
		)
	elements.extend(_footer(spec["footer"], index, "#98A2B3FF"))
	return _slide(COLORS["dark"], elements)


def _render_section(spec: dict[str, Any], index: int) -> dict[str, Any]:
	elements = [
		_shape(0, 0, SLIDE_WIDTH, SLIDE_HEIGHT, COLORS["brand"], z_index=1),
		_shape(64, 160, 72, 8, COLORS["amber"], z_index=2, border_radius=4),
		_text(spec["title"], 64, 198, 820, 46, COLORS["white"], z_index=3, bold=True),
	]
	if spec["subtitle"]:
		elements.append(_text(spec["subtitle"], 64, 285, 760, 23, "#DCE6FFFF", z_index=4))
	elements.extend(_footer(spec["footer"], index, "#DCE6FFFF"))
	return _slide(COLORS["brand"], elements)


def _base_content(spec: dict[str, Any], index: int) -> list[dict[str, Any]]:
	elements = [
		_text(spec["title"], 64, 42, 820, 34, COLORS["ink"], z_index=3, bold=True, default_style="title"),
		_shape(64, 103, 72, 5, COLORS["brand"], z_index=2, border_radius=3),
	]
	if spec["subtitle"]:
		elements.append(_text(spec["subtitle"], 64, 119, 820, 17, COLORS["muted"], z_index=3))
	elements.extend(_footer(spec["footer"], index, COLORS["muted"]))
	return elements


def _render_content(spec: dict[str, Any], index: int) -> dict[str, Any]:
	elements = _base_content(spec, index)
	if spec["bullets"]:
		elements.append(_bullet_element(spec["bullets"], y=174, color=COLORS["ink"], z_index=5))
	if spec["callout"]:
		elements.extend(
			[
				_shape(64, 406, 832, 68, "#EEF4FFFF", z_index=4, border_radius=8),
				_shape(64, 406, 6, 68, COLORS["brand"], z_index=5, border_radius=3),
				_text(spec["callout"], 88, 423, 780, 17, COLORS["ink"], z_index=6, bold=True),
			]
		)
	return _slide(COLORS["white"], elements)


def _render_metrics(spec: dict[str, Any], index: int) -> dict[str, Any]:
	elements = _base_content(spec, index)
	metrics = spec["metrics"] or [
		{"value": "待确认", "label": "目标指标", "detail": "与客户共同确定量化口径"}
	]
	card_width = (816 - 18 * (len(metrics) - 1)) / len(metrics)
	for metric_index, metric in enumerate(metrics):
		x = 72 + metric_index * (card_width + 18)
		elements.extend(
			[
				_shape(x, 188, card_width, 190, COLORS["surface"], z_index=4, border_radius=8),
				_shape(
					x,
					188,
					card_width,
					7,
					[COLORS["brand"], COLORS["teal"], COLORS["amber"], "#E94D8AFF"][metric_index],
					z_index=5,
					border_radius=4,
				),
				_text(
					metric["value"],
					x + 20,
					226,
					card_width - 40,
					31,
					COLORS["ink"],
					z_index=6,
					bold=True,
					align="center",
				),
				_text(
					metric["label"],
					x + 20,
					286,
					card_width - 40,
					18,
					COLORS["brand"],
					z_index=6,
					bold=True,
					align="center",
				),
				_text(
					metric["detail"],
					x + 20,
					326,
					card_width - 40,
					14,
					COLORS["muted"],
					z_index=6,
					align="center",
				),
			]
		)
	if spec["callout"]:
		elements.append(
			_text(spec["callout"], 90, 410, 780, 17, COLORS["ink"], z_index=6, bold=True, align="center")
		)
	return _slide(COLORS["white"], elements)


def _render_timeline(spec: dict[str, Any], index: int) -> dict[str, Any]:
	elements = _base_content(spec, index)
	steps = spec["bullets"][:4]
	if not steps:
		steps = ["启动与范围确认", "方案设计与配置", "验证、培训与上线", "持续运营与优化"]
	card_width = 188
	for step_index, step in enumerate(steps):
		x = 66 + step_index * 210
		if step_index < len(steps) - 1:
			elements.append(_shape(x + 148, 232, 78, 3, COLORS["line"], z_index=3))
		elements.extend(
			[
				_shape(x, 188, card_width, 206, COLORS["surface"], z_index=4, border_radius=8),
				_shape(
					x + 18, 208, 42, 42, COLORS["brand"], z_index=5, border_radius=21, shape_type="circle"
				),
				_text(
					str(step_index + 1),
					x + 18,
					215,
					42,
					18,
					COLORS["white"],
					z_index=6,
					bold=True,
					align="center",
				),
				_text(
					step,
					x + 18,
					274,
					card_width - 36,
					17,
					COLORS["ink"],
					z_index=6,
					bold=True,
					align="center",
				),
			]
		)
	if spec["callout"]:
		elements.append(_text(spec["callout"], 90, 420, 780, 16, COLORS["muted"], z_index=6, align="center"))
	return _slide(COLORS["white"], elements)


def _render_closing(spec: dict[str, Any], index: int) -> dict[str, Any]:
	elements = [
		_shape(0, 0, SLIDE_WIDTH, SLIDE_HEIGHT, COLORS["dark"], z_index=1),
		_shape(64, 110, 72, 8, COLORS["teal"], z_index=2, border_radius=4),
		_text(spec["title"], 64, 154, 820, 46, COLORS["white"], z_index=3, bold=True),
	]
	if spec["subtitle"]:
		elements.append(_text(spec["subtitle"], 64, 245, 760, 23, "#D0D5DDFF", z_index=4))
	if spec["bullets"]:
		elements.append(_bullet_element(spec["bullets"], y=320, color="#EAECF0FF", z_index=5))
	if spec["callout"]:
		elements.append(_text(spec["callout"], 64, 420, 820, 19, "#84CAFFFF", z_index=6, bold=True))
	elements.extend(_footer(spec["footer"], index, "#98A2B3FF"))
	return _slide(COLORS["dark"], elements)


def _slide(background: str, elements: list[dict[str, Any]]) -> dict[str, Any]:
	return {
		"background": background,
		"elements": json.dumps(elements, ensure_ascii=False, indent=2),
		"client_id": _id(),
		"transition": "Fade",
		"transition_duration": "0.35",
		"fade_unmatched_elements": 1,
	}


def build_presentation_slides(slides: list[dict[str, Any]]) -> list[dict[str, Any]]:
	normalized = normalize_slide_specs(slides)
	renderers = {
		"cover": _render_cover,
		"section": _render_section,
		"content": _render_content,
		"metrics": _render_metrics,
		"timeline": _render_timeline,
		"closing": _render_closing,
	}
	return [renderers[spec["kind"]](spec, index) for index, spec in enumerate(normalized, start=1)]
