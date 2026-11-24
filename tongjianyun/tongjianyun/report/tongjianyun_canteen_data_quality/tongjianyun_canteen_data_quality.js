frappe.query_reports["Tongjianyun Canteen Data Quality"] = {
    filters: [
        {fieldname: "view", label: "视图", fieldtype: "Select", options: ["问题明细", "完整性统计"], default: "问题明细"},
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
    onload(report) {
        report.page.set_title("监管数据质量");
        report.page.add_inner_button("发起整改", () => {
            const rows = (report.data || []).filter((row) => row.finding_key && !row.finding);
            if (!rows.length) return frappe.msgprint("当前结果没有可发起整改的记录。");
            const choices = rows.map((row, index) => (index + 1) + " · " + row.rule + " · " + (row.source || row.canteen) + " · " + row.fact);
            frappe.prompt([
                { fieldname: "issue", label: "选择问题", fieldtype: "Select", options: choices, reqd: 1 },
                { fieldname: "due_date", label: "整改期限", fieldtype: "Date", reqd: 1 },
                { fieldname: "assigned_to", label: "整改人", fieldtype: "Link", options: "User", reqd: 1 }
            ], async (values) => {
                const row = rows[choices.indexOf(values.issue)];
                const filters = report.get_filter_values();
                const result = await frappe.call({
                    method: "tongjianyun.canteen_ops.reports.create_finding",
                    args: { canteen: row.canteen, key: row.finding_key, due_date: values.due_date,
                        assigned_to: values.assigned_to, from_date: filters.from_date, to_date: filters.to_date },
                    freeze: true
                });
                frappe.set_route("Form", "Tongjianyun Canteen Finding", result.message);
            }, "新建整改记录", "确认");
        });
    },
};

frappe.tjyMealDesk?.registerReport("Tongjianyun Canteen Data Quality", "监管数据质量");
