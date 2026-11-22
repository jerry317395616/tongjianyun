frappe.query_reports["Tongjianyun Canteen Stock Count"] = {
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
        "fieldname": "warehouse",
        "label": "仓库",
        "fieldtype": "Link",
        "options": "Warehouse"
    },
    {
        "fieldname": "stock_reconciliation",
        "label": "盘点单",
        "fieldtype": "Link",
        "options": "Stock Reconciliation"
    }
],
    onload(report) { report.page.set_title("食堂盘点报表"); },
};
