from __future__ import annotations

import time
from functools import wraps

from tongjianyun.mcp.security import sanitize_for_audit


def request_summary(arguments) -> str:
	summary = {}
	for key, value in arguments.items():
		if key in {"data", "deal_data", "lead_data"} and isinstance(value, dict):
			summary[key] = {"fields": sorted(value)}
		elif key == "recipe" and isinstance(value, dict):
			summary[key] = {
				"recipe_id": value.get("recipeId"),
				"fields": sorted(value),
			}
		elif key == "days" and isinstance(value, list):
			summary[key] = {"count": len(value)}
		elif key == "analysis" and isinstance(value, dict):
			summary[key] = {
				"sections": len(value.get("sections") or []),
				"sources": len(value.get("sources") or []),
			}
		elif key == "content":
			summary[key] = {"characters": len(value or "")}
		elif key == "content_base64":
			summary[key] = {"characters": len(value or "")}
		elif key == "slides" and isinstance(value, list):
			summary[key] = {
				"count": len(value),
				"layouts": [item.get("kind") for item in value if isinstance(item, dict)],
			}
		elif key == "filters" and isinstance(value, dict):
			summary[key] = {"fields": sorted(value)}
		else:
			summary[key] = value
	return sanitize_for_audit(summary)


def result_summary(result) -> str:
	if not isinstance(result, dict):
		return sanitize_for_audit({"result_type": type(result).__name__})
	summary = {
		key: result[key]
		for key in (
			"doctype",
			"name",
			"docstatus",
			"modified",
			"file",
			"count",
			"lead",
			"deal",
			"presentation",
			"slide_count",
			"created",
			"task",
			"assignee",
			"recipe_id",
			"day_count",
			"dish_count",
			"ingredient_count",
		)
		if key in result
	}
	if isinstance(result.get("records"), list):
		summary["record_names"] = [
			row.get("name") for row in result["records"][:20] if isinstance(row, dict) and row.get("name")
		]
	if isinstance(result.get("document"), dict):
		summary["document_name"] = result["document"].get("name")
	if "doctypes" in result:
		summary["doctypes"] = result["doctypes"]
	return sanitize_for_audit(summary)


def audited_tool(tool_name: str, operation: str):
	def decorator(fn):
		@wraps(fn)
		def wrapper(*args, **kwargs):
			started = time.monotonic()
			status = "成功"
			result = None
			error = ""
			try:
				result = fn(*args, **kwargs)
				return result
			except Exception as exc:
				status = "失败"
				error = str(exc)
				raise
			finally:
				write_audit_log(
					tool_name=tool_name,
					operation=operation,
					status=status,
					duration_ms=round((time.monotonic() - started) * 1000),
					arguments=kwargs or {f"arg_{index}": value for index, value in enumerate(args)},
					result=result,
					error=error,
				)

		return wrapper

	return decorator


def write_audit_log(
	*,
	tool_name: str,
	operation: str,
	status: str,
	duration_ms: int,
	arguments,
	result,
	error: str,
) -> None:
	try:
		import frappe

		doctype = str(
			arguments.get("doctype")
			or ("CRM Lead" if arguments.get("lead") or arguments.get("lead_data") else "")
		)
		target_name = str(
			arguments.get("name") or arguments.get("document_name") or arguments.get("lead") or ""
		)
		frappe.get_doc(
			{
				"doctype": "I-ONE MCP Audit Log",
				"user": frappe.session.user,
				"tool_name": tool_name,
				"operation": operation,
				"status": status,
				"duration_ms": duration_ms,
				"target_doctype": doctype,
				"target_name": target_name,
				"request_summary": request_summary(arguments),
				"result_summary": result_summary(result),
				"error_message": error[:1000],
			}
		).insert(ignore_permissions=True)
	except Exception:
		# Audit failures must not make normal Frappe operations unavailable.
		try:
			frappe.log_error(title="I-ONE MCP audit log failed", message=frappe.get_traceback())
		except Exception:
			pass
