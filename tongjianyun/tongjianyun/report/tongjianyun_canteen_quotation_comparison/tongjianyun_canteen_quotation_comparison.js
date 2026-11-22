frappe.query_reports["Tongjianyun Canteen Quotation Comparison"] = {
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
        "fieldname": "quotation_request",
        "label": "询价单",
        "fieldtype": "Link",
        "options": "Request for Quotation"
    },
    {
        "fieldname": "item_code",
        "label": "食材",
        "fieldtype": "Link",
        "options": "Item"
    },
    {
        "fieldname": "only_anomalies",
        "label": "仅异常",
        "fieldtype": "Check"
    }
],
    onload(report) { report.page.set_title("食材询价比价"); },
};
