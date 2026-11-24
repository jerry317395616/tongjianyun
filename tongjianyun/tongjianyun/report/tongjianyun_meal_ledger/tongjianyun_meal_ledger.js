(() => {
	const name = "Tongjianyun Meal Ledger";
	const base = `/desk/query-report/${encodeURIComponent(name)}`;
	const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
	const today = frappe.datetime.get_today();
	const monday = frappe.datetime.add_days(today, -((new Date(`${today}T12:00:00Z`).getUTCDay() + 6) % 7));

	function dayLink(row) {
		const query = new URLSearchParams({ company: row.company, week_name: row.meal_week, from_date: row.meal_date,
			to_date: row.meal_date, view: "餐次核对" });
		return `${base}?${query}`;
	}

	frappe.query_reports[name] = {
		filters: [
			{ fieldname: "company", label: "园所", fieldtype: "Link", options: "Company",
				default: frappe.defaults.get_user_default("Company") },
			{ fieldname: "from_date", label: "开始日期", fieldtype: "Date", default: monday, reqd: 1 },
			{ fieldname: "to_date", label: "结束日期", fieldtype: "Date", default: frappe.datetime.add_days(monday, 4), reqd: 1 },
			{ fieldname: "view", label: "视图", fieldtype: "Select", options: ["按日汇总", "餐次核对", "食材流水", "采购与日结"],
				default: "按日汇总" },
			{ fieldname: "day_status", label: "日结状态", fieldtype: "Select",
				options: ["", "暂无执行记录", "待日结", "已日结", "日结依据待核对"] },
			{ fieldname: "week_name", label: "食谱周计划", fieldtype: "Link", options: "Meal Planning Week",
				get_query() {
					const company = frappe.query_report.get_filter_value("company");
					return { filters: { docstatus: 1, ...(company ? { company } : {}) } };
				} },
		],
		onload(report) {
			report.page.set_title(__("膳食台账"));
		},
		formatter(value, row, column, data, defaultFormatter) {
			if (data && column.fieldname === "meal_date" && data.day_status) {
				return `<a href="${escape(dayLink(data))}" target="_blank" rel="noopener">${escape(frappe.datetime.str_to_user(value))}</a>`;
			}
			if (data && column.fieldname === "stock_entries" && data.stock_entry_names?.length) {
				return data.stock_entry_names.map((entry) =>
					`<a href="/desk/stock-entry/${encodeURIComponent(entry)}">${escape(entry)}</a>`).join("、");
			}
			if (column.fieldname === "actual" && value == null) return `<span class="text-muted">${__("待确认")}</span>`;
			if (column.fieldtype === "Data") return escape(value);
			return defaultFormatter(value, row, column, data);
		},
	};
})();

frappe.tjyMealDesk?.registerReport("Tongjianyun Meal Ledger", "膳食台账");
