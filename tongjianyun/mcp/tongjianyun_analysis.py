from __future__ import annotations

from typing import Any

from tongjianyun.mcp.security import ensure_doctype_permission


def generate_tongjianyun_recipe_analysis(
	recipe_name: str,
	standard: dict[str, Any] | None = None,
) -> dict[str, Any]:
	"""Generate and attach a permission-aware Excel analysis for one recipe."""

	import frappe

	if "tongjianyun" not in frappe.get_installed_apps():
		raise ValueError("Tongjianyun is not installed on this site")
	import tongjianyun

	if getattr(tongjianyun, "REPORTS_ONLY", False):
		raise ValueError("童健云现仅提供只读报表。请从周食谱表进入食谱分析并下载。")
	ensure_doctype_permission("Tongjianyun Recipe", "read")
	name = str(recipe_name or "").strip()
	if not name:
		raise ValueError("recipe_name is required")
	doc = frappe.get_doc("Tongjianyun Recipe", name)
	doc.check_permission("read")
	from tongjianyun.recipe_analysis import create_and_attach_recipe_analysis

	return create_and_attach_recipe_analysis(doc.name, standard=standard)
