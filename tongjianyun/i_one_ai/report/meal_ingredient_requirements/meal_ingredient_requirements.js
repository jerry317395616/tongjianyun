(() => {
	const reportName = "Meal Ingredient Requirements";
	const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
	const selectedWeek = (report) => !report.get_filter_value("plan_batch") && (report.get_filter_value("week_name") || report.data?.[0]?.week_name);
	const selectedBatch = (report) => !report.get_filter_value("week_name") && (report.get_filter_value("plan_batch") || report.data?.[0]?.plan_batch);
	const sourceFilters = (report) => selectedBatch(report)
		? { plan_batch: selectedBatch(report), ...(report.get_filter_value("week_start") ? { week_start: report.get_filter_value("week_start") } : {}) }
		: { week_name: selectedWeek(report) };
	async function changeSource(report, field) {
		if (report._no_refresh || report.__meal_switching_source) return;
		report.__meal_switching_source = true;
		try {
			if (report.get_filter_value(field)) {
				const other = ["week_name", "plan_batch", "week_start"].filter((key) => key !== field && report.get_filter_value(key));
				if (other.length) await report.set_filter_value(Object.fromEntries(other.map((key) => [key, ""])));
			}
		} finally {
			report.__meal_switching_source = false;
		}
		return report.refresh(true);
	}

	frappe.query_reports[reportName] = {
		filters: [
			{ fieldname: "week_name", label: __("周食谱"), fieldtype: "Link", options: "Meal Planning Week",
				on_change(report) { return changeSource(report, "week_name"); } },
			{ fieldname: "plan_batch", label: __("生产计划批次"), fieldtype: "Data",
				on_change(report) { return changeSource(report, "plan_batch"); } },
			{ fieldname: "week_start", label: __("周开始日期"), fieldtype: "Date",
				on_change(report) { return changeSource(report, "week_start"); } },
		],
		async onload(report) {
			report.page.set_title(__("食材需求明细（计划供餐）"));
			report.page.add_inner_button(__("查看计划"), () => {
				const batch = selectedBatch(report);
				if (batch) return frappe.set_route("List", "Production Plan", { custom_meal_batch: batch });
				const week = selectedWeek(report);
				if (!week) return frappe.msgprint(__("请先选择可查看的周食谱。"));
				frappe.set_route("Form", "Meal Planning Week", week);
			});
			report.page.add_inner_button(__("周食谱表"), () => {
				if (!selectedWeek(report) && !selectedBatch(report)) return frappe.msgprint(__("请先选择可查看的周食谱。"));
				frappe.set_route("query-report", "Tongjianyun Weekly Menu", sourceFilters(report));
			});
			if (report.get_filter_value("week_name") || selectedBatch(report) || report.get_filter_value("week_start")) return;
			try {
				const weeks = await frappe.db.get_list("Meal Planning Week", {
					fields: ["name"], filters: { docstatus: ["<", 2] },
					order_by: "week_start desc, modified desc", limit: 1,
				});
				if (weeks[0]?.name && !report.get_filter_value("week_name") && !selectedBatch(report) && !report.get_filter_value("week_start")) {
					await report.set_filter_value("week_name", weeks[0].name);
				}
			} catch (error) {
				frappe.msgprint({ title: __("读取周食谱失败"), indicator: "red",
					message: escape(error?.message || "无法读取可查看的周食谱，请检查权限后重试。") });
			}
		},
		get_datatable_options(options) {
			return { ...options, inlineFilters: false };
		},
		after_datatable_render(datatable) {
			const report = frappe.query_report;
			if (report.report_name !== reportName || report.datatable !== datatable) return;
			const wrapper = $(datatable.wrapper);
			wrapper.children(".meal-live-detail-note").remove();
			$("<div class=\"meal-live-detail-note text-muted\" style=\"padding:8px 0 16px\">")
				.text(selectedBatch(report)
					? "历史生产计划仅展示每名幼儿的配方带量。历史供餐人数未确认，人数及备料总量留空；计算基准1不作为供餐人数。各食材保留配方单位，克与毫升不混算。"
					: "备料总量＝每名幼儿带量×该餐有效计划供餐人数；已批准的单餐变更以变更后安排计算，整餐停供不计入需求。人数属于计划供餐人数，不代表当天实际出勤、实际进餐或摄入。各食材保留配方单位，克与毫升不混算；该表为食材需求，采购量还需核对重量口径、库存和待到货。")
				.prependTo(wrapper);
		},
		formatter(value, row, column, data, default_formatter) {
			if (["per_child_qty", "headcount", "total_qty"].includes(column.fieldname)) {
				if (value === null || value === undefined || value === "") return "—";
				if (Number.isFinite(Number(value))) {
					return `<span style="display:block;text-align:right">${Number(value).toLocaleString("zh-CN", {
						maximumFractionDigits: column.fieldname === "headcount" ? 0 : 6,
					})}</span>`;
				}
			}
			if (["dish_name", "ingredient_name", "uom", "meal_type"].includes(column.fieldname)) return escape(value);
			return default_formatter(value, row, column, data);
		},
	};
})();
