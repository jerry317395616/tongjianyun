(() => {
    const profileType = "Tongjianyun Food Nutrition Profile";
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

    async function ingredient(frm) {
        const $content = frm.fields_dict.custom_tjy_nutrition_preview?.$wrapper;
        if (!$content) return;
        if (!frappe.model.can_read(profileType)) {
            $content.empty().text("当前账号无权查看营养档案。");
            return;
        }
        if (frm.is_new()) {
            $content.empty().text("保存食材后可建立营养档案。");
            return;
        }
        const code = frm.doc.name;
        const actions = () => {
            const $actions = $("<div>", {class: "mb-3"}).appendTo($content);
            $("<button>", {type: "button", class: "btn btn-default btn-sm mr-2"}).text("查看营养档案")
                .on("click", () => {
                    frappe.route_options = {item_code: code};
                    frappe.set_route("List", profileType);
                }).appendTo($actions);
            if (!frm.doc.disabled && frappe.model.can_create(profileType)) {
                $("<button>", {type: "button", class: "btn btn-primary btn-sm"}).text("新建营养档案")
                    .on("click", () => frappe.new_doc(profileType, {item_code: code})).appendTo($actions);
            }
        };
        $content.empty().text("正在加载营养成分…");
        try {
            const {message: result} = await frappe.call({
                method: "tongjianyun.food_nutrition.ingredient_profile", type: "GET", args: {item_code: code},
            });
            if (frm.doc.name !== code) return;
            const {profile, labels, nutrients, status} = result;
            frm.doc.custom_tjy_nutrition_status = status;
            frm.refresh_field("custom_tjy_nutrition_status");
            $content.empty();
            actions();
            if (!profile) {
                $("<p>", {class: "text-muted"}).text(status === "待审核"
                    ? "档案审核通过后，营养成分将在这里显示。" : "暂无可用的营养档案。").appendTo($content);
                return;
            }
            const $source = $("<p>", {class: "mb-2"}).appendTo($content);
            $("<a>", {href: frappe.utils.get_form_link(profileType, profile.name)}).text(profile.name)
                .appendTo($source);
            $source.append(document.createTextNode(` · ${profile.food_name} · ${profile.food_state} · ${profile.source_name} · ${profile.source_code} · ${profile.source_version}`));
            $("<p>", {class: "text-muted"}).text([
                `原始口径 ${profile.basis}`,
                `默认可食率 ${profile.edible_pct ? profile.edible_pct + "%" : "暂无数据"}`,
                ...(profile.grams_per_stock_unit ? [`每${result.stock_uom} ${profile.grams_per_stock_unit} 克`] : []),
            ].join(" · ")).appendTo($content);
            const $summary = $("<div>", {class: "row mb-3"}).appendTo($content);
            for (const [key, [label, unit]] of Object.entries(labels).filter(([key]) => primary.has(key))) {
                const $cell = $("<div>", {class: "col-sm-3 mb-2"}).appendTo($summary);
                $("<div>", {class: "text-muted"}).text(label).appendTo($cell);
                $("<strong>").text(nutrients[key] == null ? "暂无数据" : `${valueText(nutrients[key])} ${unit}`).appendTo($cell);
            }
            $content.append(table(["营养素", "每 100 克可食部", "单位"],
                Object.entries(labels).map(([key, [label, unit]]) => [label, valueText(nutrients[key]), unit])));
        } catch {
            if (frm.doc.name === code) $content.empty().text("暂时无法读取营养成分。");
        }
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
        const profiles = result.profiles.length ? table(["食材", "营养档案", "来源", "条目编号", "来源版本"],
            result.profiles.map(row => [row.food, row.profile, row.source, row.source_code, row.source_version])) : "<p>暂无可用档案。</p>";
        showResult("周食谱营养 · 人均投料估算", `<p>${basis} 「部分」标记后是已计入食材项数／总项数。</p>
            ${totals}<details><summary>分餐次查看</summary>${meals}</details>
            <details${result.issues.length ? " open" : ""}><summary>食材档案和换算缺项</summary>${gaps}</details>
            <details><summary>计算所用的档案版本</summary>${profiles}</details>`);
    }

    frappe.tjy_food_nutrition = {ingredient, dish, week};
})();
