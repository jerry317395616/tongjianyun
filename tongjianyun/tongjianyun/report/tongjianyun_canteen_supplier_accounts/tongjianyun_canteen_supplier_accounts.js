frappe.query_reports["Tongjianyun Canteen Supplier Accounts"] = {
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
        "fieldname": "supplier",
        "label": "供应商",
        "fieldtype": "Link",
        "options": "Supplier"
    }
],
    onload(report) { report.page.set_title("供应商对账与结算"); },
};
