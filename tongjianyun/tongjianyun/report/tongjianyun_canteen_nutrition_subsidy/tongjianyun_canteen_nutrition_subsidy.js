frappe.query_reports["Tongjianyun Canteen Nutrition Subsidy"] = {
    filters: [
    {
        "fieldname": "company",
        "label": "园所",
        "fieldtype": "Link",
        "options": "Company"
    },
    {
        "fieldname": "canteen",
        "label": "食堂",
        "fieldtype": "Link",
        "options": "Tongjianyun Canteen"
    },
    {
        "fieldname": "from_date",
        "label": "开始日期",
        "fieldtype": "Date"
    },
    {
        "fieldname": "to_date",
        "label": "结束日期",
        "fieldtype": "Date"
    }
],
    onload(report) { report.page.set_title("营养餐补助报表"); },
};
