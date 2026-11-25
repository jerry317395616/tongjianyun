(() => {
	frappe.provide("frappe.meal_planning");
	frappe.meal_planning = frappe.meal_planning || {};
	frappe.meal_planning.open_weekly_report = (listview) => {
		const filters = listview?.filter_area?.get?.() || [];
		let batch = filters.find((row) => row[1] === "custom_meal_batch" && row[2] === "=")?.[3];
		if (!batch) batch = new URLSearchParams(window.location.search).get("custom_meal_batch");
		if (typeof batch !== "string" || !batch) {
			return frappe.set_route("query-report", "Tongjianyun Weekly Menu");
		}
		const args = batch.startsWith("MEAL-WEEK-") ? { week_name: batch } : { plan_batch: batch };
		return frappe.set_route("query-report", "Tongjianyun Weekly Menu", args);
	};
	const settings = frappe.listview_settings["Production Plan"] || {};
	const previous = settings.onload;
	frappe.listview_settings["Production Plan"] = {
		...settings,
		onload(listview) {
			if (previous) previous.call(this, listview);
			listview.page.add_inner_button("周食谱表", () => frappe.meal_planning.open_weekly_report(listview));
		},
	};
})();
