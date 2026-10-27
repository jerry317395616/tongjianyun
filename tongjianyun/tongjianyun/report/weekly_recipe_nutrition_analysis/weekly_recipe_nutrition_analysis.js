(() => {
    const name = "Weekly Recipe Nutrition Analysis";
    const esc = value => frappe.utils.escape_html(String(value ?? ""));
    async function changeSource(report, field) {
        if (report._no_refresh || report.__changing_meal_source) return;
        report.__changing_meal_source = true;
        try {
            if (report.get_filter_value(field)) {
                const others = ["week_name", "plan_batch", "week_start"].filter(key => key !== field && report.get_filter_value(key));
                if (others.length) await report.set_filter_value(Object.fromEntries(others.map(key => [key, ""])));
            }
        } finally { report.__changing_meal_source = false; }
        return report.refresh(true);
    }
    const selectedSource = report => {
        const week = report.get_filter_value("week_name"), batch = report.get_filter_value("plan_batch");
        if (week) return {week_name: week};
        if (batch) return {plan_batch: batch};
        if (report.get_filter_value("week_start")) return {week_start: report.get_filter_value("week_start")};
        const row = report.data?.[0];
        return row?.week_name ? {week_name: row.week_name} : row?.plan_batch ? {plan_batch: row.plan_batch} : {};
    };
    frappe.query_reports[name] = {
        filters: [
            {fieldname: "week_start", label: __("周开始日期"), fieldtype: "Date", on_change: report => changeSource(report, "week_start")},
            {fieldname: "week_name", label: __("周食谱"), fieldtype: "Link", options: "Meal Planning Week", on_change: report => changeSource(report, "week_name")},
            {fieldname: "plan_batch", label: __("生产计划批次"), fieldtype: "Data", on_change: report => changeSource(report, "plan_batch")},
            {fieldname: "age_group", label: __("手动年龄参考"), fieldtype: "Select", options: "4–5岁平均\n2岁\n3岁\n4岁\n5岁\n6岁", default: "4–5岁平均"},
            {fieldname: "gender", label: __("手动性别参考"), fieldtype: "Select", options: "男女平均\n男\n女", default: "男女平均"},
            {fieldname: "garden_ratio", label: __("园内参考比例"), fieldtype: "Percent", default: 80},
            {fieldname: "section", label: __("报表内容"), fieldtype: "Select", options: "全部\n食谱结构\n营养估算\n食材带量\n待补资料", default: "全部"},
        ],
        async onload(report) {
            report.page.set_title(__("食谱分析"));
            report.page.add_inner_button(__("周食谱表"), () => frappe.set_route("query-report", "Tongjianyun Weekly Menu", selectedSource(report)));
            if (Object.keys(selectedSource(report)).length) return;
            const rows = await frappe.db.get_list("Meal Planning Week", {fields:["name"],filters:{docstatus:["<",2]},order_by:"week_start desc, modified desc",limit:1});
            if (rows[0]?.name && !Object.keys(selectedSource(report)).length) await report.set_filter_value("week_name", rows[0].name);
        },
        formatter(value, row, column, data, defaultFormatter) {
            if (["amount", "reference", "garden_target"].includes(column.fieldname)) {
                if (value === null || value === undefined || value === "") return "—";
                if (Number.isFinite(Number(value))) return Number(value).toLocaleString("zh-CN", {maximumFractionDigits: 4});
                return "—";
            }
            return esc(value);
        },
    };
})();
