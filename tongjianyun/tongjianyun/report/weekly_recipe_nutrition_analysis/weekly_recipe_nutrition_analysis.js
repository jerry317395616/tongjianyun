(() => {
    const name = "Weekly Recipe Nutrition Analysis";
    const esc = value => frappe.utils.escape_html(String(value ?? ""));
    const method = "tongjianyun.weekly_nutrition_api.";
    function zoom(report) {
        const container = report.$report_message.find(".tjy-analysis-scroll")[0];
        const table = report.$report_message.find(".tjy-analysis table");
        if (container && table[0]) table.css("zoom", report.__nutritionFit ? Math.min(1, container.clientWidth / Number(table.attr("width"))) : 1);
    }
    function reset(report, message) {
        const state = report.__nutrition;
        if (state) { clearTimeout(state.timer); clearTimeout(state.expiry); }
        report.__nutrition = {epoch: (state?.epoch || 0) + 1};
        report.__nutritionDownload?.prop("disabled", true);
        report.__nutritionPrint?.prop("disabled", true);
        report.__nutritionGenerate?.prop("disabled", false);
        if (report.__nutritionBlank) report.$report_message.find(".tjy-inline-sheet").html(report.__nutritionBlank);
        if (message) report.$report_message.find(".tjy-inline-status").text(message);
    }
    async function changeSource(report, field) {
        if (report._no_refresh || report.__changing_meal_source) return;
        reset(report, "正在切换食谱…");
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
    const active = (report, state) => report.__nutrition === state && frappe.get_route()[0] === "query-report" && frappe.get_route()[1] === name;
    async function generate(report) {
        if (report.__nutrition?.pending) return;
        const source = selectedSource(report);
        if (!Object.keys(source).length) return frappe.msgprint(__("请先选择周食谱或生产计划批次。"));
        reset(report, "大模型正在分析，完成后将在本表显示。可以继续浏览食材带量。");
        const state = report.__nutrition;
        state.pending = true;
        report.__nutritionGenerate.prop("disabled", true);
        try {
            const response = await frappe.call({method: method + "generate", args: source});
            if (!active(report, state)) return;
            const meta = response.message;
            if (!/^[a-f0-9]{64}$/.test(meta?.report_id || "")) throw Error("INVALID_REPORT");
            state.id = meta.report_id;
            state.expiry = setTimeout(() => reset(report, "临时结果已过期并清除，请重新生成。"), Math.max(0, meta.expires_at * 1000 - Date.now()));
            await poll(report, state);
        } catch { if (active(report, state)) reset(report, "未能生成分析，请稍后重试。"); }
    }
    async function poll(report, state) {
        if (!active(report, state)) return;
        try {
            const response = await fetch("/api/method/" + method + "result?report_id=" + state.id, {credentials: "same-origin", cache: "no-store", redirect: "error"});
            if (!response.ok) throw Error("RESULT_UNAVAILABLE");
            const payload = (await response.json()).message;
            if (!active(report, state)) return;
            if (payload?.status === "pending") { state.timer = setTimeout(() => poll(report, state), 4000); return; }
            if (payload?.status !== "ready" || !payload.sheet_html) throw Error("ANALYSIS_FAILED");
            report.$report_message.find(".tjy-inline-sheet").html(payload.sheet_html);
            zoom(report);
            report.$report_message.find(".tjy-inline-status").text("AI分析完成。结果有效至 " + new Date(payload.expires_at * 1000).toLocaleTimeString("zh-CN") + "；页面、打印与Excel使用相同结果。");
            state.pending = false; state.ready = true;
            report.__nutritionGenerate.prop("disabled", false);
            report.__nutritionDownload.prop("disabled", false);
            report.__nutritionPrint.prop("disabled", false);
        } catch { if (active(report, state)) reset(report, "结果已过期、食谱已改变或分析未成功，请重新生成。"); }
    }
    function print(report) {
        if (!report.__nutrition?.ready) return;
        const popup = window.open("about:blank", "_blank");
        if (!popup) return frappe.msgprint(__("请允许此站点打开打印窗口。"));
        popup.opener = null;
        popup.document.write('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>食谱带量分析</title><style>@page{size:A3 landscape;margin:8mm}body{margin:0}button{margin:10px;padding:8px 16px}@media print{button{display:none}}</style><button onclick="window.print()">打印 / 另存为PDF</button>' + report.$report_message.find(".tjy-inline-sheet").html() + '</html>');
        popup.document.close();
    }
    frappe.query_reports[name] = {
        filters: [
            {fieldname: "week_start", label: __("周开始日期"), fieldtype: "Date", on_change: report => changeSource(report, "week_start")},
            {fieldname: "week_name", label: __("周食谱"), fieldtype: "Link", options: "Meal Planning Week", on_change: report => changeSource(report, "week_name")},
            {fieldname: "plan_batch", label: __("生产计划批次"), fieldtype: "Data", on_change: report => changeSource(report, "plan_batch")},
        ],
        async onload(report) {
            report.page.set_title(__("食谱分析"));
            report.page.add_inner_button(__("周食谱表"), () => frappe.set_route("query-report", "Tongjianyun Weekly Menu", selectedSource(report)));
            report.__nutritionGenerate = report.page.add_inner_button(__("生成AI营养分析"), () => generate(report));
            report.__nutritionDownload = report.page.add_inner_button(__("下载带量分析Excel"), () => {
                if (report.__nutrition?.ready) window.location.assign("/api/method/" + method + "download?report_id=" + report.__nutrition.id);
            }).prop("disabled", true);
            report.__nutritionPrint = report.page.add_inner_button(__("打印带量分析"), () => print(report), __("更多")).prop("disabled", true);
            report.page.add_inner_button(__("适应宽度／原始大小"), () => { report.__nutritionFit = !report.__nutritionFit; zoom(report); });
            report.page.add_inner_button(__("清除临时结果"), async () => {
                const id = report.__nutrition?.id;
                reset(report, "页面中的临时分析已清除。");
                if (id) { try { await frappe.call({method: method + "discard", args: {report_id: id}}); }
                    catch { frappe.show_alert(__("服务端结果会在到期时自动清除。")); } }
            }, __("更多"));
            if (!report.__nutritionRouteHandler) {
                report.__nutritionRouteHandler = () => {
                    if (frappe.get_route()[0] !== "query-report" || frappe.get_route()[1] !== name) reset(report);
                };
                frappe.router.on("change", report.__nutritionRouteHandler);
                window.addEventListener("pagehide", () => reset(report));
            }
            if (Object.keys(selectedSource(report)).length) return;
            const rows = await frappe.db.get_list("Meal Planning Week", {fields:["name"],filters:{docstatus:["<",2]},order_by:"week_start desc, modified desc",limit:1});
            if (rows[0]?.name && !Object.keys(selectedSource(report)).length) await report.set_filter_value("week_name", rows[0].name);
        },
        after_refresh(report) {
            // Frappe owns the data/query machinery; only this report's visible body changes.
            report.$report_message.find(".tjy-inline-analysis").css("width", "100%");
            report.$report_message.css({background: "transparent", padding: "12px 0", color: "inherit"});
            report.$report.hide();
            report.__nutritionBlank = report.$report_message.find(".tjy-inline-sheet").html();
            reset(report);
            zoom(report);
        },
        formatter(value, row, column, data, defaultFormatter) { return esc(value); },
    };
})();
