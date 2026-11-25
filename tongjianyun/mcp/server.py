from importlib import import_module

from tongjianyun.mcp.runtime import MCP

mcp = MCP(name="ione-manager")


@mcp.register(allow_guest=False)
def handle_mcp():
	"""Serve the I-ONE manager MCP endpoint for authenticated Frappe users."""
	from tongjianyun.mcp import tools  # noqa: F401

	_load_extension_tools()


def _load_extension_tools() -> None:
	"""Load MCP tools contributed by installed Frappe apps.

	Apps opt in through ``ione_mcp_tool_modules`` in their hooks. Importing a
	module is the registration boundary, so the core app does not need a hard
	dependency on any business application.
	"""
	import frappe

	for module_name in frappe.get_hooks("ione_mcp_tool_modules") or []:
		import_module(str(module_name))
