frappe.query_reports["Tongjianyun Canteen Inventory Batches"] = {
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
        "fieldname": "warehouse",
        "label": "仓库",
        "fieldtype": "Link",
        "options": "Warehouse"
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
    onload(report) { report.page.set_title("实时库存与效期"); },
};

frappe.tjyMealDesk?.registerReport("Tongjianyun Canteen Inventory Batches", "实时库存与效期");
