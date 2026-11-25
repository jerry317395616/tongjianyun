from __future__ import annotations

import base64
import binascii
import io
import json
import re
import zipfile
from pathlib import PurePath
from typing import Any
from xml.etree import ElementTree

DENIED_DOCTYPES = {
	"Access Log",
	"Activity Log",
	"API Request Log",
	"Auth Token",
	"Client Script",
	"Communication",
	"Connected App",
	"Custom Field",
	"Custom DocPerm",
	"DocField",
	"DocPerm",
	"DocType",
	"Email Account",
	"Email Queue",
	"Error Log",
	"Event Streaming",
	"File",
	"Has Role",
	"Integration Request",
	"Module Def",
	"OAuth Authorization Code",
	"OAuth Bearer Token",
	"OAuth Client",
	"Package",
	"Package Import",
	"Password",
	"Property Setter",
	"RQ Job",
	"Role",
	"Role Profile",
	"Role Profile Role",
	"Scheduled Job Log",
	"Server Script",
	"Session Default Settings",
	"Social Login Key",
	"System Settings",
	"User",
	"User Permission",
	"Webhook",
}

PROTECTED_FIELDS = {
	"creation",
	"docstatus",
	"idx",
	"modified",
	"modified_by",
	"owner",
	"parent",
	"parentfield",
	"parenttype",
}

ORDER_BY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(?:\s+(?:asc|desc))?$", re.IGNORECASE)
SAFE_FILE_EXTENSIONS = {".csv", ".json", ".md", ".txt"}
MAX_DOCX_BYTES = 5 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED_BYTES = 25 * 1024 * 1024
MAX_DOCX_TEXT_CHARACTERS = 300000
REQUIRED_DOCX_PARTS = {"[Content_Types].xml", "word/document.xml"}
MAX_XLSX_BYTES = 8 * 1024 * 1024
MAX_XLSX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
REQUIRED_XLSX_PARTS = {"[Content_Types].xml", "xl/workbook.xml"}
SENSITIVE_KEYS = {
	"actor_token",
	"api_key",
	"api_secret",
	"authorization",
	"password",
	"secret",
	"token",
}


def require_login() -> str:
	import frappe

	user = getattr(frappe.session, "user", "Guest")
	if not user or user == "Guest":
		frappe.throw("MCP requires an authenticated Frappe user", frappe.AuthenticationError)
	return user


def _configured_values(name: str) -> tuple[str, ...]:
	import frappe

	values = frappe.conf.get(name)
	if isinstance(values, str):
		try:
			decoded = json.loads(values)
		except json.JSONDecodeError:
			decoded = values.split(",")
		values = decoded
	if not isinstance(values, (list, tuple, set)):
		return ()
	return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _configured_values_by_user(name: str, user: str) -> tuple[str, ...]:
	import frappe

	configuration = frappe.conf.get(name) or {}
	if isinstance(configuration, str):
		try:
			configuration = json.loads(configuration)
		except json.JSONDecodeError:
			return ()
	if not isinstance(configuration, dict) or user not in configuration:
		return ()
	values = configuration.get(user)
	if isinstance(values, str):
		values = values.split(",")
	if not isinstance(values, (list, tuple, set)):
		return ()
	return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def integration_scope_user(user: str | None = None) -> str:
	"""Return the integration identity whose site-config scope should be applied."""
	import frappe

	local = getattr(frappe, "local", None)
	return str(user or getattr(local, "ione_mcp_integration_user", "") or require_login())


def allowed_doctype_prefixes(user: str | None = None) -> tuple[str, ...]:
	"""Return an optional per-user MCP DocType scope from site_config.json."""
	return _configured_values_by_user(
		"ione_mcp_allowed_doctype_prefixes_by_user", integration_scope_user(user)
	)


def allowed_doctypes(user: str | None = None) -> tuple[str, ...]:
	"""Return an optional exact allowlist for this site or integration user."""
	values = list(_configured_values("ione_mcp_allowed_doctypes"))
	values.extend(
		_configured_values_by_user("ione_mcp_allowed_doctypes_by_user", integration_scope_user(user))
	)
	return tuple(dict.fromkeys(values))


def denied_doctypes(user: str | None = None) -> frozenset[str]:
	"""Return built-in and site-specific DocTypes that MCP must never expose."""
	values = set(DENIED_DOCTYPES)
	values.update(_configured_values("ione_mcp_denied_doctypes"))
	values.update(
		_configured_values_by_user("ione_mcp_denied_doctypes_by_user", integration_scope_user(user))
	)
	return frozenset(values)


def doctype_is_denied(doctype: str, user: str | None = None) -> bool:
	return doctype in denied_doctypes(user)


def doctype_allowed_by_scope(doctype: str, user: str | None = None) -> bool:
	if doctype_is_denied(doctype, user):
		return False
	exact = allowed_doctypes(user)
	if exact and doctype not in exact:
		return False
	prefixes = allowed_doctype_prefixes(user)
	return not prefixes or any(doctype.startswith(prefix) for prefix in prefixes)


def ensure_doctype_permission(doctype: str, permission_type: str):
	import frappe

	require_login()
	doctype = (doctype or "").strip()
	if not doctype or doctype_is_denied(doctype):
		frappe.throw(f"DocType {doctype or '<empty>'} is not available through MCP", frappe.PermissionError)
	if not doctype_allowed_by_scope(doctype):
		frappe.throw(f"DocType {doctype} is outside this MCP integration's scope", frappe.PermissionError)
	if not frappe.db.exists("DocType", doctype):
		frappe.throw(f"DocType {doctype} does not exist")
	meta = frappe.get_meta(doctype)
	if meta.istable:
		frappe.throw("Child tables must be accessed through their parent document")
	if not frappe.has_permission(doctype, ptype=permission_type):
		frappe.throw(f"No {permission_type} permission for {doctype}", frappe.PermissionError)
	return meta


def validate_order_by(meta, order_by: str | None, permitted: set[str]) -> str:
	value = (order_by or "modified desc").strip()
	if not ORDER_BY_PATTERN.fullmatch(value):
		raise ValueError("order_by must contain one field and an optional asc/desc direction")
	fieldname = value.split()[0]
	if fieldname not in {"name", "creation", "modified", "owner"} and not meta.has_field(fieldname):
		raise ValueError(f"Unknown order_by field: {fieldname}")
	if fieldname not in {"name", "creation", "modified", "owner"} and fieldname not in permitted:
		raise ValueError(f"order_by field is not available through MCP: {fieldname}")
	return value


def permitted_fields(doctype: str, permission_type: str, parenttype: str | None = None) -> set[str]:
	import frappe
	from frappe.model import get_permitted_fields

	return set(
		get_permitted_fields(
			doctype,
			parenttype=parenttype,
			user=frappe.session.user,
			permission_type=permission_type,
		)
	)


def safe_fields(meta, fields: list[str] | None, permitted: set[str]) -> list[str]:
	requested = fields or ["name", "modified", "owner"]
	allowed_standard = {"name", "creation", "modified", "modified_by", "owner", "docstatus"}
	result = []
	for fieldname in requested:
		if fieldname in allowed_standard:
			result.append(fieldname)
			continue
		field = meta.get_field(fieldname)
		if not field:
			raise ValueError(f"Unknown field: {fieldname}")
		if field.fieldtype == "Password" or fieldname not in permitted:
			raise ValueError(f"Field is not available through MCP: {fieldname}")
		result.append(fieldname)
	return list(dict.fromkeys(result))


def safe_filters(meta, filters: dict[str, Any] | None, permitted: set[str]) -> dict[str, Any]:
	if filters is None:
		return {}
	if not isinstance(filters, dict):
		raise ValueError("filters must be an object")
	allowed_standard = {"name", "creation", "modified", "modified_by", "owner", "docstatus"}
	for fieldname in filters:
		if fieldname in allowed_standard:
			continue
		if not meta.has_field(fieldname) or fieldname not in permitted:
			raise ValueError(f"Filter field is not available through MCP: {fieldname}")
	return filters


def safe_write_data(
	meta,
	data: dict[str, Any],
	permitted: set[str],
	*,
	parenttype: str | None = None,
) -> dict[str, Any]:
	if not isinstance(data, dict) or not data:
		raise ValueError("data must be a non-empty object")
	result = {}
	for fieldname, value in data.items():
		if fieldname in PROTECTED_FIELDS or fieldname == "doctype":
			continue
		if fieldname == "name":
			result[fieldname] = value
			continue
		field = meta.get_field(fieldname)
		if not field:
			raise ValueError(f"Unknown field: {fieldname}")
		if field.fieldtype == "Password" or field.read_only or fieldname not in permitted:
			raise ValueError(f"Field is not writable through MCP: {fieldname}")
		if field.fieldtype in {"Table", "Table MultiSelect"}:
			if not isinstance(value, list):
				raise ValueError(f"Child table field must be a list: {fieldname}")
			import frappe

			child_meta = frappe.get_meta(field.options)
			child_permitted = permitted_fields(field.options, "write", parenttype=parenttype or meta.name)
			result[fieldname] = [
				safe_write_data(
					child_meta,
					row,
					child_permitted,
					parenttype=parenttype or meta.name,
				)
				for row in value
			]
		else:
			result[fieldname] = value
	if not result:
		raise ValueError("data contains no writable fields")
	return result


def safe_document(doc, meta) -> dict[str, Any]:
	import frappe

	readable = permitted_fields(meta.name, "read")
	result = {
		key: doc.get(key)
		for key in ("name", "creation", "modified", "modified_by", "owner", "docstatus")
		if doc.get(key) is not None
	}
	for field in meta.fields:
		if field.fieldname not in readable or field.fieldtype == "Password":
			continue
		value = doc.get(field.fieldname)
		if field.fieldtype in {"Table", "Table MultiSelect"}:
			child_meta = frappe.get_meta(field.options)
			child_readable = permitted_fields(field.options, "read", parenttype=meta.name)
			result[field.fieldname] = [
				{
					key: row.get(key)
					for key in ("name", "idx", *child_readable)
					if row.get(key) is not None
					and (not child_meta.get_field(key) or child_meta.get_field(key).fieldtype != "Password")
				}
				for row in (value or [])
			]
		else:
			result[field.fieldname] = value
	return serializable(result)


def serializable(value: Any) -> Any:
	import frappe

	return json.loads(frappe.as_json(value))


def sanitize_for_audit(value: Any, *, max_length: int = 2000) -> str:
	def mask(item: Any) -> Any:
		if isinstance(item, dict):
			return {
				key: "***" if key.lower() in SENSITIVE_KEYS else mask(child) for key, child in item.items()
			}
		if isinstance(item, list):
			return [mask(child) for child in item[:50]]
		return item

	try:
		text = json.dumps(mask(value), ensure_ascii=False, default=str)
	except Exception:
		text = str(value)
	return text[:max_length]


def validate_text_file(file_name: str, content: str) -> tuple[str, bytes]:
	name = PurePath(file_name or "").name
	if not name or PurePath(name).suffix.lower() not in SAFE_FILE_EXTENSIONS:
		raise ValueError("Only .txt, .md, .csv and .json attachments are allowed")
	payload = (content or "").encode("utf-8")
	if not payload:
		raise ValueError("Attachment content cannot be empty")
	if len(payload) > 1024 * 1024:
		raise ValueError("Attachment content exceeds the 1 MB limit")
	return name, payload


def validate_docx_file(file_name: str, content_base64: str) -> tuple[str, bytes]:
	"""Validate a small, structurally valid Word document supplied as Base64."""
	name = PurePath(file_name or "").name
	if not name or PurePath(name).suffix.lower() != ".docx":
		raise ValueError("Only .docx Word attachments are allowed")
	if not isinstance(content_base64, str) or not content_base64.strip():
		raise ValueError("Word attachment content cannot be empty")
	try:
		payload = base64.b64decode(content_base64, validate=True)
	except (binascii.Error, ValueError) as exc:
		raise ValueError("Word attachment content must be valid Base64") from exc
	if not payload:
		raise ValueError("Word attachment content cannot be empty")
	if len(payload) > MAX_DOCX_BYTES:
		raise ValueError("Word attachment exceeds the 5 MB limit")
	if not payload.startswith(b"PK\x03\x04"):
		raise ValueError("Word attachment is not a valid DOCX package")
	try:
		with zipfile.ZipFile(io.BytesIO(payload)) as archive:
			names = set(archive.namelist())
			if not REQUIRED_DOCX_PARTS.issubset(names):
				raise ValueError("Word attachment is missing required DOCX parts")
			if len(names) > 500:
				raise ValueError("Word attachment contains too many package parts")
			if any(item.flag_bits & 0x1 for item in archive.infolist()):
				raise ValueError("Encrypted Word attachments are not allowed")
			if sum(item.file_size for item in archive.infolist()) > MAX_DOCX_UNCOMPRESSED_BYTES:
				raise ValueError("Word attachment expands beyond the 25 MB limit")
	except zipfile.BadZipFile as exc:
		raise ValueError("Word attachment is not a valid DOCX package") from exc
	return name, payload


def validate_xlsx_payload(payload: bytes) -> bytes:
	"""Validate a bounded, macro-free Open XML workbook package."""
	if not isinstance(payload, bytes) or not payload:
		raise ValueError("Spreadsheet attachment content cannot be empty")
	if len(payload) > MAX_XLSX_BYTES:
		raise ValueError("Spreadsheet attachment exceeds the 8 MB limit")
	if not payload.startswith(b"PK\x03\x04"):
		raise ValueError("Spreadsheet attachment is not a valid XLSX package")
	try:
		with zipfile.ZipFile(io.BytesIO(payload)) as archive:
			infos = archive.infolist()
			names = {item.filename for item in infos}
			if not REQUIRED_XLSX_PARTS.issubset(names):
				raise ValueError("Spreadsheet attachment is missing required XLSX parts")
			if len(infos) > 2000:
				raise ValueError("Spreadsheet attachment contains too many package parts")
			if any(item.flag_bits & 0x1 for item in infos):
				raise ValueError("Encrypted spreadsheet attachments are not allowed")
			if sum(item.file_size for item in infos) > MAX_XLSX_UNCOMPRESSED_BYTES:
				raise ValueError("Spreadsheet attachment expands beyond the 64 MB limit")
			for item in infos:
				part = PurePath(item.filename)
				if item.filename.startswith(("/", "\\")) or ".." in part.parts:
					raise ValueError("Spreadsheet attachment contains an unsafe package path")
				if (item.external_attr >> 16) & 0o170000 == 0o120000:
					raise ValueError("Spreadsheet attachment contains an unsupported symbolic link")
			lower_names = {name.lower() for name in names}
			if "xl/vbaproject.bin" in lower_names or any(
				name.startswith(("xl/activex/", "xl/embeddings/")) for name in lower_names
			):
				raise ValueError("Macro and embedded-object spreadsheet attachments are not allowed")
			for required_xml in REQUIRED_XLSX_PARTS:
				ElementTree.fromstring(archive.read(required_xml))
	except zipfile.BadZipFile as exc:
		raise ValueError("Spreadsheet attachment is not a valid XLSX package") from exc
	except ElementTree.ParseError as exc:
		raise ValueError("Spreadsheet attachment contains invalid workbook XML") from exc
	return payload


def validate_xlsx_file(file_name: str, content_base64: str) -> tuple[str, bytes]:
	"""Validate one .xlsx file supplied as Base64 and return its safe name and bytes."""
	name = PurePath(file_name or "").name
	if not name or PurePath(name).suffix.lower() != ".xlsx":
		raise ValueError("Only .xlsx spreadsheet attachments are allowed")
	if not isinstance(content_base64, str) or not content_base64.strip():
		raise ValueError("Spreadsheet attachment content cannot be empty")
	try:
		payload = base64.b64decode(content_base64, validate=True)
	except (binascii.Error, ValueError) as exc:
		raise ValueError("Spreadsheet attachment content must be valid Base64") from exc
	return name, validate_xlsx_payload(payload)


def extract_docx_text(payload: bytes) -> str:
	"""Extract paragraph text from a validated, bounded DOCX package."""
	if not isinstance(payload, bytes) or not payload or len(payload) > MAX_DOCX_BYTES:
		raise ValueError("Word attachment exceeds the 5 MB limit or is empty")
	if not payload.startswith(b"PK\x03\x04"):
		raise ValueError("Word attachment is not a valid DOCX package")
	try:
		with zipfile.ZipFile(io.BytesIO(payload)) as archive:
			names = set(archive.namelist())
			if not REQUIRED_DOCX_PARTS.issubset(names):
				raise ValueError("Word attachment is missing required DOCX parts")
			if len(names) > 500 or any(item.flag_bits & 0x1 for item in archive.infolist()):
				raise ValueError("Word attachment package is not supported")
			if sum(item.file_size for item in archive.infolist()) > MAX_DOCX_UNCOMPRESSED_BYTES:
				raise ValueError("Word attachment expands beyond the 25 MB limit")
			document_xml = archive.read("word/document.xml")
	except zipfile.BadZipFile as exc:
		raise ValueError("Word attachment is not a valid DOCX package") from exc

	try:
		root = ElementTree.fromstring(document_xml)
	except ElementTree.ParseError as exc:
		raise ValueError("Word attachment contains invalid document XML") from exc

	namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
	paragraphs = []
	character_count = 0
	for paragraph in root.iter(f"{namespace}p"):
		text = "".join(node.text or "" for node in paragraph.iter(f"{namespace}t")).strip()
		if not text:
			continue
		character_count += len(text)
		if character_count > MAX_DOCX_TEXT_CHARACTERS:
			raise ValueError("Word attachment text exceeds the 300,000 character limit")
		paragraphs.append(text)
	if not paragraphs:
		raise ValueError("Word attachment contains no readable text")
	return "\n".join(paragraphs)
