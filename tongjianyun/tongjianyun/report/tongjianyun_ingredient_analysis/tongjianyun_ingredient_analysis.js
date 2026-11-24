(() => {
	const name = "Tongjianyun Ingredient Analysis";
	const summary = "食材汇总";
	const trend = "趋势分析";
	const purchase = "采购明细";
	const kitchen = "消耗明细";
	const today = frappe.datetime.get_today();
	const purchaseFields = new Set(["ordered_qty", "received_qty", "purchase_return_qty", "net_received_qty", "pending_qty"]);
	const kitchenFields = new Set(["planned_qty", "issued_qty", "consumed_qty", "returned_qty", "loss_qty", "difference"]);
	const filterValue = (key) => frappe.query_report.get_filter_value(key);
	const escape = (value) => frappe.utils.escape_html(String(value ?? ""));

	function reportLink(report, query) {
		return `/desk/query-report/${encodeURIComponent(report)}?${new URLSearchParams(query)}`;
	}

	function link(href, text) {
		return `<a href="${escape(href)}" target="_blank" rel="noopener">${escape(text)}</a>`;
	}

	function analysisLink(view, data) {
		return reportLink(name, {
			company: filterValue("company"), from_date: data.range_start || filterValue("from_date"),
			to_date: data.range_end || filterValue("to_date"), item_code: data.item_code, view,
		});
	}

	frappe.query_reports[name] = {
		filters: [
			{ fieldname: "company", label: "园所", fieldtype: "Link", options: "Company", reqd: 1,
				default: frappe.defaults.get_user_default("Company") },
			{ fieldname: "from_date", label: "开始日期", fieldtype: "Date", default: frappe.datetime.add_days(today, -29), reqd: 1 },
			{ fieldname: "to_date", label: "结束日期", fieldtype: "Date", default: today, reqd: 1 },
			{ fieldname: "item_code", label: "食材", fieldtype: "Link", options: "Item",
				get_query: () => ({ filters: { is_stock_item: 1 } }) },
			{ fieldname: "view", label: "视图", fieldtype: "Select", options: [summary, trend, purchase, kitchen], default: summary },
			{ fieldname: "period", label: "统计周期", fieldtype: "Select", options: ["按日", "按周", "按月"], default: "按日",
				depends_on: "eval:doc.view === '趋势分析'" },
			{ fieldname: "supplier", label: "供应商", fieldtype: "Link", options: "Supplier",
				depends_on: "eval:doc.view === '采购明细'" },
			{ fieldname: "only_anomalies", label: "仅看异常与待核对", fieldtype: "Check",
				depends_on: "eval:['食材汇总', '趋势分析'].includes(doc.view)" },
			{ fieldname: "variance_threshold", label: "耗用偏差阈值 (%)", fieldtype: "Float", default: 10,
				depends_on: "eval:['食材汇总', '趋势分析'].includes(doc.view)" },
		],
		onload(report) {
			report.page.set_title("食材采购与消耗分析");
		},
		formatter(value, row, column, data, defaultFormatter) {
			const view = filterValue("view") || summary;
			if (data?.stock_entry_names?.length && column.fieldname === "stock_entries") {
				return data.stock_entry_names.map((entry) => link(`/desk/stock-entry/${encodeURIComponent(entry)}`, entry)).join("、");
			}
			if (view === kitchen && data?.meal_week && column.fieldname === "date") {
				return link(reportLink("Tongjianyun Meal Ledger", {
					company: filterValue("company"), week_name: data.meal_week, from_date: value, to_date: value, view: "食材流水",
				}), frappe.datetime.str_to_user(value));
			}
			if ((view === summary || view === trend) && data?.item_code) {
				if (view === summary && column.fieldname === "item_name") return link(analysisLink(trend, data), value);
				if (value != null && value !== "" && purchaseFields.has(column.fieldname)) {
					return link(analysisLink(purchase, data), value);
				}
				if (value != null && value !== "" && kitchenFields.has(column.fieldname)) {
					return link(analysisLink(kitchen, data), value);
				}
			}
			if (column.fieldtype === "Data") return escape(value);
			return defaultFormatter(value, row, column, data);
		},
	};
})();
