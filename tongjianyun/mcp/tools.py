from __future__ import annotations

import json
from typing import Any

import frappe
from bs4 import BeautifulSoup

from tongjianyun.mcp.audit import audited_tool
from tongjianyun.mcp.identity import as_verified_actor
from tongjianyun.mcp.runtime import ToolAnnotations
from tongjianyun.mcp.security import (
	doctype_allowed_by_scope,
	ensure_doctype_permission,
	extract_docx_text,
	permitted_fields,
	require_login,
	safe_document,
	safe_fields,
	safe_filters,
	safe_write_data,
	serializable,
	validate_docx_file,
	validate_order_by,
	validate_text_file,
	validate_xlsx_file,
	validate_xlsx_payload,
)
from tongjianyun.mcp.server import mcp
from tongjianyun.mcp.tongjianyun_analysis import generate_tongjianyun_recipe_analysis
from tongjianyun.mcp.tongjianyun_recipe import upsert_tongjianyun_recipe

READ_ONLY = ToolAnnotations(
	readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
DRAFT_WRITE = ToolAnnotations(
	readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
)
UPSERT_WRITE = ToolAnnotations(
	readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


@mcp.tool(annotations=READ_ONLY)
@as_verified_actor
@audited_tool("frappe_get_context", "读取")
def frappe_get_context(actor_token: str = "") -> dict[str, Any]:
	"""Return the authenticated user, roles, site and installed Frappe applications."""
	user = require_login()
	return {
		"user": user,
		"roles": frappe.get_roles(user),
		"site": getattr(frappe.local, "site", ""),
		"installed_apps": frappe.get_installed_apps(),
	}


@mcp.tool(annotations=READ_ONLY)
@as_verified_actor
@audited_tool("frappe_get_site_catalog", "读取")
def frappe_get_site_catalog(
	app: str = "",
	query: str = "",
	limit: int = 100,
	actor_token: str = "",
) -> dict[str, Any]:
	"""Return a compact app summary or permission-aware business DocType catalog.

	Args:
		app: Optional installed app name. Omit app and query for compact app summaries.
		query: Optional DocType name or module fragment for a detailed cross-app search.
		limit: Maximum visible DocTypes from 1 to 500.
		actor_token: Signed identity for the current Frappe login.
	"""
	require_login()
	installed_apps = tuple(frappe.get_installed_apps())
	selected_app = str(app or "").strip()
	if selected_app and selected_app not in installed_apps:
		raise ValueError(f"App is not installed on this site: {selected_app}")
	module_rows = frappe.get_all(
		"Module Def",
		fields=["name", "app_name"],
		filters={"app_name": ["in", list(installed_apps)]},
		limit_page_length=5000,
	)
	module_apps = {str(row.name): str(row.app_name) for row in module_rows}
	needle = str(query or "").strip().casefold()
	limit = max(1, min(int(limit), 500))
	summary_mode = not selected_app and not needle
	app_summaries = {
		app_name: {"app": app_name, "readable_doctype_count": 0, "samples": []}
		for app_name in installed_apps
	}
	doctypes = []
	for row in frappe.get_all(
		"DocType",
		filters={"istable": 0},
		fields=["name", "module", "is_submittable"],
		order_by="module asc, name asc",
		limit_page_length=5000,
	):
		name = str(row.name)
		module = str(row.module or "")
		app_name = module_apps.get(module, "custom")
		if selected_app and app_name != selected_app:
			continue
		if needle and needle not in name.casefold() and needle not in module.casefold():
			continue
		if not doctype_allowed_by_scope(name) or not frappe.has_permission(name, ptype="read"):
			continue
		label = frappe._(name)
		if summary_mode:
			summary = app_summaries.setdefault(
				app_name,
				{"app": app_name, "readable_doctype_count": 0, "samples": []},
			)
			summary["readable_doctype_count"] += 1
			if len(summary["samples"]) < 5:
				summary["samples"].append({"name": name, "label": label, "module": module})
			continue
		doctypes.append(
			{
				"name": name,
				"label": label,
				"module": module,
				"app": app_name,
				"can_read": True,
				"can_create": bool(frappe.has_permission(name, ptype="create")),
				"can_write": bool(frappe.has_permission(name, ptype="write")),
				"is_submittable": bool(row.is_submittable),
			}
		)
		if len(doctypes) >= limit:
			break
	summaries = [
		app_summaries[app_name]
		for app_name in (*installed_apps, *sorted(set(app_summaries) - set(installed_apps)))
	]
	return {
		"site": getattr(frappe.local, "site", ""),
		"user": frappe.session.user,
		"installed_apps": list(installed_apps),
		"mode": "summary" if summary_mode else "doctypes",
		"apps": summaries if summary_mode else [],
		"selected_app": selected_app or None,
		"query": query,
		"doctypes": doctypes,
		"count": (
			sum(summary["readable_doctype_count"] for summary in summaries)
			if summary_mode
			else len(doctypes)
		),
		"limit": limit,
	}


@mcp.tool(annotations=READ_ONLY)
@as_verified_actor
@audited_tool("frappe_search_doctypes", "读取")
def frappe_search_doctypes(query: str, limit: int = 20, actor_token: str = "") -> dict[str, Any]:
	"""Find non-child DocTypes that the authenticated user can read.

	Args:
		query: A DocType name fragment, such as Lead, Purchase or Wiki.
		limit: Maximum number of results from 1 to 50.
	"""
	require_login()
	limit = max(1, min(int(limit), 50))
	names = frappe.get_all(
		"DocType",
		filters={"name": ["like", f"%{(query or '').strip()}%"], "istable": 0},
		pluck="name",
		limit_page_length=limit * 4,
		order_by="name asc",
	)
	visible = [
		name
		for name in names
		if doctype_allowed_by_scope(name)
		and frappe.has_permission(name, ptype="read")
	][:limit]
	return {"query": query, "doctypes": visible, "count": len(visible)}


@mcp.tool(annotations=READ_ONLY)
@as_verified_actor
@audited_tool("frappe_get_doctype_meta", "读取")
def frappe_get_doctype_meta(doctype: str, actor_token: str = "") -> dict[str, Any]:
	"""Return safe field metadata for one readable business DocType.

	Args:
		doctype: Exact DocType name.
	"""
	meta = ensure_doctype_permission(doctype, "read")
	readable = permitted_fields(doctype, "read")
	writable = permitted_fields(doctype, "write") if frappe.has_permission(doctype, ptype="write") else set()
	fields = []
	for field in meta.fields:
		if field.fieldtype in {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Password"}:
			continue
		if field.fieldname not in readable and field.fieldname not in writable:
			continue
		fields.append(
			{
				"fieldname": field.fieldname,
				"label": field.label,
				"fieldtype": field.fieldtype,
				"options": field.options
				if field.fieldtype in {"Link", "Select", "Table", "Table MultiSelect"}
				else None,
				"required": bool(field.reqd),
				"read_only": bool(field.read_only),
				"readable": field.fieldname in readable,
				"writable": field.fieldname in writable and not field.read_only,
			}
		)
	return {
		"doctype": doctype,
		"title_field": meta.title_field,
		"search_fields": meta.search_fields,
		"is_submittable": bool(meta.is_submittable),
		"fields": fields,
	}


@mcp.tool(annotations=READ_ONLY)
@as_verified_actor
@audited_tool("frappe_list_documents", "读取")
def frappe_list_documents(
	doctype: str,
	filters: dict[str, Any] | None = None,
	fields: list[str] | None = None,
	order_by: str = "modified desc",
	limit: int = 20,
	start: int = 0,
	actor_token: str = "",
) -> dict[str, Any]:
	"""List a PAGE of documents using the current user's Frappe permissions.

	count/page_count is ONLY this page's size, never the total. For questions
	like '有多少学生/how many', use frappe_count_documents or total_count.
	Report the filters and permission scope; enabled students are not attendance.

	Args:
		doctype: Exact business DocType name.
		filters: Frappe filter object using field names and values.
		fields: Fields to return. Password fields are never available.
		order_by: One field and optional asc or desc direction.
		limit: Maximum number of records from 1 to 100.
		start: Zero-based record offset for permission-aware pagination.
	"""
	meta = ensure_doctype_permission(doctype, "read")
	readable = permitted_fields(doctype, "read")
	limit = max(1, min(int(limit), 100))
	start = max(0, min(int(start), 100000))
	validated_filters = safe_filters(meta, filters, readable)
	rows = frappe.get_list(
		doctype,
		filters=validated_filters,
		fields=safe_fields(meta, fields, readable),
		order_by=validate_order_by(meta, order_by, readable),
		limit_start=start,
		limit_page_length=limit + 1,
	)
	has_more = len(rows) > limit
	rows = rows[:limit]
	return {
		"doctype": doctype,
		"records": serializable(rows),
		"count": len(rows),
		"page_count": len(rows),
		"count_scope": "current_page_only",
		"total_count": _permission_aware_count(doctype, validated_filters),
		"filters": validated_filters,
		"permission_scope": "current_user",
		"start": start,
		"has_more": has_more,
		"next_start": start + len(rows) if has_more else None,
	}


def _permission_aware_count(doctype: str, filters: Any) -> int:
	"""Use Frappe's list count, including row permissions and distinct names."""
	from frappe.desk.reportview import get_count

	previous = frappe.local.form_dict
	try:
		frappe.local.form_dict = frappe._dict(
			doctype=doctype, filters=filters, distinct=1, limit=0
		)
		return int(get_count())
	finally:
		frappe.local.form_dict = previous


@mcp.tool(annotations=READ_ONLY)
@as_verified_actor
@audited_tool("frappe_count_documents", "读取")
def frappe_count_documents(
	doctype: str,
	filters: dict[str, Any] | None = None,
	actor_token: str = "",
) -> dict[str, Any]:
	"""Count ALL matching records visible to the current user, without pagination.

	Use for totals/how many/有多少/人数, not len(list records) or page count.
	For active student archives use Student with enabled=1; this is NOT actual
	attendance or meal participation. State filters and permission scope in answers.
	"""
	meta = ensure_doctype_permission(doctype, "read")
	filters = safe_filters(meta, filters, permitted_fields(doctype, "read"))
	return {
		"doctype": doctype,
		"total_count": _permission_aware_count(doctype, filters),
		"filters": filters,
		"count_scope": "all_matching_records",
		"permission_scope": "current_user",
	}


@mcp.tool(annotations=READ_ONLY)
@as_verified_actor
@audited_tool("frappe_get_document", "读取")
def frappe_get_document(doctype: str, name: str, actor_token: str = "") -> dict[str, Any]:
	"""Get one business document after checking document-level read permission.

	Args:
		doctype: Exact business DocType name.
		name: Document name.
	"""
	ensure_doctype_permission(doctype, "read")
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("read")
	meta = frappe.get_meta(doctype)
	return {"doctype": doctype, "document": safe_document(doc, meta)}


@mcp.tool(annotations=READ_ONLY)
@as_verified_actor
@audited_tool("frappe_list_attachments", "读取")
def frappe_list_attachments(
	doctype: str,
	document_name: str,
	include_text_content: bool = True,
	actor_token: str = "",
) -> dict[str, Any]:
	"""List a document's attachments and optionally read small UTF-8 text attachments.

	Args:
		doctype: Parent business DocType.
		document_name: Parent document name.
		include_text_content: Include content for .txt, .md, .csv and .json files up to 1 MB total.
	"""
	ensure_doctype_permission(doctype, "read")
	doc = frappe.get_doc(doctype, document_name)
	doc.check_permission("read")
	rows = frappe.get_all(
		"File",
		filters={"attached_to_doctype": doctype, "attached_to_name": document_name},
		fields=[
			"name",
			"file_name",
			"file_url",
			"is_private",
			"file_size",
			"creation",
			"modified",
		],
		order_by="creation asc",
		limit_page_length=50,
	)
	attachments = []
	remaining_text_bytes = 1024 * 1024
	for row in rows:
		item = serializable(row)
		file_name = str(row.get("file_name") or "")
		if (
			include_text_content
			and not str(row.get("file_url") or "").startswith(("http://", "https://"))
			and file_name.lower().endswith((".txt", ".md", ".csv", ".json"))
		):
			file_size = int(row.get("file_size") or 0)
			if 0 < file_size <= remaining_text_bytes:
				content = frappe.get_doc("File", row.name).get_content()
				if isinstance(content, bytes):
					for encoding in ("utf-8-sig", "utf-8", "gb18030"):
						try:
							content = content.decode(encoding)
							break
						except UnicodeDecodeError:
							continue
				if isinstance(content, str):
					encoded_size = len(content.encode("utf-8"))
					if encoded_size <= remaining_text_bytes:
						item["content"] = content
						remaining_text_bytes -= encoded_size
		attachments.append(item)
	return {"doctype": doctype, "name": document_name, "attachments": attachments, "count": len(attachments)}


@mcp.tool(annotations=READ_ONLY)
@as_verified_actor
@audited_tool("frappe_read_word_attachment", "读取")
def frappe_read_word_attachment(
	doctype: str,
	document_name: str,
	file_name: str,
	actor_token: str = "",
) -> dict[str, Any]:
	"""Read text from one small DOCX attachment after checking parent document permission.

	Args:
		doctype: Parent business DocType.
		document_name: Parent document name.
		file_name: Exact attached .docx file name returned by frappe_list_attachments.
	"""
	ensure_doctype_permission(doctype, "read")
	doc = frappe.get_doc(doctype, document_name)
	doc.check_permission("read")
	name = str(file_name or "").strip()
	if not name.lower().endswith(".docx"):
		raise ValueError("Only .docx Word attachments can be read")
	file_row = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": doctype,
			"attached_to_name": document_name,
			"file_name": name,
		},
		fields=["name", "file_name", "file_url", "file_size", "modified"],
		order_by="modified desc",
		limit_page_length=1,
	)
	if not file_row:
		frappe.throw(f"Word attachment {name} was not found on {doctype} {document_name}")
	row = file_row[0]
	if str(row.file_url or "").startswith(("http://", "https://")):
		frappe.throw("Remote Word attachments cannot be read through MCP")
	payload = frappe.get_doc("File", row.name).get_content()
	if isinstance(payload, str):
		payload = payload.encode("utf-8")
	text = extract_docx_text(bytes(payload))
	return {
		"doctype": doctype,
		"name": document_name,
		"file_name": row.file_name,
		"file_url": row.file_url,
		"characters": len(text),
		"content": text,
	}


@mcp.tool(annotations=READ_ONLY)
@as_verified_actor
@audited_tool("frappe_read_spreadsheet_attachment", "读取")
def frappe_read_spreadsheet_attachment(
	doctype: str,
	document_name: str,
	file_name: str,
	actor_token: str = "",
) -> dict[str, Any]:
	"""Read one validated .xlsx attachment after checking its parent document permission.

	This is a transport tool for the I-ONE Agent bridge. The bridge stages the decoded
	bytes inside the assigned workspace and never exposes the Base64 payload to the model.
	"""
	import base64

	ensure_doctype_permission(doctype, "read")
	doc = frappe.get_doc(doctype, document_name)
	doc.check_permission("read")
	name = str(file_name or "").strip()
	if not name.lower().endswith(".xlsx"):
		raise ValueError("Only .xlsx spreadsheet attachments can be read")
	file_row = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": doctype,
			"attached_to_name": document_name,
			"file_name": name,
		},
		fields=["name", "file_name", "file_url", "file_size", "modified"],
		order_by="modified desc",
		limit_page_length=1,
	)
	if not file_row:
		frappe.throw(f"Spreadsheet attachment {name} was not found on {doctype} {document_name}")
	row = file_row[0]
	if str(row.file_url or "").startswith(("http://", "https://")):
		frappe.throw("Remote spreadsheet attachments cannot be read through MCP")
	payload = frappe.get_doc("File", row.name).get_content()
	if isinstance(payload, str):
		payload = payload.encode("utf-8")
	payload = validate_xlsx_payload(bytes(payload))
	return {
		"doctype": doctype,
		"name": document_name,
		"file_name": row.file_name,
		"file_url": row.file_url,
		"file_size": len(payload),
		"modified": serializable(row.modified),
		"content_base64": base64.b64encode(payload).decode("ascii"),
	}


@mcp.tool(annotations=DRAFT_WRITE)
@as_verified_actor
@audited_tool("frappe_create_document", "写入")
def frappe_create_document(
	doctype: str, data: dict[str, Any], actor_token: str = ""
) -> dict[str, Any]:
	"""Create one draft business document with normal Frappe validations and permissions.

	Args:
		doctype: Exact business DocType name.
		data: Field values. Submission and protected system fields are not accepted.
	"""
	meta = ensure_doctype_permission(doctype, "create")
	payload = safe_write_data(meta, data, permitted_fields(doctype, "write"))
	payload["doctype"] = doctype
	savepoint = "ione_mcp_create"
	frappe.db.savepoint(savepoint)
	try:
		doc = frappe.get_doc(payload).insert()
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise
	return {"doctype": doctype, "name": doc.name, "docstatus": doc.docstatus}


@mcp.tool(annotations=DRAFT_WRITE)
@as_verified_actor
@audited_tool("frappe_update_document", "写入")
def frappe_update_document(
	doctype: str, name: str, data: dict[str, Any], actor_token: str = ""
) -> dict[str, Any]:
	"""Update one draft business document with normal Frappe validations and permissions.

	Args:
		doctype: Exact business DocType name.
		name: Existing document name.
		data: Writable field values. Submitted documents cannot be changed.
	"""
	meta = ensure_doctype_permission(doctype, "write")
	doc = frappe.get_doc(doctype, name)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw("MCP can update draft documents only")
	payload = safe_write_data(meta, data, permitted_fields(doctype, "write"))
	payload.pop("name", None)
	savepoint = "ione_mcp_update"
	frappe.db.savepoint(savepoint)
	try:
		doc.update(payload)
		doc.save()
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise
	return {"doctype": doctype, "name": doc.name, "modified": serializable(doc.modified)}


@mcp.tool(annotations=UPSERT_WRITE)
@as_verified_actor
@audited_tool("frappe_upsert_tongjianyun_recipe", "写入")
def frappe_upsert_tongjianyun_recipe(
	recipe: dict[str, Any],
	days: list[dict[str, Any]],
	actor_token: str = "",
) -> dict[str, Any]:
	"""Create or replace one complete draft Tongjianyun recipe atomically.

	The server generates every dish and ingredient row ID, rebuilds their
	relationships and verifies the saved row counts before returning.

	Args:
		recipe: Recipe metadata using recipeId, title, weekStart, weekEnd and optional source fields.
		days: Recipe days containing portions, dishes and dishIngredientRows.
		actor_token: Signed identity for the current Frappe login.
	"""
	return upsert_tongjianyun_recipe(recipe, days)


@mcp.tool(annotations=DRAFT_WRITE)
@as_verified_actor
@audited_tool("frappe_generate_tongjianyun_recipe_analysis", "写入")
def frappe_generate_tongjianyun_recipe_analysis(
	recipe_name: str,
	standard: dict[str, Any] | None = None,
	actor_token: str = "",
) -> dict[str, Any]:
	"""Generate the template-identical Tongjianyun recipe analysis workbook and attach it.

	Args:
		recipe_name: Exact Tongjianyun Recipe document name returned by the recipe upsert tool.
		standard: Optional nutrition-standard overrides. Omit to use the configured preschool profile.
		actor_token: Signed identity for the current Frappe login.
	"""
	return generate_tongjianyun_recipe_analysis(recipe_name, standard)


@mcp.tool(annotations=DRAFT_WRITE)
@as_verified_actor
@audited_tool("frappe_attach_text_file", "写入")
def frappe_attach_text_file(
	doctype: str,
	document_name: str,
	file_name: str,
	content: str,
	actor_token: str = "",
) -> dict[str, Any]:
	"""Attach a private UTF-8 text, Markdown, CSV or JSON file to a writable document.

	Args:
		doctype: Parent business DocType.
		document_name: Parent document name.
		file_name: Safe file name ending in .txt, .md, .csv or .json.
		content: UTF-8 text content, limited to 1 MB.
	"""
	ensure_doctype_permission(doctype, "write")
	doc = frappe.get_doc(doctype, document_name)
	doc.check_permission("write")
	name, payload = validate_text_file(file_name, content)
	from frappe.utils.file_manager import save_file

	file_doc = save_file(name, payload, doctype, document_name, is_private=1)
	return {"doctype": doctype, "name": document_name, "file": file_doc.file_url}


@mcp.tool(annotations=DRAFT_WRITE)
@as_verified_actor
@audited_tool("frappe_attach_word_file", "写入")
def frappe_attach_word_file(
	doctype: str,
	document_name: str,
	file_name: str,
	content_base64: str,
	actor_token: str = "",
) -> dict[str, Any]:
	"""Attach a private, validated Word .docx file to a writable business document.

	Args:
		doctype: Parent business DocType.
		document_name: Parent document name.
		file_name: Safe file name ending in .docx.
		content_base64: Base64-encoded DOCX package, limited to 5 MB.
	"""
	ensure_doctype_permission(doctype, "write")
	doc = frappe.get_doc(doctype, document_name)
	doc.check_permission("write")
	name, payload = validate_docx_file(file_name, content_base64)
	from frappe.utils.file_manager import save_file

	file_doc = save_file(name, payload, doctype, document_name, is_private=1)
	return {"doctype": doctype, "name": document_name, "file": file_doc.file_url}


@mcp.tool(annotations=DRAFT_WRITE)
@as_verified_actor
@audited_tool("frappe_attach_spreadsheet_file", "写入")
def frappe_attach_spreadsheet_file(
	doctype: str,
	document_name: str,
	file_name: str,
	content_base64: str,
	actor_token: str = "",
) -> dict[str, Any]:
	"""Attach a private, validated and macro-free .xlsx file to a writable document."""
	ensure_doctype_permission(doctype, "write")
	doc = frappe.get_doc(doctype, document_name)
	doc.check_permission("write")
	name, payload = validate_xlsx_file(file_name, content_base64)
	from frappe.utils.file_manager import save_file

	file_doc = save_file(name, payload, doctype, document_name, is_private=1)
	return {
		"doctype": doctype,
		"name": document_name,
		"file_name": name,
		"file_size": len(payload),
		"file": file_doc.file_url,
	}


@mcp.tool(annotations=DRAFT_WRITE)
@audited_tool("frappe_create_crm_lead_package", "创建线索")
def frappe_create_crm_lead_package(
	lead_data: dict[str, Any],
	analysis: dict[str, Any],
	task_title: str,
	task_description: str,
	actor_token: str,
	task_due_date: str | None = None,
	task_priority: str = "Medium",
) -> dict[str, Any]:
	"""Atomically create a CRM Lead, detailed Word analysis and assigned CRM follow-up task.

	The assignee is derived exclusively from the signed current Manager login identity. The caller
	cannot choose another user. Any failure rolls back the Lead, CRM Task and assignment together.

	Args:
		lead_data: Writable CRM Lead field values supported by current metadata.
		analysis: Detailed analysis with executive_summary, at least ten sections and optional sources.
		task_title: Specific follow-up action title, limited to 140 characters.
		task_description: Plain-text follow-up context and expected result.
		actor_token: Short-lived trusted identity token supplied in the Agent session context.
		task_due_date: Optional ISO date or datetime; defaults to three days from creation.
		task_priority: Low, Medium or High.
	"""
	from tongjianyun.mcp.identity import resolve_actor_user
	from tongjianyun.mcp.lead_analysis import create_lead_analysis_docx, validate_analysis

	lead_meta = ensure_doctype_permission("CRM Lead", "create")
	ensure_doctype_permission("CRM Task", "create")
	assignee = resolve_actor_user(actor_token)
	validate_analysis(analysis)
	lead_payload = safe_write_data(
		lead_meta,
		lead_data,
		permitted_fields("CRM Lead", "write"),
	)
	lead_payload["doctype"] = "CRM Lead"

	title = str(task_title or "").strip()
	if not title:
		raise ValueError("task_title is required")
	if len(title) > 140:
		raise ValueError("task_title cannot exceed 140 characters")
	description = BeautifulSoup(str(task_description or ""), "html.parser").get_text("\n", strip=True)
	if not description:
		description = "核实客户需求、关键联系人、预算、决策流程和下一步行动。"
	if len(description) > 6000:
		raise ValueError("task_description cannot exceed 6,000 characters")
	if task_priority not in {"Low", "Medium", "High"}:
		raise ValueError("task_priority must be Low, Medium or High")

	from frappe.utils import add_days, get_datetime, now_datetime, today

	due_date = get_datetime(task_due_date) if task_due_date else add_days(now_datetime(), 3)
	savepoint = "ione_mcp_create_lead_package"
	frappe.db.savepoint(savepoint)
	try:
		lead = frappe.get_doc(lead_payload).insert()
		customer_name = str(
			lead.get("organization")
			or lead.get("organization_name")
			or " ".join(
				part
				for part in (lead.get("first_name"), lead.get("middle_name"), lead.get("last_name"))
				if part
			).strip()
			or lead.get("lead_name")
			or lead.get("name")
		)
		docx = create_lead_analysis_docx(
			analysis,
			lead_name=lead.name,
			customer_name=customer_name,
			prepared_for=assignee,
		)
		task = frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": title,
				"description": description,
				"assigned_to": assignee,
				"priority": task_priority,
				"status": "Todo",
				"start_date": today(),
				"due_date": due_date,
				"reference_doctype": "CRM Lead",
				"reference_docname": lead.name,
			}
		).insert()
		from frappe.utils.file_manager import save_file

		file_doc = save_file(
			f"客户需求分析_{lead.name}.docx",
			docx,
			"CRM Lead",
			lead.name,
			is_private=1,
		)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise
	return {
		"doctype": "CRM Lead",
		"name": lead.name,
		"lead": lead.name,
		"analysis_file": file_doc.file_url,
		"task": task.name,
		"assignee": assignee,
		"due_date": serializable(task.due_date),
	}


@mcp.tool(annotations=DRAFT_WRITE)
@audited_tool("frappe_convert_lead_to_deal", "转换")
def frappe_convert_lead_to_deal(
	lead: str,
	deal_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
	"""Convert one CRM Lead to a CRM Deal through CRM's official conversion service.

	The operation is idempotent: when a Deal already references the Lead, that Deal is returned.

	Args:
		lead: Exact CRM Lead document name.
		deal_data: Optional writable CRM Deal values such as next_step or expected_closure_date.
	"""
	ensure_doctype_permission("CRM Lead", "write")
	ensure_doctype_permission("CRM Deal", "create")
	lead_doc = frappe.get_doc("CRM Lead", lead)
	lead_doc.check_permission("write")
	existing_deal = frappe.db.get_value("CRM Deal", {"lead": lead}, "name")
	if existing_deal:
		frappe.get_doc("CRM Deal", existing_deal).check_permission("read")
		return {"lead": lead, "deal": existing_deal, "created": False}
	if lead_doc.get("converted"):
		frappe.throw("Lead is marked as converted but no linked CRM Deal was found")

	payload = None
	if deal_data:
		deal_meta = frappe.get_meta("CRM Deal")
		payload = safe_write_data(deal_meta, deal_data, permitted_fields("CRM Deal", "write"))
		for protected_field in ("name", "lead", "contacts", "contact", "organization", "naming_series"):
			payload.pop(protected_field, None)
		if not payload:
			payload = None

	savepoint = "ione_mcp_convert_lead"
	frappe.db.savepoint(savepoint)
	try:
		from crm.fcrm.doctype.crm_lead.crm_lead import convert_to_deal

		deal = convert_to_deal(lead=lead, deal=payload)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise
	frappe.get_doc("CRM Deal", deal).check_permission("read")
	return {"lead": lead, "deal": deal, "created": True}


@mcp.tool(annotations=UPSERT_WRITE)
@audited_tool("frappe_upsert_deal_presentation", "生成演示")
def frappe_upsert_deal_presentation(
	deal: str,
	title: str,
	slides: list[dict[str, Any]],
	make_public: bool | None = None,
) -> dict[str, Any]:
	"""Create or update a Frappe Suite Slides presentation linked to one CRM Deal.

	The slide input is a bounded business-content schema. The server renders it into editable
	Suite Slides elements and reuses the Deal's linked presentation on repeated calls.

	Args:
		deal: Exact CRM Deal document name.
		title: Customer-facing presentation title.
		slides: Four to twenty slide objects using cover, section, content, metrics, timeline or closing layouts.
		make_public: Set public link access only when explicitly requested; omit to preserve the current setting.
	"""
	from tongjianyun.mcp.slides import build_presentation_slides
	from tongjianyun.setup.slides_integration import (
		ensure_deal_presentation_field,
		suite_slides_available,
	)

	if not suite_slides_available():
		frappe.throw("Frappe Suite Slides is not available on this site")

	ensure_deal_presentation_field()
	ensure_doctype_permission("CRM Deal", "write")
	deal_doc = frappe.get_doc("CRM Deal", deal)
	deal_doc.check_permission("write")
	presentation_title = " ".join(str(title or "").split())
	if not presentation_title or len(presentation_title) > 140:
		raise ValueError("title is required and must not exceed 140 characters")
	rendered_slides = build_presentation_slides(slides)

	linked_name = deal_doc.get("custom_customer_presentation")
	created = not bool(linked_name and frappe.db.exists("Presentation", linked_name))
	if created:
		ensure_doctype_permission("Presentation", "create")
		presentation = frappe.new_doc("Presentation")
		presentation.title = presentation_title
		presentation.theme = "Light"
		presentation.thumbnail = "/assets/suite/slides/frontend/images/layouts/light/thumbnail-3.webp"
	else:
		ensure_doctype_permission("Presentation", "write")
		presentation = frappe.get_doc("Presentation", linked_name)
		presentation.check_permission("write")
		presentation.title = presentation_title

	presentation.set("slides", [])
	for slide in rendered_slides:
		presentation.append("slides", slide)

	savepoint = "ione_mcp_deal_presentation"
	frappe.db.savepoint(savepoint)
	try:
		if created:
			presentation.insert()
		else:
			presentation.save()
		if deal_doc.get("custom_customer_presentation") != presentation.name:
			deal_doc.db_set("custom_customer_presentation", presentation.name)

		from suite.drive.overrides.file import File as DriveFile

		drive_file_name = DriveFile.get_for_doc("Presentation", presentation.name)
		if not drive_file_name:
			frappe.throw("Suite Slides did not create a backing Drive file")
		drive_file = frappe.get_doc("File", drive_file_name)
		if make_public is True:
			drive_file.share(user=None, read=True)
		elif make_public is False:
			drive_file.unshare("$GENERAL")
		is_public = bool(drive_file.is_public())
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise

	editor_path = f"/slides/presentation/{presentation.name}"
	slideshow_path = f"/slides/slideshow/{presentation.name}"
	return {
		"deal": deal_doc.name,
		"presentation": presentation.name,
		"title": presentation.title,
		"slide_count": len(rendered_slides),
		"created": created,
		"is_public": is_public,
		"editor_url": frappe.utils.get_url(editor_path),
		"slideshow_url": frappe.utils.get_url(slideshow_path),
	}


def _presentation_text(presentation_name: str) -> dict[str, Any] | None:
	if not presentation_name or not frappe.db.exists("Presentation", presentation_name):
		return None
	presentation = frappe.get_doc("Presentation", presentation_name)
	presentation.check_permission("read")
	slides = []
	for index, slide in enumerate(presentation.get("slides") or [], start=1):
		texts = []
		try:
			elements = json.loads(slide.get("elements") or "[]")
		except (TypeError, ValueError):
			elements = []
		for element in elements:
			content = str(element.get("content") or "") if isinstance(element, dict) else ""
			if content:
				text = BeautifulSoup(content, "html.parser").get_text(" ", strip=True)
				if text:
					texts.append(text)
		slides.append({"index": index, "text": "\n".join(texts)[:3000]})
	return {
		"name": presentation.name,
		"title": presentation.title,
		"modified": serializable(presentation.modified),
		"slides": slides,
	}


@mcp.tool(annotations=READ_ONLY)
@audited_tool("frappe_get_deal_video_sources", "读取视频资料")
def frappe_get_deal_video_sources(deal: str) -> dict[str, Any]:
	"""Read the bounded, permission-aware source package for one CRM Deal video.

	The package includes the Deal, attachment metadata, the latest Word proposal text and the
	linked Frappe Suite Slides text. Private file URLs are never fetched by the agent.

	Args:
		deal: Exact CRM Deal document name.
	"""
	ensure_doctype_permission("CRM Deal", "read")
	deal_doc = frappe.get_doc("CRM Deal", deal)
	deal_doc.check_permission("read")
	deal_meta = frappe.get_meta("CRM Deal")
	rows = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "CRM Deal", "attached_to_name": deal},
		fields=["name", "file_name", "file_url", "file_size", "is_private", "creation", "modified"],
		order_by="modified desc",
		limit_page_length=50,
	)
	attachments = serializable(rows)
	proposal = None
	docx_rows = [row for row in rows if str(row.file_name or "").lower().endswith(".docx")]
	# `rows` is already newest-first. Stable sorting only lifts formal proposal files
	# above other Word attachments while preserving that recency order.
	docx_rows.sort(key=lambda row: 0 if str(row.file_name or "").lower().startswith("proposal_") else 1)
	if docx_rows:
		row = docx_rows[0]
		if not str(row.file_url or "").startswith(("http://", "https://")):
			payload = frappe.get_doc("File", row.name).get_content()
			if isinstance(payload, str):
				payload = payload.encode("utf-8")
			proposal = {
				"file_name": row.file_name,
				"modified": serializable(row.modified),
				"content": extract_docx_text(bytes(payload)),
			}
	presentation = _presentation_text(str(deal_doc.get("custom_customer_presentation") or ""))
	return {
		"deal": safe_document(deal_doc, deal_meta),
		"attachments": attachments,
		"proposal": proposal,
		"presentation": presentation,
	}


@mcp.tool(annotations=UPSERT_WRITE)
@audited_tool("frappe_upsert_deal_video", "生成视频分镜")
def frappe_upsert_deal_video(
	deal: str,
	title: str,
	manifest: dict[str, Any],
) -> dict[str, Any]:
	"""Create or update one controlled promotional-video storyboard linked to a CRM Deal.

	The input is validated as business content only. It cannot contain React, JavaScript or shell code.
	Repeated calls reuse the video linked to the Deal and preserve previous rendered artifacts.

	Args:
		deal: Exact CRM Deal document name.
		title: Customer-facing video title.
		manifest: Bounded video manifest containing six to twelve approved scene objects.
	"""
	from tongjianyun.mcp.video import KIND_LABELS, TEMPLATE_LABELS, manifest_hash, normalize_video_manifest
	from tongjianyun.setup.video_integration import ensure_deal_video_field

	ensure_deal_video_field()
	ensure_doctype_permission("CRM Deal", "write")
	deal_doc = frappe.get_doc("CRM Deal", deal)
	deal_doc.check_permission("write")
	payload = dict(manifest or {})
	payload["title"] = title
	normalized = normalize_video_manifest(payload)
	linked_name = str(deal_doc.get("custom_customer_video") or "")
	created = not bool(linked_name and frappe.db.exists("I-ONE Deal Video", linked_name))
	if created:
		ensure_doctype_permission("I-ONE Deal Video", "create")
		video = frappe.new_doc("I-ONE Deal Video")
		video.deal = deal_doc.name
	else:
		ensure_doctype_permission("I-ONE Deal Video", "write")
		video = frappe.get_doc("I-ONE Deal Video", linked_name)
		video.check_permission("write")
		if video.status in {"已排队", "渲染中"}:
			frappe.throw("当前视频正在渲染, 不能修改分镜")

	video.title = normalized["title"]
	video.customer = normalized["customer"]
	video.brand = normalized["brand"]
	video.template = TEMPLATE_LABELS[normalized["template"]]
	video.aspect_ratio = normalized["aspect_ratio"]
	video.language = normalized["language"]
	video.call_to_action = normalized["call_to_action"]
	video.status = "待审核"
	video.progress = 0
	video.current_step = "分镜待确认"
	video.error_message = ""
	video.source_hash = manifest_hash(
		normalized,
		deal_doc.modified,
		deal_doc.get("custom_customer_presentation"),
	)
	video.set("scenes", [])
	for index, scene in enumerate(normalized["scenes"], start=1):
		video.append(
			"scenes",
			{
				"scene_order": index,
				"scene_type": KIND_LABELS[scene["kind"]],
				"title": scene["title"],
				"subtitle": scene["subtitle"],
				"bullets": "\n".join(scene["bullets"]),
				"narration": scene["narration"],
				"duration_seconds": scene["duration_seconds"],
				"asset_file": scene["asset_file"],
				"evidence": scene["evidence"],
			},
		)

	savepoint = "ione_mcp_deal_video"
	frappe.db.savepoint(savepoint)
	try:
		if created:
			video.insert()
		else:
			video.save()
		if deal_doc.get("custom_customer_video") != video.name:
			deal_doc.db_set("custom_customer_video", video.name)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise
	return {
		"deal": deal_doc.name,
		"video": video.name,
		"title": video.title,
		"status": video.status,
		"scene_count": len(video.scenes),
		"duration_seconds": video.duration_seconds,
		"created": created,
		"form_url": frappe.utils.get_url(f"/app/i-one-deal-video/{video.name}"),
	}


@mcp.tool(annotations=UPSERT_WRITE)
@audited_tool("frappe_submit_deal_video_render", "提交视频渲染")
def frappe_submit_deal_video_render(video: str, quality: str = "final") -> dict[str, Any]:
	"""Approve and enqueue one Deal video storyboard for asynchronous rendering.

	Args:
		video: Exact I-ONE Deal Video document name.
		quality: draft for 720p or final for 1080p.
	"""
	from tongjianyun.deal_video import queue_deal_video_render

	ensure_doctype_permission("I-ONE Deal Video", "write")
	return queue_deal_video_render(video, quality)


@mcp.tool(annotations=READ_ONLY)
@audited_tool("frappe_get_deal_video_render_status", "读取视频状态")
def frappe_get_deal_video_render_status(video: str) -> dict[str, Any]:
	"""Return progress and output links for one permission-visible Deal video.

	Args:
		video: Exact I-ONE Deal Video document name.
	"""
	ensure_doctype_permission("I-ONE Deal Video", "read")
	doc = frappe.get_doc("I-ONE Deal Video", video)
	doc.check_permission("read")
	return {
		"video": doc.name,
		"deal": doc.deal,
		"status": doc.status,
		"progress": doc.progress,
		"current_step": doc.current_step,
		"render_version": doc.render_version,
		"output_video": doc.output_video,
		"output_cover": doc.output_cover,
		"output_subtitles": doc.output_subtitles,
		"error_message": doc.error_message,
	}
