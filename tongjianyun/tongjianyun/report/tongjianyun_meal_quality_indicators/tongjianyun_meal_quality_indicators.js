frappe.query_reports["Tongjianyun Meal Quality Indicators"] = {
	filters: [
		{fieldname:"canteen", label:"食堂", fieldtype:"Link", options:"Tongjianyun Canteen", reqd:1},
		{fieldname:"from_date", label:"起始日期", fieldtype:"Date", default:frappe.datetime.month_start(), reqd:1},
		{fieldname:"to_date", label:"结束日期", fieldtype:"Date", default:frappe.datetime.get_today(), reqd:1}
	]
};

frappe.tjyMealDesk?.registerReport("Tongjianyun Meal Quality Indicators", "膳食质量指标");
