"""Site-level navigation for the Tongjianyun multi-app desk.

The framework owns the three-level navigation model:

    application dock -> module sidebar -> feature link

This module only adds site-level dock entries for applications that do not ship a
dock yet and makes the ERPNext Home workspace the default landing point.  It does
not alter permissions or remove any doctypes; the normal Frappe reachability
checks continue to filter every item for the signed-in user.
"""

from __future__ import annotations

import frappe
from werkzeug.exceptions import HTTPException
from werkzeug.wrappers import Response


APP_DOCKS = {
	"frappe": (
		{
			"link_type": "Sidebar",
			"link_to": "Setup",
			"title": "首页",
			"icon": "house",
		},
	),
	"erpnext": (
		{
			"link_type": "Sidebar",
			"link_to": "Setup",
			"title": "首页",
			"icon": "house",
		},
	),
	"hrms": (
		{
			"link_type": "Sidebar",
			"link_to": "Setup",
			"title": "首页",
			"icon": "house",
		},
	),
	"education": (
		{
			"link_type": "Sidebar",
			"link_to": "Setup",
			"title": "首页",
			"icon": "house",
		},
	),
	"tongjianyun": (
		{
			"link_type": "Sidebar",
			"link_to": "Setup",
			"title": "首页",
			"icon": "house",
		},
	),
}

HIDDEN_APPS = {"tongjianyun", "ione_agent", "ione_harness_launcher", "dify_launcher"}

APP_TITLES = {
	"frappe": "系统",
	"erpnext": "数智管理",
	"hrms": "人力资源",
	"education": "教育管理",
	"tongjianyun": "膳食管理",
}

# Use an explicit education icon for the top-level app item.  The stored
# sidebar metadata currently contains the non-standard ``education`` icon
# name, which does not render in Frappe's Lucide icon set.
APP_ICONS = {
	"education": "graduation-cap",
}

MODULE_TITLES = {
	"Accounts": "财务",
	"Assets": "资产",
	"Automation": "自动化",
	"Build": "开发构建",
	"Buying": "采购",
	"Contacts": "联系人",
	"CRM": "客户关系",
	"Data": "数据管理",
	"Education": "教育管理",
	"Email": "邮件",
	"Expenses": "费用",
	"Geo": "地理位置",
	"HR Setup": "人事设置",
	"Integrations": "集成",
	"Leaves": "休假",
	"Manufacturing": "制造",
	"Payroll": "薪资",
	"Performance": "绩效",
	"Printing": "打印",
	"Projects": "项目",
	"Quality": "质量",
	"Recruitment": "招聘",
	"Selling": "销售",
	"Setup": "系统设置",
	"Shift and Attendance": "考勤与排班",
	"Stock": "库存",
	"Support": "支持",
	"System": "系统管理",
	"Tax and Benefits": "税务与福利",
	"Tenure": "任职管理",
	"Tongjianyun": "童健云",
	"Users": "用户管理",
	"Website": "网站",
	"Workflow": "工作流",
}

HIDDEN_MODULES = {"I ONE AI", "I ONE Mobile", "I-ONE Agent"}

DEFAULT_APP = "erpnext"


class DeskLandingRedirect(HTTPException):
	"""HTTP redirect used by the request hook before the desk renderer runs."""

	code = 302

	def __init__(self, location: str):
		super().__init__()
		self.location = location

	def get_response(self, environ=None):
		return Response(
			status=self.code,
			headers={"Location": self.location, "Cache-Control": "no-store"},
		)


def _ensure_app_dock(app: str, entries: tuple[dict, ...]) -> bool:
	"""Keep one Home entry on every visible app rail.

	The standard dock is never edited. Site-level reference rows hide its other entries,
	so app updates remain safe and the original destinations stay available from the unified
	Sidebar below. This also hides stale site-added entries from earlier navigation versions.
	"""
	if app not in frappe.get_installed_apps():
		return False

	dock_name = frappe.db.get_value(
		"Dock",
		{"app": app, "user": "", "standard": 0},
		"name",
	)
	if dock_name:
		dock = frappe.get_doc("Dock", dock_name)
	else:
		dock = frappe.get_doc(
		{
			"doctype": "Dock",
			"app": app,
			"user": "",
			"standard": 0,
			"items": [],
		}
	)

	standard = frappe.db.get_value("Dock", {"app": app, "standard": 1}, "name")
	standard_rows = frappe.get_all(
		"Dock Item",
		filters={"parent": standard},
		fields=["link_type", "link_to", "url"],
		order_by="idx asc",
		limit_page_length=0,
	) if standard else []
	standard_keys = {(row.link_type, row.link_to, row.url) for row in standard_rows}
	entry_keys = {(entry.get("link_type"), entry.get("link_to"), entry.get("url")) for entry in entries}
	existing = {(row.link_type, row.link_to, row.url): row for row in dock.items}
	changed = False
	# Add reference rows for every standard destination, hiding them at the site layer.
	for key in standard_keys:
		row = existing.get(key)
		if not row:
			row = dock.append("items", {"link_type": key[0], "link_to": key[1], "url": key[2], "hidden": 1})
			existing[key] = row
			changed = True
		elif key not in entry_keys and not row.hidden:
			row.hidden = 1
			changed = True

	# Hide all earlier site-added entries, then expose exactly the Home destination.
	for key, row in existing.items():
		if key not in entry_keys and not row.hidden:
			row.hidden = 1
			changed = True
	for entry in entries:
		key = (entry.get("link_type"), entry.get("link_to"), entry.get("url"))
		row = existing.get(key)
		if not row:
			row = dock.append("items", {**entry, "added": 1, "hidden": 0})
			existing[key] = row
			changed = True
		else:
			for field in ("title", "icon"):
				if getattr(row, field, None) != entry.get(field):
					setattr(row, field, entry.get(field))
					changed = True
			if row.hidden:
				row.hidden = 0
				changed = True

	if changed:
		dock.save(ignore_permissions=True)
	return changed


def _feature_item(item: dict) -> dict | None:
	"""Copy a navigable sidebar row into the unified Setup sidebar."""
	if item.get("type") != "Link" or item.get("link_type") not in {"DocType", "Page", "Report", "Dashboard", "Workspace", "URL"}:
		return None
	fields = (
		"type", "label", "link_type", "link_to", "icon", "child", "indent",
		"keep_closed", "url", "show_arrow", "filters", "route_options",
		"navigate_to_tab", "open_in_new_tab",
	)
	return {field: item.get(field) for field in fields if item.get(field) is not None}


def _item_signature(row: dict) -> dict:
	"""Compare sidebar rows by meaningful values, ignoring framework defaults."""
	fields = (
		"type", "label", "link_type", "link_to", "icon", "child", "indent",
		"keep_closed", "url", "show_arrow", "filters", "route_options",
		"navigate_to_tab",
	)
	signature = {
		field: row.get(field)
		for field in fields
		if row.get(field) not in (None, "", 0, False, [])
	}
	if row.get("type") == "Section Break":
		for field in ("link_type", "link_to", "url"):
			signature.pop(field, None)
	return signature


def _build_unified_sidebar_items(existing_sidebar: bool) -> list[dict]:
	"""Build the generated rows without recursively consuming the generated Setup shell."""
	from frappe.boot import get_module_sidebars

	sidebars = get_module_sidebars()
	if existing_sidebar and "Setup" in sidebars:
		source_setup = sidebars.pop("Setup")
		source_items = source_setup.get("items", [])
		setup_labels = {
			f"{APP_TITLES['erpnext']}  →  {MODULE_TITLES['Setup']}",
			MODULE_TITLES["Setup"],
		}
		try:
			start = next(i for i, item in enumerate(source_items) if item.get("label") in setup_labels)
		except StopIteration:
			start = -1
		setup_features = []
		if start >= 0:
			for item in source_items[start + 1 :]:
				if item.get("type") == "Section Break":
					break
				if item.get("link_type") == "Workspace" and item.get("link_to") not in {"Home", "ERPNext Settings"}:
					break
				feature = _feature_item(item)
				if feature:
					setup_features.append(feature)
		if setup_features:
			sidebars["Setup"] = {
				"app": "erpnext",
				"label": MODULE_TITLES["Setup"],
				"header_icon": "house",
				"items": setup_features,
			}

	items = []
	last_app = None
	for module, sidebar in sorted(
		sidebars.items(),
		key=lambda pair: (APP_TITLES.get(pair[1].get("app"), pair[1].get("app") or ""), pair[0]),
	):
		app = sidebar.get("app")
		if app in HIDDEN_APPS or module in HIDDEN_MODULES:
			continue
		feature_items = [_feature_item(item) for item in sidebar.get("items", [])]
		feature_items = [item for item in feature_items if item]
		if app == "tongjianyun" and module == "Tongjianyun":
			allowed_pages = [
				("Page", "weekly-recipe-calendar"),
				("Page", "weekly-recipe-nutrition-sheet"),
			]
			available = {
				(item.get("link_type"), item.get("link_to")): item
				for item in feature_items
			}
			feature_items = [available[key] for key in allowed_pages if key in available]
			calendar_item = {
				"type": "Link",
				"label": "周食谱日历",
				"link_type": "Page",
				"link_to": "weekly-recipe-calendar",
				"icon": "calendar-days",
				"child": 1,
				"open_in_new_tab": 0,
			}
			if not any(item.get("link_to") == calendar_item["link_to"] for item in feature_items):
				feature_items.append(calendar_item)
		if not feature_items:
			continue
		app_title = APP_TITLES.get(app, app or "应用")
		module_title = MODULE_TITLES.get(module, sidebar.get("label") or module)
		if app != last_app:
			items.append(
				{
					"type": "Link",
					"label": app_title,
					"link_type": "URL",
					"url": f"/desk/home?app={app}",
					"icon": APP_ICONS.get(app) or sidebar.get("header_icon") or "folder",
					"keep_closed": 0,
				}
			)
			last_app = app
		items.append(
			{
				"type": "Section Break",
				"label": module_title,
				"icon": sidebar.get("header_icon") or "folder",
				"indent": 1,
				"collapsible": 1,
				"keep_closed": 0,
			}
		)
		for feature in feature_items:
			feature["child"] = 1
		items.extend(feature_items)
	return items


def _ensure_unified_sidebar() -> bool:
	"""Build the site Home sidebar as Application -> Module -> Feature.

	Each module is rendered as a collapsible section whose label includes its application;
	its existing feature links are copied unchanged, so routing and permissions continue to
	be handled by Frappe's normal sidebar resolver.
	"""
	if not frappe.db.exists("DocType", "Sidebar") or not frappe.db.exists("Module Def", "Setup"):
		return False

	current = frappe.db.get_value("Sidebar", "Setup", ["module", "app", "standard"], as_dict=True)
	existing_sidebar = bool(current)
	if current and current.standard:
		return False
	items = _build_unified_sidebar_items(existing_sidebar)

	if current:
		sidebar_doc = frappe.get_doc("Sidebar", "Setup")
	else:
		sidebar_doc = frappe.get_doc({"doctype": "Sidebar", "title": "Setup", "module": "Setup", "app": "erpnext", "standard": 0})
	old = [row.as_dict() for row in sidebar_doc.items]
	new_signature = [_item_signature(row) for row in items]
	old_signature = [_item_signature(row) for row in old]
	if old_signature == new_signature:
		return False
	sidebar_doc.set("items", items)
	sidebar_doc.header_icon = "house"
	# Some optional Education links intentionally point at doctypes that are not installed on
	# every site. Frappe drops those rows during permission resolution; skip insert-time link
	# validation so the remaining reachable features are still available.
	sidebar_doc.flags.ignore_links = True
	if not existing_sidebar:
		sidebar_doc.insert(ignore_permissions=True, ignore_links=True)
	else:
		sidebar_doc.save(ignore_permissions=True)
	return True


def ensure_unified_navigation() -> dict[str, object]:
	"""Ensure app rails, the unified Home sidebar and the default landing workspace are present."""
	if not frappe.db.exists("DocType", "Dock"):
		return {"docks_changed": [], "users_changed": []}

	docks_changed = []
	for app, entries in APP_DOCKS.items():
		if _ensure_app_dock(app, entries):
			docks_changed.append(app)

	sidebar_changed = _ensure_unified_sidebar()

	users_changed = []
	if frappe.db.exists("Workspace", "Home"):
		users = frappe.get_all(
			"User",
			filters={"user_type": "System User", "enabled": 1},
			pluck="name",
			limit_page_length=0,
		)
		for user in users:
			user_changed = False
			if frappe.db.get_value("User", user, "default_workspace") != "Home":
				frappe.db.set_value("User", user, "default_workspace", "Home", update_modified=False)
				user_changed = True
			if frappe.db.get_value("User", user, "default_app") != DEFAULT_APP:
				frappe.db.set_value("User", user, "default_app", DEFAULT_APP, update_modified=False)
				user_changed = True
			if user_changed:
				users_changed.append(user)

	if docks_changed or users_changed or sidebar_changed:
		frappe.db.commit()

	return {"docks_changed": docks_changed, "sidebar_changed": sidebar_changed, "users_changed": users_changed}


def redirect_desk_landing() -> None:
	"""Open the workbench for signed-in desk users at the site's entry URLs."""
	request = getattr(frappe.local, "request", None)
	if not request or request.method not in {"GET", "HEAD"}:
		return

	if request.path.rstrip("/") not in {"", "/desk", "/app"}:
		return

	if getattr(frappe.session, "user", "Guest") in {"Guest", ""}:
		return
	if frappe.session.data.get("user_type") != "System User":
		return

	raise DeskLandingRedirect("/desk/home")
