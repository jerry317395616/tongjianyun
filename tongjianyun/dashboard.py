from __future__ import annotations

from typing import Any

import frappe
from frappe.desk.doctype.dashboard_chart.dashboard_chart import get as get_frappe_dashboard_chart

from tongjianyun.dashboard_labels import localize_chart_config


@frappe.whitelist()
def get_dashboard_chart(
	chart_name: str | None = None,
	chart: str | dict[str, Any] | None = None,
	no_cache: bool | int | None = None,
	filters: str | list | dict[str, Any] | None = None,
	from_date: str | None = None,
	to_date: str | None = None,
	timespan: str | None = None,
	time_interval: str | None = None,
	heatmap_year: str | int | None = None,
	refresh: bool | int | None = None,
):
	config = get_frappe_dashboard_chart(
		chart_name=chart_name,
		chart=chart,
		no_cache=no_cache,
		filters=filters,
		from_date=from_date,
		to_date=to_date,
		timespan=timespan,
		time_interval=time_interval,
		heatmap_year=heatmap_year,
		refresh=refresh,
	)
	return localize_chart_config(config, getattr(frappe.local, "lang", None))
