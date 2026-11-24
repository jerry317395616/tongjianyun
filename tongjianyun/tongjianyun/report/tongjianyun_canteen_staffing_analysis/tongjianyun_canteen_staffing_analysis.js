(() => {
	const name = "Tongjianyun Canteen Staffing Analysis";
	const summary = "岗位汇总";
	const detail = "班次明细";
	const today = frappe.datetime.get_today();
	const filter = (key) => frappe.query_report.get_filter_value(key);
	const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
	const sources = {
		assignments: { field: "assignment_links", route: "shift-assignment" },
		attendance: { field: "attendance_links", route: "attendance" },
	};

	function link(href, label) {
		return `<a href="${escape(href)}" target="_blank" rel="noopener">${escape(label)}</a>`;
	}

	function details(row) {
		const params = new URLSearchParams({
			company: filter("company"), from_date: filter("from_date"), to_date: filter("to_date"), view: detail,
			canteen_name: row.canteen, shift_type: row.shift_type, designation: row.designation, department: row.department,
		});
		if (row.shift_location) params.set("shift_location", row.shift_location);
		if (filter("only_anomalies")) params.set("only_anomalies", "1");
		return `/desk/query-report/${encodeURIComponent(name)}?${params}`;
	}

	frappe.query_reports[name] = {
		filters: [
			{ fieldname: "company", label: "园所", fieldtype: "Link", options: "Company", reqd: 1,
				default: frappe.defaults.get_user_default("Company") },
			{ fieldname: "from_date", label: "开始日期", fieldtype: "Date", reqd: 1, default: frappe.datetime.add_days(today, -6) },
			{ fieldname: "to_date", label: "结束日期", fieldtype: "Date", reqd: 1, default: today },
			{ fieldname: "view", label: "视图", fieldtype: "Select", options: [summary, detail, "供餐负荷"], default: summary },
			{ fieldname: "canteen_name", label: "食堂名称", fieldtype: "Data" },
			{ fieldname: "shift_location", label: "值勤地点", fieldtype: "Link", options: "Shift Location" },
			{ fieldname: "shift_type", label: "班次", fieldtype: "Link", options: "Shift Type" },
			{ fieldname: "department", label: "部门", fieldtype: "Link", options: "Department",
				get_query: () => ({ filters: filter("company") ? { company: filter("company") } : {} }) },
			{ fieldname: "designation", label: "岗位", fieldtype: "Link", options: "Designation" },
			{ fieldname: "only_anomalies", label: "仅看异常与待核对", fieldtype: "Check" },
		],
		onload(report) {
			report.page.set_title("人员配置分析");
			report.page.add_inner_button("食堂岗位配置", () => {
				frappe.set_route("List", "Tongjianyun Canteen Staffing Rule", { company: filter("company") });
			});
		},
		formatter(value, row, column, data, defaultFormatter) {
			const source = sources[column.fieldname];
			if (source && data?.[source.field]?.length) {
				return data[source.field].map((name) => link(`/desk/${source.route}/${encodeURIComponent(name)}`, name)).join("、");
			}
			const view = filter("view") || summary;
			if (view === summary && data && column.fieldname === "canteen") return link(details(data), value);
			if (view === summary && data && ["plan_gap", "actual_gap", "pending", "conflicts"].includes(column.fieldname)
					&& Number(value) > 0) return link(details(data), value);
			if (column.fieldtype === "Data") return escape(value);
			return defaultFormatter(value, row, column, data);
		},
	};
})();

frappe.tjyMealDesk?.registerReport("Tongjianyun Canteen Staffing Analysis", "人员配置分析");
