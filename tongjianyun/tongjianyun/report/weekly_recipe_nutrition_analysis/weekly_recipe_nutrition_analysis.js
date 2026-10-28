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
            {fieldname: "section", label: __("报表内容"), fieldtype: "Select", options: "全部\n食谱结构\n食材带量", default: "全部"},
        ],
        async onload(report) {
            report.page.set_title(__("食谱分析"));
            report.page.add_inner_button(__("周食谱表"), () => frappe.set_route("query-report", "Tongjianyun Weekly Menu", selectedSource(report)));
            report.page.add_inner_button(__("生成临时AI营养分析"), async () => {
                const source = selectedSource(report);
                if (!Object.keys(source).length) return frappe.msgprint(__("请先选择周食谱或生产计划批次。"));
                if (report.__ai_nutrition_busy) return;
                report.__ai_nutrition_busy = true;
                const popup = window.open("about:blank", "_blank");
                try {
                    const response = await frappe.call({method: "tongjianyun.weekly_nutrition_api.generate", args: source, freeze: true, freeze_message: __("正在开始临时营养分析…")});
                    const url = response.message?.preview_url;
                    if (!url?.startsWith("/api/method/tongjianyun.weekly_nutrition_api.preview?report_id=")) throw new Error("INVALID_PREVIEW");
                    if (popup) { popup.opener = null; popup.location.replace(url); }
                    else frappe.msgprint(`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${__("打开临时AI营养分析")}</a>`);
                } catch (error) { popup?.close(); frappe.msgprint(__("未能开始分析，请稍后重试。")); }
                finally { report.__ai_nutrition_busy = false; }
            });
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
