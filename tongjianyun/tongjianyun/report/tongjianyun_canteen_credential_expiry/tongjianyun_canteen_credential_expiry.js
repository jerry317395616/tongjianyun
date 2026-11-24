frappe.query_reports["Tongjianyun Canteen Credential Expiry"] = {
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
        "fieldname": "only_anomalies",
        "label": "仅异常",
        "fieldtype": "Check"
    }
],
    onload(report) { report.page.set_title("食堂证照到期提醒"); },
};

frappe.tjyMealDesk?.registerReport("Tongjianyun Canteen Credential Expiry", "食堂证照到期提醒");
