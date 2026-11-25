from __future__ import annotations

import frappe

TOOL_SLUG = "fetch_frappe_document"
INSTRUCTION_MARKER = "[IONE_FRAPPE_DOCUMENT_TOOL]"
FLOW_INSTRUCTIONS = f"""

{INSTRUCTION_MARKER}
When the user provides an https://docs.frappe.io URL, always call
`{TOOL_SLUG}` before summarizing or translating it. Use only the returned
Markdown as the source; never reconstruct missing content from memory. Preserve
the document hierarchy and links, translate into natural Chinese, and include
the original source URL. If the fetch fails, report the failure and stop instead
of creating Wiki records. Inspect Wiki DocTypes before writing, and use the
existing confirmation flow for every Wiki Space or Wiki Page change.
[/IONE_FRAPPE_DOCUMENT_TOOL]
""".strip()


def ensure_frappe_document_tool():
	if "flow" not in frappe.get_installed_apps():
		return
	if not frappe.db.exists("DocType", "Flow Tool") or not frappe.db.exists("DocType", "Flow Agent"):
		return

	description = (
		"Read one exact page from the official Frappe documentation site (docs.frappe.io) "
		"and return its title, canonical URL, and main article content as Markdown. "
		"Use this before translating, summarizing, or publishing a supplied Frappe docs URL. "
		"If it fails, do not guess the document content. This tool is read-only."
	)
	if frappe.db.exists("Flow Tool", TOOL_SLUG):
		tool = frappe.get_doc("Flow Tool", TOOL_SLUG)
		changed = False
		for field, value in {
			"title": "读取 Frappe 官方文档",
			"enabled": 1,
			"requires_confirmation": 0,
			"description": description,
		}.items():
			if tool.get(field) != value:
				tool.set(field, value)
				changed = True
		if changed:
			tool.save(ignore_permissions=True)
	else:
		frappe.get_doc(
			{
				"doctype": "Flow Tool",
				"title": "读取 Frappe 官方文档",
				"slug": TOOL_SLUG,
				"type": "Imported",
				"enabled": 1,
				"requires_confirmation": 0,
				"description": description,
				"import_path": "tongjianyun.integrations.flow_web_docs.fetch_frappe_document",
			}
		).insert(ignore_permissions=True)

	agent_name = frappe.db.get_value("Flow Agent", {"title": "Flow"}, "name")
	if not agent_name:
		return

	agent = frappe.get_doc("Flow Agent", agent_name)
	changed = False
	if TOOL_SLUG not in {row.tool for row in agent.tools if row.tool}:
		agent.append("tools", {"tool": TOOL_SLUG})
		changed = True
	if INSTRUCTION_MARKER not in (agent.instructions or ""):
		agent.instructions = f"{(agent.instructions or '').rstrip()}\n\n{FLOW_INSTRUCTIONS}".strip()
		changed = True
	if changed:
		agent.save(ignore_permissions=True)
