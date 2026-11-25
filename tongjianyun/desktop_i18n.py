from __future__ import annotations

import json

import frappe

APP_TITLES = {
	"frappe": "系统",
	"erpnext": "ERPNext",
	"education": "教育管理",
	"hrms": "人事管理",
	"tongjianyun": "童健云",
}

HIDDEN_APPS_CONFIG_KEY = "ione_hidden_apps"


def ensure_desktop_app_labels() -> dict[str, int]:
	"""Persist localized labels for sites using the Desktop Icons page."""
	if not frappe.db.exists("DocType", "Desktop Icon"):
		return {"updated": 0}

	icons = frappe.get_all(
		"Desktop Icon",
		filters={"icon_type": "App", "app": ("in", tuple(APP_TITLES))},
		fields=["name", "label", "app"],
		limit_page_length=0,
	)
	updated = 0
	for icon in icons:
		label = APP_TITLES.get(icon.app)
		if not label or icon.label == label:
			continue
		frappe.db.set_value(
			"Desktop Icon",
			icon.name,
			"label",
			label,
			update_modified=False,
		)
		updated += 1

	if updated:
		# These are hashes keyed by user. Removing the complete hashes ensures
		# existing sessions also receive the new label on their next reload.
		frappe.cache.delete_key("desktop_icons")
		frappe.cache.delete_key("bootinfo")

	return {"updated": updated}


def localize_app_titles(bootinfo) -> None:
	"""Localize app titles and apply site-scoped Apps desktop visibility."""
	hidden_apps = get_hidden_apps()
	# Hiding an app only changes navigation visibility; it does not revoke any
	# permissions. Apply this display choice to Administrator as well so the
	# selected apps stay out of the app picker for every account.
	visible_apps = []
	for app in getattr(bootinfo, "app_data", None) or []:
		app_name = app.get("app_name")
		if app_name in APP_TITLES:
			app["app_title"] = APP_TITLES[app_name]
		if app_name in hidden_apps:
			continue
		visible_apps.append(app)
	bootinfo.app_data = visible_apps

	# Keep the alternative "Desktop Icons" layout consistent with the Apps
	# desktop. Removing the records here also prevents an old saved layout from
	# re-introducing a site-hidden application.
	desktop_icons = getattr(bootinfo, "desktop_icons", None)
	if isinstance(desktop_icons, (list, tuple)):
		bootinfo.desktop_icons = [
			icon for icon in desktop_icons if icon.get("app") not in hidden_apps
		]


def get_hidden_apps() -> set[str]:
	"""Return app names hidden by this site's ``site_config.json``."""
	config = getattr(frappe, "conf", None) or {}
	raw_value = config.get(HIDDEN_APPS_CONFIG_KEY) or []
	if isinstance(raw_value, str):
		try:
			raw_value = json.loads(raw_value)
		except json.JSONDecodeError:
			raw_value = raw_value.split(",")
	if not isinstance(raw_value, (list, tuple, set)):
		return set()
	return {str(app).strip() for app in raw_value if str(app).strip()}
