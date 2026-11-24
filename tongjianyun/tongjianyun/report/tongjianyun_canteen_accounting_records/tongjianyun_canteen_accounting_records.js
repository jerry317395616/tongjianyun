frappe.query_reports["Tongjianyun Canteen Accounting Records"] = {
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
    onload(report) { report.page.set_title("食堂账务记录"); },
};

frappe.tjyMealDesk?.registerReport("Tongjianyun Canteen Accounting Records", "食堂账务记录");
