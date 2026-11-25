from __future__ import annotations

import csv
import html
import json
import re
import time
from collections import Counter
from pathlib import Path
from typing import Any

PLACEHOLDER_PATTERN = re.compile(
	r"(?:\{\{\s*[a-zA-Z_][^{}]*\}\}|\$\{[^{}]+\}|%\([^)]+\)[#0 +\-]?(?:\d+|\*)?(?:\.\d+)?[diouxXeEfFgGcrs%]|"
	r"%[sdif]|\{\d+\}|\{[a-zA-Z_][\w.]*\})"
)
HTML_TAG_PATTERN = re.compile(r"</?[a-zA-Z][^>]*>")
HAN_PATTERN = re.compile(r"[\u3400-\u9fff]")
ENGLISH_WORD_PATTERN = re.compile(r"[A-Za-z]{2,}")
TECHNICAL_PASSTHROUGH = {
	"API",
	"CRM",
	"CSV",
	"DocType",
	"ERPNext",
	"Frappe",
	"Flow",
	"GitHub",
	"GitHub ID",
	"GitLab",
	"Google Analytics ID",
	"Google Classroom",
	"Google Meet",
	"HR",
	"HL7 v2",
	"HTML",
	"I-ONE",
	"I ONE AI",
	"IONE AI",
	"IONE CDI",
	"IONE DIP",
	"IONE DRG",
	"IONE Flow AI",
	"IONE QMS",
	"ID",
	"JSON",
	"Instagram",
	"Javascript",
	"Jinja",
	"Kajabi",
	"Keycloak",
	"LDAP",
	"LinkedIn",
	"Linode",
	"MariaDB",
	"Markdown",
	"Meilisearch",
	"Microsoft",
	"Microsoft Teams",
	"Moodle",
	"MySQL",
	"Namecheap",
	"Nextcloud",
	"Nomatim",
	"Nominatim",
	"Notion",
	"OAuth",
	"Office 365",
	"Ollama",
	"OpenAI",
	"Oracle",
	"Outlook.com",
	"PayPal",
	"Pipedrive",
	"Plausible",
	"PostgreSQL",
	"Pusher",
	"Qwen",
	"Razorpay",
	"REST API",
	"REST JSON",
	"Redis",
	"Robots.txt",
	"Rust",
	"S3",
	"SLA",
	"SNOMED CT",
	"SQL",
	"Sqlite",
	"Sendgrid",
	"Sentry",
	"Sigstore Rekor",
	"Shopify",
	"Skype",
	"Slack",
	"Stalwart/JMAP",
	"Stripe",
	"Supabase",
	"Teachmint",
	"Telegram",
	"Thinkific",
	"Trello",
	"Twilio",
	"Twitter",
	"Unsplash",
	"URL",
	"UTF-8",
	"Vimeo",
	"Vercel",
	"Verdana",
	"Webhook",
	"Websocket",
	"WhatsApp",
	"Wistia",
	"WooCommerce",
	"WordPress",
	"YouTube",
	"Xero",
	"X (Twitter)",
	"Zoho CRM",
	"Zapier",
	"Zoom",
	"Arial",
	"Azure",
	"Bootstrap",
	"Chrome",
	"Classplus",
	"Cloudflare",
	"Emacs",
	"Facebook",
	"Fairlogin",
	"FHIR",
	"Geoapify",
	"Helvetica",
	"Helvetica Neue",
	"Hetzner",
	"Inter",
	"JMAP",
	"Maildir",
	"Mbox",
	"Noto Sans",
	"Roboto",
	"VCF",
	"Vim",
	"VS Code",
	"VSCode",
	"wkhtmltopdf",
	"exchangerate-api",
	"fawazahmed-exchange-api",
}
TECHNICAL_PASSTHROUGH_CASEFOLDED = frozenset(
	value.casefold() for value in TECHNICAL_PASSTHROUGH
)
TECHNICAL_CODE_LITERALS = {
	"div",
	"durationchange",
	"eml",
	"hr",
	"ics",
	"id",
	"loadedmetadata",
	"nonce",
	"processlist",
	"resp2",
	"resp3",
	"simulcast",
	"span",
	"svc",
	"svg",
	"td",
	"th",
	"timeupdate",
	"tr",
	"volumechange",
}
CODE_MARKERS = (
	"[File truncated to fit the context window.]",
	"exports=function",
	"__name__",
	"sourceMappingURL",
	"webpack",
	"function(e,n,s)",
	"createElement(",
	"onUpdate:modelValue",
	").format(",
	"=>",
	"console.",
	"===",
	"!==",
	"&&",
	"||",
)


def collect_missing_messages(language: str = "zh", apps: list[str] | None = None) -> list[str]:
	"""Return source messages that are not translated by any installed app."""
	import frappe
	from frappe.translate import deduplicate_messages, get_all_translations, get_messages_for_app

	translations = get_all_translations(language)
	messages: list[tuple[Any, ...]] = []
	for app in apps or frappe.get_installed_apps():
		messages.extend(get_messages_for_app(app))

	return sorted(
		{
			message[1]
			for message in deduplicate_messages(messages)
			if len(message) > 1 and message[1] and not translations.get(message[1])
		}
	)


def is_translation_candidate(message: str) -> bool:
	"""Discard extractor artifacts while retaining labels, errors, and HTML help."""
	if not message or not message.strip():
		return False
	stripped = message.strip()
	if any(marker in message for marker in CODE_MARKERS):
		return False
	if stripped.startswith(("),", ",!0", "))", "}:_", "):_")):
		return False
	if re.fullmatch(
		r"\$[a-zA-Z_][\w.]*|@[a-zA-Z0-9_.-]+|\.[a-zA-Z0-9.]+", stripped
	):
		return False
	if re.fullmatch(r"[a-z][A-Z0-9]{3,}", stripped):
		return False
	if re.fullmatch(r"[a-z][A-Za-z0-9]*(?:[._:-][A-Za-z0-9]+)+", stripped):
		return False
	if re.fullmatch(r"[a-z_]+(?:\s*\|\s*[a-z_]+)+", stripped):
		return False
	if stripped.casefold() in TECHNICAL_CODE_LITERALS:
		return False
	if len(message) > 1000 and not ("<" in message and ">" in message):
		return False
	if len(message) > 500:
		punctuation = sum(message.count(char) for char in "{}[]();=,")
		if punctuation / len(message) > 0.12 and message.count(" ") / len(message) < 0.08:
			return False
	return requires_chinese_text(message)


def placeholders(value: str) -> Counter[str]:
	return Counter(PLACEHOLDER_PATTERN.findall(value or ""))


def html_tags(value: str) -> Counter[str]:
	return Counter(HTML_TAG_PATTERN.findall(value or ""))


def requires_chinese_text(source: str) -> bool:
	visible = html.unescape(source or "")
	visible = PLACEHOLDER_PATTERN.sub("", HTML_TAG_PATTERN.sub("", visible)).strip()
	if not visible or visible.casefold() in TECHNICAL_PASSTHROUGH_CASEFOLDED:
		return False
	technical_parts = [part.strip() for part in visible.split("/")]
	if len(technical_parts) > 1 and all(
		part.casefold() in TECHNICAL_PASSTHROUGH_CASEFOLDED for part in technical_parts
	):
		return False
	if re.fullmatch(r"[A-Z][A-Z0-9_-]{1,19}", visible):
		return False
	if not re.search(r"[a-z]", visible) and re.fullmatch(r"[A-Z0-9_.:/-]+", visible):
		return False
	if " " not in visible and re.fullmatch(r"[A-Z][A-Za-z0-9_-]*[A-Z0-9][A-Za-z0-9_-]*", visible):
		return False
	if re.fullmatch(r"(?:https?://|mailto:|www\.)\S+|\S+@\S+\.\S+", visible):
		return False
	if re.fullmatch(r"[YMDHhms:/.,\-\s]+", visible, flags=re.IGNORECASE):
		return False
	return bool(ENGLISH_WORD_PATTERN.search(visible))


def validate_translation(source: str, translation: str) -> list[str]:
	errors: list[str] = []
	if not isinstance(translation, str) or not translation.strip():
		return ["translation is empty"]
	if placeholders(source) != placeholders(translation):
		errors.append("placeholders changed")
	if html_tags(source) != html_tags(translation):
		errors.append("HTML tags changed")
	if requires_chinese_text(source) and not HAN_PATTERN.search(translation):
		errors.append("translation contains no Chinese text")
	return errors


def translate_missing_catalog(
	output_file: str,
	model_name: str | None = None,
	base_url_override: str | None = None,
	batch_size: int = 80,
	limit: int = 0,
	apps: list[str] | None = None,
) -> dict[str, int]:
	"""Translate missing catalog messages with the site's enabled Flow model.

	The JSON checkpoint is written after every successful batch, so interrupted runs
	can resume without repeating completed model calls. Pass ``apps`` to limit the
	translation run to specific installed applications.
	"""
	import frappe
	import requests

	output_path = Path(output_file)
	completed = _load_json_dict(output_path)
	failure_path = output_path.with_suffix(output_path.suffix + ".failures")
	failures = _load_json_dict(failure_path)
	messages = [
		message
		for message in collect_missing_messages(apps=apps)
		if is_translation_candidate(message)
	]
	message_set = set(messages)
	discarded = len(completed)
	completed = {
		source: translation
		for source, translation in completed.items()
		if source in message_set and not validate_translation(source, translation)
	}
	discarded -= len(completed)
	failures = {
		source: error
		for source, error in failures.items()
		if source in message_set and source not in completed
	}
	pending = [message for message in messages if message not in completed]
	if limit:
		pending = pending[:limit]
	_write_json_dict(output_path, completed)
	_write_json_dict(failure_path, failures)
	if not pending:
		return {
			"catalog_messages": len(messages),
			"translated_messages": len(completed),
			"remaining_messages": max(0, len(messages) - len(completed)),
			"failed_messages": len(failures),
			"discarded_checkpoint_messages": discarded,
		}

	model = _get_flow_model(model_name)
	api_key = model.get_password("api_key")
	base_url = (base_url_override or model.base_url or "").rstrip("/")
	if not base_url:
		frappe.throw("The selected Flow Model has no base URL.")
	model_id = str(model.model_id or "").removeprefix("openai/")

	session = requests.Session()
	session.trust_env = False
	for offset in range(0, len(pending), max(1, int(batch_size))):
		batch = pending[offset : offset + batch_size]
		translated, batch_failures = _translate_batch_resilient(
			session, base_url, api_key, model_id, batch
		)
		completed.update(translated)
		for source in translated:
			failures.pop(source, None)
		failures.update(batch_failures)
		_write_json_dict(output_path, completed)
		_write_json_dict(failure_path, failures)
		print(
			f"processed {min(offset + len(batch), len(pending))}/{len(pending)}; "
			f"translated={len(completed)} failures={len(failures)}"
		)

	return {
		"catalog_messages": len(messages),
		"translated_messages": len(completed),
		"remaining_messages": max(0, len(messages) - len(completed)),
		"failed_messages": len(failures),
		"discarded_checkpoint_messages": discarded,
	}


def _get_flow_model(model_name: str | None):
	import frappe

	name = model_name or frappe.db.get_value(
		"Flow Model", {"enabled": 1}, "name", order_by="creation asc"
	)
	if not name:
		frappe.throw("No enabled Flow Model is configured.")
	return frappe.get_doc("Flow Model", name)


def _translate_batch_resilient(
	session: Any,
	base_url: str,
	api_key: str,
	model_id: str,
	messages: list[str],
) -> tuple[dict[str, str], dict[str, str]]:
	translated: dict[str, str] = {}
	pending = list(messages)
	last_errors: dict[str, str] = {}
	last_attempt_was_request_error = False
	for attempt in range(3):
		try:
			result = _request_translations(session, base_url, api_key, model_id, pending)
		except Exception as exc:
			last_attempt_was_request_error = True
			last_errors = {source: str(exc) for source in pending}
		else:
			last_attempt_was_request_error = False
			next_pending: list[str] = []
			last_errors = {}
			for source in pending:
				errors = validate_translation(source, result.get(source, ""))
				if errors:
					next_pending.append(source)
					last_errors[source] = ", ".join(errors)
				else:
					translated[source] = result[source]
			pending = next_pending
			if not pending:
				return translated, {}
		time.sleep(2**attempt)

	if pending and not last_attempt_was_request_error:
		return translated, last_errors
	if len(pending) == 1:
		return translated, {pending[0]: last_errors.get(pending[0], "translation failed")}
	if pending:
		middle = len(pending) // 2
		left, left_failures = _translate_batch_resilient(
			session, base_url, api_key, model_id, pending[:middle]
		)
		right, right_failures = _translate_batch_resilient(
			session, base_url, api_key, model_id, pending[middle:]
		)
		translated.update(left)
		translated.update(right)
		return translated, {**left_failures, **right_failures}
	return translated, {}


def _request_translations(
	session: Any,
	base_url: str,
	api_key: str,
	model_id: str,
	messages: list[str],
) -> dict[str, str]:
	items = [{"id": index, "text": message} for index, message in enumerate(messages)]
	response = session.post(
		f"{base_url}/chat/completions",
		headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
		json={
			"model": model_id,
			"temperature": 0,
			"max_tokens": 8192,
			"messages": [
				{
					"role": "system",
					"content": (
						"You are the Simplified Chinese localization editor for the Frappe business "
						"software ecosystem. Translate every UI label, help text, validation message, "
						"and notification naturally and professionally. Preserve every placeholder, "
						"HTML tag, variable, number, punctuation intent, and line break. Keep product "
						"and technical names such as Frappe, ERPNext, I-ONE, Flow, CRM, HR, API, URL, "
						"SQL, JSON, CSV, DocType, ID, OAuth, and SLA unchanged. Return only a JSON "
						"array of objects with integer id and string translation; do not add markdown."
					),
				},
				{
					"role": "user",
					"content": json.dumps(items, ensure_ascii=False),
				},
			],
		},
		timeout=330,
	)
	response.raise_for_status()
	content = response.json()["choices"][0]["message"]["content"]
	rows = _parse_json_array(content)
	by_id = {int(row["id"]): _translation_from_row(row) for row in rows}
	if set(by_id) != set(range(len(messages))):
		raise ValueError(
			f"model response ids {sorted(by_id)} did not match {list(range(len(messages)))}"
		)
	return {source: by_id[index] for index, source in enumerate(messages)}


def _translation_from_row(row: dict[str, Any]) -> str:
	for key in ("translation", "translated_text", "translated", "text"):
		value = row.get(key)
		if isinstance(value, str) and value.strip():
			return value
	raise ValueError(f"model response row has no translation: {row!r}")


def _parse_json_array(content: str) -> list[dict[str, Any]]:
	value = (content or "").strip()
	if value.startswith("```"):
		value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.IGNORECASE)
	start = value.find("[")
	end = value.rfind("]")
	if start < 0 or end < start:
		raise ValueError("model response did not contain a JSON array")
	parsed = json.loads(value[start : end + 1])
	if not isinstance(parsed, list):
		raise ValueError("model response is not a JSON array")
	return parsed


def _load_json_dict(path: Path) -> dict[str, str]:
	if not path.exists():
		return {}
	loaded = json.loads(path.read_text(encoding="utf-8"))
	return {str(key): str(value) for key, value in loaded.items()}


def _write_json_dict(path: Path, values: dict[str, str]) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	temporary = path.with_suffix(path.suffix + ".tmp")
	temporary.write_text(
		json.dumps(dict(sorted(values.items())), ensure_ascii=False, indent=2) + "\n",
		encoding="utf-8",
	)
	temporary.replace(path)


def audit_translation_values(
	messages: list[str],
	translations: dict[str, str],
) -> dict[str, Any]:
	candidates = {message for message in messages if is_translation_candidate(message)}
	missing = sorted(candidates - translations.keys())
	invalid = {
		source: errors
		for source in sorted(candidates & translations.keys())
		if (errors := validate_translation(source, translations[source]))
	}
	extra = sorted(translations.keys() - candidates)
	return {
		"candidate_messages": len(candidates),
		"translated_messages": len(candidates & translations.keys()) - len(invalid),
		"missing_messages": len(missing),
		"invalid_messages": len(invalid),
		"extra_messages": len(extra),
		"missing_sample": missing[:20],
		"invalid_sample": dict(list(invalid.items())[:20]),
		"extra_sample": extra[:20],
	}


def audit_translation_checkpoint(input_file: str) -> dict[str, Any]:
	"""Audit a live checkpoint against every installed-app translation candidate."""
	return audit_translation_values(
		collect_missing_messages(),
		_load_json_dict(Path(input_file)),
	)


def merge_translations_into_csv(
	input_file: str,
	csv_file: str,
	overwrite: bool = False,
) -> dict[str, int]:
	"""Merge a validated checkpoint while preserving hand-edited translations."""
	checkpoint = _load_json_dict(Path(input_file))
	translations = {
		source: translation
		for source, translation in checkpoint.items()
		if is_translation_candidate(source)
	}
	invalid = {
		source: errors
		for source, translation in translations.items()
		if (errors := validate_translation(source, translation))
	}
	if invalid:
		sample = dict(list(sorted(invalid.items()))[:20])
		raise ValueError(f"checkpoint contains invalid translations: {sample}")
	csv_path = Path(csv_file)
	existing: dict[str, str] = {}
	if csv_path.exists():
		with csv_path.open("r", encoding="utf-8", newline="") as handle:
			for row in csv.reader(handle):
				if len(row) >= 2 and row[0]:
					existing[row[0]] = row[1]

	added_messages = sorted(set(translations) - set(existing), key=str.casefold)
	updated_messages = {
		message
		for message in translations.keys() & existing.keys()
		if overwrite and existing[message] != translations[message]
	}
	for message in updated_messages:
		existing[message] = translations[message]
	for message in added_messages:
		existing[message] = translations[message]

	temporary = csv_path.with_suffix(csv_path.suffix + ".tmp")
	with temporary.open("w", encoding="utf-8", newline="") as handle:
		writer = csv.writer(handle, lineterminator="\n")
		writer.writerows(existing.items())
	temporary.replace(csv_path)
	return {
		"total": len(existing),
		"added": len(added_messages),
		"updated": len(updated_messages),
	}
