(() => {
    const primary = new Set(["energy", "protein", "fat", "carbohydrate"]);
    const number = new Intl.NumberFormat("zh-CN", {maximumFractionDigits: 4});
    const esc = value => frappe.utils.escape_html(String(value ?? ""));
    const table = (headers, rows) => `
        <div class="table-responsive">
            <table class="table table-bordered table-sm">
                <thead><tr>${headers.map(label => `<th scope="col">${esc(label)}</th>`).join("")}</tr></thead>
                <tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${esc(cell)}</td>`).join("")}</tr>`).join("")}</tbody>
            </table>
        </div>`;
    const valueText = value => value == null ? "暂无数据" : number.format(value);
    function metricText(metric) {
        if (metric.value == null) return "暂无数据";
        const amount = valueText(metric.value);
        return metric.covered === metric.total ? amount : `${amount}（部分 ${metric.covered}/${metric.total}）`;
    }

    function showResult(title, html) {
        const dialog = new frappe.ui.Dialog({title, size: "extra-large",
            fields: [{fieldname: "data", fieldtype: "HTML"}]});
        dialog.get_field("data").$wrapper.html(html);
        dialog.show();
    }

    function dish(result) {
        const source = result.frozen ? "使用发布时记录的档案和换算依据。" : "使用当前已审核的档案。";
        showResult("每份菜品营养 · 投料估算", `<p>${source} 标为部分的数值只汇总了有依据的食材。</p>
            ${table(["营养素", "每份", "单位"], result.metrics.map(row => [row.label, metricText(row), row.unit]))}
            <h5>食材与计算依据</h5>
            ${table(["食材", "每份可食重量（克）", "营养档案", "依据"], result.lines.map(line => [
                line.food, valueText(line.grams), line.profile || "—", line.issue || line.weight_basis,
            ]))}`);
    }

    function week(result) {
        const basis = result.frozen ? "使用审核发布时记录的档案和换算依据。" : "未记录周食谱发布时的依据。本次使用配方已保存的依据或当前档案。";
        const totals = table(["营养素", "单位", ...result.days.map(day => day.date), "本周合计"],
            result.metrics.map((row, i) => [row.label, row.unit,
                ...result.days.map(day => metricText(day.metrics[i])), metricText(row)]));
        const meals = table(["日期", "餐次", ...result.metrics.filter(row => primary.has(row.key)).map(row => `${row.label}（${row.unit}）`)],
            result.meals.map(meal => [meal.date, meal.meal, ...meal.metrics.filter(row => primary.has(row.key)).map(metricText)]));
        const gaps = result.issues.length ? table(["日期", "餐次", "食材", "待补资料"], result.issues
            .map(row => [row.date, row.meal, row.food, row.issue])) : "<p>暂无食材档案或重量换算缺项。各营养素的覆盖情况请查看汇总。</p>";
        const profiles = result.profiles.length ? table(["食材", "营养档案", "来源依据"],
            result.profiles.map(row => [row.food, row.profile, row.source_reference])) : "<p>暂无可用档案。</p>";
        showResult("周食谱营养 · 人均投料估算", `<p>${basis} 「部分」标记后是已计入食材项数／总项数。</p>
            ${totals}<details><summary>分餐次查看</summary>${meals}</details>
            <details${result.issues.length ? " open" : ""}><summary>食材档案和换算缺项</summary>${gaps}</details>
            <details><summary>计算所用的档案版本</summary>${profiles}</details>`);
    }

    frappe.tjy_food_nutrition = {dish, week,
        ingredient: frm => frappe.require("/assets/tongjianyun/js/ingredient_nutrition.js?v=per-100g.js")
            .then(() => frappe.tjy_ingredient_nutrition(frm)),
    };
})();
