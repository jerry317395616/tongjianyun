from __future__ import annotations

import gzip
import hashlib
import json
import re
from pathlib import Path
from typing import Any

BUNDLE_SCHEMA_VERSION = 1
BUNDLE_DIRECTORY = Path(__file__).with_name("translation_data")
MANIFEST_FILENAME = "manifest.json"
INSTALL_HASH_KEY = "ione_core_wiki_translation_bundle_hash"

SPACE_FIELDS = (
	"space_name",
	"route",
	"switcher_order",
	"enable_feedback_collection",
	"show_in_switcher",
	"is_published",
	"allow_contributions",
)
DOCUMENT_FIELDS = (
	"title",
	"route",
	"slug",
	"doc_key",
	"source_path",
	"content",
	"is_published",
	"is_group",
	"is_external_link",
	"external_url",
	"meta_title",
	"meta_description",
	"meta_image",
	"sort_order",
)


def export_translation_bundle(
	output_dir: str | Path | None = None,
	space_routes: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
	"""Export Wiki text and hierarchy into deterministic, version-controlled package files."""
	import frappe

	if not _wiki_available():
		return {"status": "skipped", "reason": "Frappe Wiki is not installed"}

	target = Path(output_dir) if output_dir else BUNDLE_DIRECTORY
	target.mkdir(parents=True, exist_ok=True)
	selected_routes = {route.strip() for route in space_routes or () if route.strip()}
	filters = {"route": ["in", sorted(selected_routes)]} if selected_routes else None
	spaces = frappe.get_all(
		"Wiki Space",
		filters=filters,
		fields=["name", *SPACE_FIELDS, "root_group"],
		order_by="route asc",
		limit_page_length=0,
	)

	entries = []
	written_files: set[str] = set()
	for space_row in spaces:
		space = frappe.get_doc("Wiki Space", space_row.name)
		payload = _export_space(space)
		filename = f"{_safe_filename(space.route)}.json.gz"
		raw = _canonical_json(payload)
		compressed = _gzip_bytes(raw)
		(target / filename).write_bytes(compressed)
		written_files.add(filename)
		entries.append(
			{
				"route": space.route,
				"file": filename,
				"sha256": hashlib.sha256(compressed).hexdigest(),
				"documents": len(payload["documents"]),
				"pages": sum(not document["is_group"] for document in payload["documents"]),
				"groups": sum(bool(document["is_group"]) for document in payload["documents"]),
			}
		)

	for stale in target.glob("*.json.gz"):
		if stale.name not in written_files:
			stale.unlink()

	bundle_hash = _entries_hash(entries)
	manifest = {
		"schema_version": BUNDLE_SCHEMA_VERSION,
		"bundle_sha256": bundle_hash,
		"spaces": entries,
		"summary": {
			"spaces": len(entries),
			"documents": sum(entry["documents"] for entry in entries),
			"pages": sum(entry["pages"] for entry in entries),
			"groups": sum(entry["groups"] for entry in entries),
		},
	}
	(target / MANIFEST_FILENAME).write_bytes(_pretty_json(manifest))
	return {"status": "exported", **manifest["summary"], "bundle_sha256": bundle_hash}


def install_translation_bundle(
	bundle_dir: str | Path | None = None,
	force: bool = False,
) -> dict[str, Any]:
	"""Install packaged Wiki translations without requiring the source site or an LLM."""
	import frappe

	if not _wiki_available():
		return {"status": "skipped", "reason": "Frappe Wiki is not installed"}

	source = Path(bundle_dir) if bundle_dir else BUNDLE_DIRECTORY
	manifest_path = source / MANIFEST_FILENAME
	if not manifest_path.exists():
		return {"status": "skipped", "reason": "No packaged Wiki translations"}

	manifest = _load_manifest(source)
	installed_hash = frappe.db.get_default(INSTALL_HASH_KEY)
	if not force and installed_hash == manifest["bundle_sha256"] and _bundle_is_present(manifest):
		return {"status": "current", **manifest["summary"]}

	stats = {"spaces": 0, "documents_created": 0, "documents_updated": 0}
	for entry in manifest["spaces"]:
		payload = _read_payload(source / entry["file"])
		result = _install_space(payload)
		stats["spaces"] += 1
		stats["documents_created"] += result["created"]
		stats["documents_updated"] += result["updated"]

	from frappe.utils.nestedset import rebuild_tree

	rebuild_tree("Wiki Document")
	frappe.db.set_default(INSTALL_HASH_KEY, manifest["bundle_sha256"])
	frappe.clear_cache()
	return {"status": "installed", **stats, **manifest["summary"]}


def _export_space(space: Any) -> dict[str, Any]:
	import frappe

	documents = frappe.get_all(
		"Wiki Document",
		filters={"wiki_space": space.name},
		fields=["name", "parent_wiki_document", *DOCUMENT_FIELDS],
		order_by="lft asc, sort_order asc, name asc",
		limit_page_length=0,
	)
	keys = {document.name: _document_key(document) for document in documents}
	if len(keys) != len(set(keys.values())):
		raise ValueError(f"Wiki Space {space.route} contains duplicate portable document keys")

	parent_map = {document.name: document.parent_wiki_document for document in documents}
	depth_cache: dict[str, int] = {}
	payload_documents = []
	for document in documents:
		row = {field: document.get(field) for field in DOCUMENT_FIELDS}
		row.update(
			{
				"key": keys[document.name],
				"parent_key": keys.get(document.parent_wiki_document),
				"depth": _document_depth(document.name, parent_map, depth_cache),
			}
		)
		payload_documents.append(row)

	payload_documents.sort(
		key=lambda row: (
			row["depth"],
			0 if row["is_group"] else 1,
			row["sort_order"] or 0,
			row["route"] or "",
			row["key"],
		)
	)
	root_key = keys.get(space.root_group)
	if documents and not root_key:
		raise ValueError(f"Wiki Space {space.route} has documents but no portable root group")

	return {
		"schema_version": BUNDLE_SCHEMA_VERSION,
		"space": {field: space.get(field) for field in SPACE_FIELDS},
		"roles": sorted(
			(
				{"role": row.role, "permission_level": row.permission_level}
				for row in space.get("roles") or []
			),
			key=lambda row: (row["role"], row["permission_level"]),
		),
		"navbar_items": [
			{
				"label": row.label,
				"url": row.url,
				"open_in_new_tab": row.open_in_new_tab,
				"right": row.right,
				"parent_label": row.parent_label,
			}
			for row in space.get("navbar_items") or []
		],
		"root_key": root_key,
		"documents": payload_documents,
	}


def _install_space(payload: dict[str, Any]) -> dict[str, int]:
	import frappe

	space_values = payload["space"]
	space_name = frappe.db.get_value("Wiki Space", {"route": space_values["route"]}, "name")
	if space_name:
		space = frappe.get_doc("Wiki Space", space_name)
		space.update(space_values)
		space.set("roles", payload.get("roles") or [])
		space.set("navbar_items", payload.get("navbar_items") or [])
		space.save(ignore_permissions=True)
	else:
		space = frappe.get_doc(
			{
				"doctype": "Wiki Space",
				**space_values,
				"roles": payload.get("roles") or [],
				"navbar_items": payload.get("navbar_items") or [],
			}
		).insert(ignore_permissions=True)

	existing = frappe.get_all(
		"Wiki Document",
		fields=["name", "wiki_space", "route", "source_path", "doc_key"],
		limit_page_length=0,
	)
	existing.sort(key=lambda row: row.wiki_space == space.name)
	by_source = {row.source_path: row.name for row in existing if row.source_path}
	by_route = {row.route: row.name for row in existing if row.route}
	by_doc_key = {row.doc_key: row.name for row in existing if row.doc_key}
	key_to_name: dict[str, str] = {}
	created = 0
	updated = 0

	for row in payload["documents"]:
		name = _match_existing_document(row, by_source, by_doc_key, by_route)
		if not name and row["key"] == payload.get("root_key"):
			name = space.root_group
		values = {field: row.get(field) for field in DOCUMENT_FIELDS}
		values["wiki_space"] = space.name
		values.pop("parent_wiki_document", None)
		if name:
			frappe.db.set_value("Wiki Document", name, values, update_modified=False)
			updated += 1
		else:
			document = frappe.get_doc(
				{
					"doctype": "Wiki Document",
					**values,
					"parent_wiki_document": None,
				}
			).insert(ignore_permissions=True)
			name = document.name
			created += 1
		frappe.db.set_value(
			"Wiki Document",
			name,
			"wiki_space",
			space.name,
			update_modified=False,
		)
		key_to_name[row["key"]] = name
		if row.get("source_path"):
			by_source[row["source_path"]] = name
		if row.get("route"):
			by_route[row["route"]] = name
		if row.get("doc_key"):
			by_doc_key[row["doc_key"]] = name

	for row in payload["documents"]:
		parent_key = row.get("parent_key")
		if parent_key and parent_key not in key_to_name:
			raise ValueError(f"Missing packaged parent {parent_key!r} in {space.route}")
		frappe.db.set_value(
			"Wiki Document",
			key_to_name[row["key"]],
			"parent_wiki_document",
			key_to_name.get(parent_key),
			update_modified=False,
		)

	root_key = payload.get("root_key")
	if root_key:
		frappe.db.set_value(
			"Wiki Space",
			space.name,
			"root_group",
			key_to_name[root_key],
			update_modified=False,
		)
	return {"created": created, "updated": updated}


def _bundle_is_present(manifest: dict[str, Any]) -> bool:
	import frappe

	for entry in manifest["spaces"]:
		space_name = frappe.db.get_value("Wiki Space", {"route": entry["route"]}, "name")
		if not space_name:
			return False
		if frappe.db.count("Wiki Document", {"wiki_space": space_name}) < entry["documents"]:
			return False
	return True


def _load_manifest(directory: Path) -> dict[str, Any]:
	manifest = json.loads((directory / MANIFEST_FILENAME).read_text(encoding="utf-8"))
	if manifest.get("schema_version") != BUNDLE_SCHEMA_VERSION:
		raise ValueError("Unsupported I-ONE translation bundle schema")
	for entry in manifest.get("spaces") or []:
		path = directory / entry["file"]
		if not path.is_file():
			raise ValueError(f"Missing translation bundle file: {entry['file']}")
		if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
			raise ValueError(f"Translation bundle checksum mismatch: {entry['file']}")
	if _entries_hash(manifest.get("spaces") or []) != manifest.get("bundle_sha256"):
		raise ValueError("Translation bundle manifest checksum mismatch")
	return manifest


def _read_payload(path: Path) -> dict[str, Any]:
	with gzip.open(path, "rb") as handle:
		payload = json.load(handle)
	if payload.get("schema_version") != BUNDLE_SCHEMA_VERSION:
		raise ValueError(f"Unsupported packaged Wiki schema in {path.name}")
	return payload


def _document_key(document: Any) -> str:
	if document.source_path:
		return f"source:{document.source_path}"
	if document.doc_key:
		return f"document:{document.doc_key}"
	if document.route:
		return f"route:{document.route}"
	return f"legacy:{document.name}"


def _document_depth(name: str, parents: dict[str, str | None], cache: dict[str, int]) -> int:
	if name in cache:
		return cache[name]
	seen = {name}
	depth = 0
	parent = parents.get(name)
	while parent:
		if parent in seen:
			raise ValueError(f"Wiki Document hierarchy contains a cycle at {name}")
		seen.add(parent)
		depth += 1
		parent = parents.get(parent)
	cache[name] = depth
	return depth


def _match_existing_document(
	row: dict[str, Any],
	by_source: dict[str, str],
	by_doc_key: dict[str, str],
	by_route: dict[str, str],
) -> str | None:
	if row.get("source_path") and row["source_path"] in by_source:
		return by_source[row["source_path"]]
	if row.get("doc_key") and row["doc_key"] in by_doc_key:
		return by_doc_key[row["doc_key"]]
	if row.get("route") and row["route"] in by_route:
		return by_route[row["route"]]
	return None


def _wiki_available() -> bool:
	import frappe

	return all(frappe.db.exists("DocType", doctype) for doctype in ("Wiki Space", "Wiki Document"))


def _entries_hash(entries: list[dict[str, Any]]) -> str:
	lines = [f"{entry['route']}:{entry['sha256']}" for entry in sorted(entries, key=lambda row: row["route"])]
	return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _safe_filename(route: str) -> str:
	return re.sub(r"[^a-z0-9._-]+", "-", route.lower()).strip("-") or "wiki-space"


def _canonical_json(value: Any) -> bytes:
	return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _pretty_json(value: Any) -> bytes:
	return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _gzip_bytes(value: bytes) -> bytes:
	import io

	buffer = io.BytesIO()
	with gzip.GzipFile(fileobj=buffer, mode="wb", filename="", mtime=0) as handle:
		handle.write(value)
	return buffer.getvalue()
