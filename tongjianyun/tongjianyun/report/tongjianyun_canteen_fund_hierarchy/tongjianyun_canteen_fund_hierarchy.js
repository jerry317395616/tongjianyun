frappe.query_reports["Tongjianyun Canteen Fund Hierarchy"] = {
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
    },
    {
        "fieldname": "region",
        "label": "市级行政区",
        "fieldtype": "Data"
    },
    {
        "fieldname": "district",
        "label": "区县",
        "fieldtype": "Data"
    }
],
    onload(report) { report.page.set_title("经费分级统计"); },
};
