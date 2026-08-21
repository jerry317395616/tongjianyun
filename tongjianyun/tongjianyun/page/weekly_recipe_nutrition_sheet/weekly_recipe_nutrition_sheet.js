frappe.pages["weekly-recipe-nutrition-sheet"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "周食谱营养分析",
        single_column: true,
    });
    wrapper.weeklyNutritionSheet = new WeeklyRecipeNutritionSheet(page, wrapper);
};

frappe.pages["weekly-recipe-nutrition-sheet"].on_page_show = function (wrapper) {
    const controller = wrapper.weeklyNutritionSheet;
    if (controller && frappe.route_options?.recipe) {
        controller.applyRouteRecipe(frappe.route_options.recipe);
        frappe.route_options = null;
    }
};

const FOOD_LAYOUT = [
    {
        label: "粮食类",
        children: [
            { key: "fine_grain", label: "细粮", rows: 3 },
            { key: "coarse_grain", label: "杂粮", rows: 3 },
            { key: "pastry", label: "糕点", rows: 2 },
        ],
    },
    {
        label: "豆类",
        children: [
            { key: "dry_bean", label: "干豆类", rows: 2 },
            { key: "soy", label: "豆制品", rows: 2 },
        ],
    },
    {
        label: "蔬菜类",
        children: [
            { key: "non_green_veg", label: "非绿蔬菜", rows: 5 },
            { key: "green_veg", label: "绿橙蔬菜", rows: 3 },
        ],
    },
    { label: "水果", single: true, children: [{ key: "fruit", label: "水果", rows: 2 }] },
    { label: "乳类", single: true, children: [{ key: "dairy", label: "乳类", rows: 2 }] },
    { label: "蛋类", single: true, children: [{ key: "egg", label: "蛋类", rows: 2 }] },
    {
        label: "鱼肉类",
        children: [
            { key: "meat", label: "肉类", rows: 2 },
            { key: "liver", label: "肝", rows: 2 },
            { key: "fish", label: "鱼", rows: 2 },
        ],
    },
    { label: "糖类", single: true, children: [{ key: "sugar", label: "糖类", rows: 2 }] },
];

const MEALS = [
    ["breakfast", "早餐"],
    ["morningSnack", "早点"],
    ["lunch", "中餐"],
    ["snack", "午点"],
    ["dinner", "晚餐"],
];

class WeeklyRecipeNutritionSheet {
    constructor(page, wrapper) {
        this.page = page;
        this.wrapper = $(wrapper);
        this.loading = false;
        this.suspendFilterChange = false;
        this.main = $('<div class="tjy-nutrition-sheet-page"></div>').appendTo(this.page.main);
        this.installStyles();
        this.buildFilters();
        this.bindActions();
        this.loadInitial();
    }

    buildFilters() {
        const reload = () => {
            if (!this.suspendFilterChange) this.load();
        };
        this.recipeControl = this.page.add_field({
            fieldname: "recipe",
            label: "食谱",
            fieldtype: "Link",
            options: "Tongjianyun Recipe",
            get_query: () => ({ filters: { is_deleted: 0 } }),
            change: reload,
        });
        this.standardModeControl = this.page.add_field({
            fieldname: "standard_mode",
            label: "标准计算方式",
            fieldtype: "Select",
            options: "自动（按学生档案）\n手动估算",
            default: "自动（按学生档案）",
            change: reload,
        });
        this.studentGroupsControl = this.page.add_field({
            fieldname: "student_groups",
            label: "统计班级（不选则全部）",
            fieldtype: "MultiSelectList",
            get_data: (txt) => frappe.db.get_link_options("Student Group", txt, { disabled: 0 }),
            change: reload,
        });
        this.ageControl = this.page.add_field({
            fieldname: "age_group",
            label: "手动年龄口径",
            fieldtype: "Select",
            options: "4–5岁平均\n4岁\n5岁",
            default: "4–5岁平均",
            change: reload,
        });
        this.genderControl = this.page.add_field({
            fieldname: "gender",
            label: "手动性别口径",
            fieldtype: "Select",
            options: "男女平均\n男\n女",
            default: "男女平均",
            change: reload,
        });
        this.ratioControl = this.page.add_field({
            fieldname: "garden_ratio",
            label: "园内供给目标",
            fieldtype: "Percent",
            default: 80,
            change: reload,
        });
    }

    bindActions() {
        this.page.set_primary_action("导出同版Excel", () => this.exportExcel(), "download");
        this.page.add_inner_button("打印", () => window.print(), "操作");
        this.page.add_inner_button("分析看板", () => this.openDashboard(), "操作");
        this.page.add_inner_button("食谱计划", () => this.openRecipePlan(), "操作");
    }

    async loadInitial() {
        const routeRecipe = frappe.route_options?.recipe;
        frappe.route_options = null;
        if (routeRecipe) {
            this.suspendFilterChange = true;
            await this.recipeControl.set_value(routeRecipe);
            this.suspendFilterChange = false;
        }
        await this.load();
    }

    async applyRouteRecipe(recipe) {
        if (!recipe || recipe === this.recipeControl.get_value()) return;
        this.suspendFilterChange = true;
        await this.recipeControl.set_value(recipe);
        this.suspendFilterChange = false;
        await this.load();
    }

    filterArgs() {
        return {
            recipe: this.recipeControl.get_value() || null,
            standard_mode: this.standardModeControl.get_value() || "自动（按学生档案）",
            student_groups: this.studentGroupsControl.get_value() || [],
            age_group: this.ageControl.get_value() || "4–5岁平均",
            gender: this.genderControl.get_value() || "男女平均",
            garden_ratio: this.ratioControl.get_value() || 80,
        };
    }

    async load() {
        if (this.loading) return;
        this.loading = true;
        this.main.html('<div class="tjy-sheet-loading"><div class="spinner-border text-primary" role="status"></div><span>正在生成营养分析表...</span></div>');
        try {
            const response = await frappe.call({
                method: "tongjianyun.nutrition_sheet.get_nutrition_sheet",
                args: this.filterArgs(),
            });
            const result = response.message;
            if (!this.recipeControl.get_value() && result?.recipe?.name) {
                this.suspendFilterChange = true;
                await this.recipeControl.set_value(result.recipe.name);
                this.suspendFilterChange = false;
            }
            this.result = result;
            this.render(result);
        } catch (error) {
            this.main.html(`<div class="tjy-sheet-error"><strong>营养分析表生成失败</strong><span>${escapeHtml(error?.message || "请稍后重试")}</span></div>`);
        } finally {
            this.loading = false;
        }
    }

    render(result) {
        const analysis = result.analysis;
        const rows = buildFoodRows(analysis);
        const nutritionRows = buildNutritionRows(analysis);
        const recipeTitle = result.recipe.title || result.recipe.recipe_id || result.recipe.name;
        const population = populationSummary(analysis.standard.population);
        this.main.html(`
            <div class="tjy-sheet-heading">
                <div>
                    <div class="tjy-sheet-kicker">童健云 · 标准营养分析表</div>
                    <h2>${escapeHtml(recipeTitle)}</h2>
                    <p>${escapeHtml(result.recipe.week_start || "—")} 至 ${escapeHtml(result.recipe.week_end || "—")} · ${escapeHtml(analysis.standard.profile)} · 园内目标 ${formatNumber(analysis.standard.garden_ratio * 100, 0)}%${population ? ` · ${population}` : ""}</p>
                </div>
                <div class="tjy-sheet-legend"><span class="good"></span>适宜 <span class="warn"></span>需调整</div>
            </div>
            <div class="tjy-sheet-scroll">
                <table class="tjy-nutrition-sheet">
                    <colgroup>
                        <col class="group-col"><col class="subgroup-col">
                        ${Array.from({ length: 5 }, () => '<col class="food-col"><col class="weight-col">').join("")}
                        <col class="analysis-label-col"><col class="analysis-value-col">
                        <col class="nutrient-group-col"><col class="nutrient-label-col">
                        ${Array.from({ length: 5 }, () => '<col class="nutrient-value-col">').join("")}
                    </colgroup>
                    <thead>
                        <tr>
                            <th colspan="2" rowspan="2">食物分类重量</th>
                            <th colspan="10">每人每天平均进食量（折算为整全天，即一个人日数）（${analysis.ingredients.length}种）（克）（可食重量）</th>
                            <th colspan="9">营养分析及改进建议</th>
                        </tr>
                        <tr>
                            ${Array.from({ length: 5 }, () => '<th>食物</th><th>重量</th>').join("")}
                            <th colspan="2">总人日数（一周）</th>
                            <th colspan="2">营养素</th>
                            <th>全日标准量</th><th>在园标准量</th><th>在园实给量</th><th>在园实给%</th><th>评价</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${rows.map((row, index) => `
                            <tr>
                                ${renderFoodCells(row)}
                                ${renderAnalysisCells(index, analysis, result.recipe)}
                                ${renderNutritionCells(index, nutritionRows, analysis)}
                            </tr>
                        `).join("")}
                    </tbody>
                </table>
            </div>
            <div class="tjy-sheet-footnote">
                <strong>说明：</strong>营养含量采用食材分类代表值估算，适用于食谱编制阶段筛查；正式评估应结合准确食物成分、可食部、烹调损耗与实际摄入量。
            </div>
        `);
    }

    async exportExcel() {
        const recipe = this.recipeControl.get_value();
        if (!recipe) {
            frappe.msgprint("请先选择一份食谱。");
            return;
        }
        try {
            const response = await frappe.call({
                method: "tongjianyun.nutrition_sheet.export_nutrition_sheet",
                args: this.filterArgs(),
                freeze: true,
                freeze_message: "正在生成同版Excel...",
            });
            const url = response.message?.file_url;
            if (url) window.open(url, "_blank", "noopener");
        } catch (error) {
            frappe.msgprint({ title: "导出失败", indicator: "red", message: error?.message || "请稍后重试" });
        }
    }

    openDashboard() {
        frappe.route_options = this.recipeControl.get_value() ? { recipe: this.recipeControl.get_value() } : null;
        frappe.set_route("query-report", "Weekly Recipe Nutrition Analysis");
    }

    openRecipePlan() {
        frappe.route_options = this.recipeControl.get_value() ? { recipe: this.recipeControl.get_value() } : null;
        frappe.set_route("tongjianyun-recipe-workbench");
    }

    installStyles() {
        if (document.getElementById("tjy-nutrition-sheet-styles")) return;
        const style = document.createElement("style");
        style.id = "tjy-nutrition-sheet-styles";
        style.textContent = `
            .tjy-nutrition-sheet-page { padding: 4px 0 28px; color: var(--text-color); }
            .tjy-sheet-heading { display:flex; align-items:flex-end; justify-content:space-between; gap:20px; margin:8px 4px 16px; }
            .tjy-sheet-kicker { color:var(--text-muted); font-size:12px; font-weight:600; letter-spacing:.08em; text-transform:uppercase; }
            .tjy-sheet-heading h2 { margin:4px 0 3px; font-size:21px; font-weight:700; }
            .tjy-sheet-heading p { margin:0; color:var(--text-muted); }
            .tjy-sheet-legend { white-space:nowrap; color:var(--text-muted); font-size:12px; }
            .tjy-sheet-legend span { display:inline-block; width:9px; height:9px; border-radius:50%; margin:0 5px 0 12px; }
            .tjy-sheet-legend .good { background:#2f9e44; }
            .tjy-sheet-legend .warn { background:#e03131; }
            .tjy-sheet-scroll { overflow:auto; border:1px solid #1f2937; border-radius:8px; background:#fff; box-shadow:0 10px 28px rgba(15,23,42,.07); }
            .tjy-nutrition-sheet { width:1660px; table-layout:fixed; border-collapse:collapse; color:#111827; background:#fff; font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif; font-size:12px; }
            .tjy-nutrition-sheet th, .tjy-nutrition-sheet td { border:1px solid #111827; padding:3px 5px; text-align:center; vertical-align:middle; line-height:1.35; overflow-wrap:anywhere; }
            .tjy-nutrition-sheet thead th { background:#f3f6f9; font-weight:700; }
            .tjy-nutrition-sheet thead tr:first-child th { height:34px; font-size:13px; background:#eaf0f5; }
            .tjy-nutrition-sheet thead tr:nth-child(2) th { height:32px; }
            .tjy-nutrition-sheet tbody tr { height:27px; }
            .tjy-nutrition-sheet .group-cell { background:#f7f9fb; font-weight:700; }
            .tjy-nutrition-sheet .subgroup-cell { background:#fbfcfd; font-weight:600; }
            .tjy-nutrition-sheet .food-cell { text-align:left; white-space:normal; }
            .tjy-nutrition-sheet .weight-cell { font-variant-numeric:tabular-nums; }
            .tjy-nutrition-sheet .analysis-section { background:#f3f6f9; font-weight:700; }
            .tjy-nutrition-sheet .analysis-note { text-align:left; padding:10px; line-height:1.7; background:#fbfcfd; }
            .tjy-nutrition-sheet .nutrient-group { background:#f7f9fb; font-weight:700; }
            .tjy-nutrition-sheet .nutrient-label { text-align:left; padding-left:7px; }
            .tjy-nutrition-sheet .number-cell { font-variant-numeric:tabular-nums; }
            .tjy-nutrition-sheet .evaluation { font-weight:700; }
            .tjy-nutrition-sheet .evaluation.good { color:#217a35; background:#ebfbee; }
            .tjy-nutrition-sheet .evaluation.warn { color:#c92a2a; background:#fff0f0; }
            .tjy-nutrition-sheet .blank-panel { background:#fff; }
            .tjy-nutrition-sheet .conclusion-label { font-size:14px; font-weight:700; background:#f3f6f9; }
            .tjy-nutrition-sheet .conclusion { text-align:left; padding:14px 18px; line-height:1.8; font-size:13px; }
            .tjy-nutrition-sheet .group-col { width:72px; } .tjy-nutrition-sheet .subgroup-col { width:82px; }
            .tjy-nutrition-sheet .food-col { width:88px; } .tjy-nutrition-sheet .weight-col { width:58px; }
            .tjy-nutrition-sheet .analysis-label-col { width:104px; } .tjy-nutrition-sheet .analysis-value-col { width:66px; }
            .tjy-nutrition-sheet .nutrient-group-col { width:58px; } .tjy-nutrition-sheet .nutrient-label-col { width:122px; }
            .tjy-nutrition-sheet .nutrient-value-col { width:82px; }
            .tjy-sheet-footnote { margin:10px 4px 0; color:var(--text-muted); font-size:12px; line-height:1.6; }
            .tjy-sheet-loading, .tjy-sheet-error { min-height:320px; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:12px; color:var(--text-muted); border:1px dashed var(--border-color); border-radius:8px; }
            .tjy-sheet-error strong { color:var(--text-color); font-size:16px; }
            @media (max-width: 900px) { .tjy-sheet-heading { align-items:flex-start; flex-direction:column; } }
            @media print {
                @page { size:A3 landscape; margin:7mm; }
                body, .main-section, .layout-main-section { background:#fff !important; }
                .navbar, .page-head, .layout-side-section, .tjy-sheet-heading, .tjy-sheet-footnote { display:none !important; }
                .layout-main-section-wrapper, .layout-main-section, .page-body, .page-content { margin:0 !important; padding:0 !important; width:100% !important; max-width:none !important; }
                .tjy-sheet-scroll { overflow:visible; border:0; border-radius:0; box-shadow:none; }
                .tjy-nutrition-sheet { width:100%; font-size:7pt; }
                .tjy-nutrition-sheet th, .tjy-nutrition-sheet td { padding:1.5px 2px; }
            }
        `;
        document.head.appendChild(style);
    }
}

function buildFoodRows(analysis) {
    const totals = analysis.category_totals || {};
    const allItems = analysis.ingredients || [];
    const rows = [];
    for (const group of FOOD_LAYOUT) {
        const groupRows = group.children.reduce((total, child) => total + child.rows, 0);
        const groupTotal = group.children.reduce((total, child) => total + numberValue(totals[child.key]), 0);
        group.children.forEach((child, childIndex) => {
            const items = allItems.filter((item) => item.category === child.key);
            for (let rowIndex = 0; rowIndex < child.rows; rowIndex += 1) {
                rows.push({
                    groupLabel: group.label,
                    groupTotal,
                    groupRows,
                    groupStart: childIndex === 0 && rowIndex === 0,
                    single: Boolean(group.single),
                    childLabel: child.label,
                    childTotal: numberValue(totals[child.key]),
                    childRows: child.rows,
                    childStart: rowIndex === 0,
                    childRowIndex: rowIndex,
                    items,
                });
            }
        });
    }
    return rows;
}

function renderFoodCells(row) {
    let html = "";
    if (row.groupStart) {
        html += `<td class="group-cell" rowspan="${row.groupRows}" ${row.single ? 'colspan="2"' : ""}>${escapeHtml(row.groupLabel)}<br>${formatNumber(row.groupTotal)}</td>`;
    }
    if (!row.single && row.childStart) {
        html += `<td class="subgroup-cell" rowspan="${row.childRows}">${escapeHtml(row.childLabel)}<br>${formatNumber(row.childTotal)}</td>`;
    }
    for (let pair = 0; pair < 5; pair += 1) {
        const index = row.childRowIndex * 5 + pair;
        const isLastSlot = row.childRowIndex === row.childRows - 1 && pair === 4;
        const items = isLastSlot ? row.items.slice(index) : row.items.slice(index, index + 1);
        html += `<td class="food-cell">${items.map((item) => escapeHtml(item.name)).join("<br>")}</td>`;
        html += `<td class="weight-cell">${items.map((item) => formatNumber(item.grams)).join("<br>")}</td>`;
    }
    return html;
}

function renderAnalysisCells(index, analysis, recipe) {
    if (index === 0) return `<td colspan="2" class="number-cell">${formatNumber(analysis.person_days, 0)}</td>`;
    if (index === 1) return '<td colspan="2" class="analysis-section">各餐热量标准分配比例</td>';
    if (index >= 2 && index <= 6) {
        const [key, label] = MEALS[index - 2];
        return `<td>${label}</td><td class="number-cell">${formatNumber(analysis.meal_standard[key], 0)}%</td>`;
    }
    if (index === 7) return '<td colspan="2" class="analysis-section">各餐热量实给分配比例</td>';
    if (index >= 8 && index <= 12) {
        const [key, label] = MEALS[index - 8];
        return `<td>${label}</td><td class="number-cell">${formatNumber(analysis.meal_ratio[key])}%</td>`;
    }
    if (index === 13) return '<td colspan="2" class="analysis-section">钙/磷之比例</td>';
    if (index === 14) return '<td>标准比例</td><td>1.2–2.0</td>';
    if (index === 15) return `<td>实给比例</td><td class="number-cell">${formatNumber(analysis.calcium_phosphorus_ratio, 2)}</td>`;
    if (index === 16) return `<td colspan="2">胡萝卜素实给量：<strong>${formatNumber(analysis.nutrients.carotene)} μg</strong></td>`;
    if (index === 17) return '<td colspan="2"></td>';
    if (index === 18) return `<td colspan="2">纤维实给量：<strong>${formatNumber(analysis.nutrients.fiber)} g</strong></td>`;
    if (index === 19) return '<td colspan="2"></td>';
    if (index === 20) return `<td colspan="2">胆固醇实给量：<strong>${formatNumber(analysis.nutrients.cholesterol)} mg</strong></td>`;
    if (index === 21) return '<td colspan="2"></td>';
    if (index === 22) {
        const population = populationSummary(analysis.standard.population);
        return `<td colspan="9" rowspan="6" class="analysis-note">
            <strong>食谱：</strong>${escapeHtml(recipe.title || recipe.recipe_id || recipe.name)}<br>
            <strong>日期：</strong>${escapeHtml(recipe.week_start || "—")} 至 ${escapeHtml(recipe.week_end || "—")}<br>
            <strong>标准：</strong>${escapeHtml(analysis.standard.profile)}；在园目标按全日 ${formatNumber(analysis.standard.garden_ratio * 100, 0)}% 计算。${population ? `<br><strong>统计学生：</strong>${population}` : ""}<br>
            <strong>数据口径：</strong>食物成分采用分类代表值估算。
        </td>`;
    }
    if (index === 28) return '<td colspan="2" rowspan="6" class="conclusion-label">结论建议</td>';
    return "";
}

function buildNutritionRows(analysis) {
    const standard = analysis.standard;
    const ratio = numberValue(standard.garden_ratio);
    const nutrients = analysis.nutrients || {};
    const rows = [];
    const nutrient = (key, label, options = {}) => {
        const full = numberValue(standard[key]);
        const garden = full * ratio;
        const actual = numberValue(nutrients[key]);
        const percent = garden ? actual / garden * 100 : 0;
        rows.push({
            ...options,
            label,
            full: formatNumber(full, 2),
            garden: formatNumber(garden, 2),
            actual: formatNumber(actual, 2),
            rate: `${formatNumber(percent)}%`,
            evaluation: evaluateNutrient(key, percent),
        });
    };
    nutrient("energy", "热量（kcal）", { group: "热量", groupRows: 4 });
    for (const [key, label, rangeKey] of [
        ["carbohydrate", "碳水化合物供热", "carbohydrate_energy_range"],
        ["fat", "脂肪供热", "fat_energy_range"],
        ["protein", "蛋白质供热", "protein_energy_range"],
    ]) {
        const range = standard[rangeKey] || [0, 0];
        const actual = numberValue(analysis.macro_energy_ratio[key]);
        rows.push({
            label,
            full: `${range[0]}–${range[1]}%`,
            garden: `${range[0]}–${range[1]}%`,
            actual: `${formatNumber(actual)}%`,
            rate: `${formatNumber(actual)}%`,
            evaluation: actual >= range[0] && actual <= range[1] ? "适宜" : (actual < range[0] ? "偏低" : "偏高"),
        });
    }
    nutrient("protein", "总量（g）", { group: "蛋白质", groupRows: 3 });
    const protein = numberValue(nutrients.protein);
    for (const [label, actual, target] of [
        ["动物蛋白", numberValue(analysis.animal_protein), 30],
        ["动豆蛋白", numberValue(analysis.animal_soy_protein), 50],
    ]) {
        const percent = protein ? actual / protein * 100 : 0;
        rows.push({
            label,
            full: "—",
            garden: `≥${target}%`,
            actual: formatNumber(actual, 2),
            rate: `${formatNumber(percent)}%`,
            evaluation: percent >= target ? "适宜" : "偏低",
        });
    }
    nutrient("calcium", "总量（mg）", { group: "钙", groupRows: 1 });
    nutrient("vitamin_a", "维生素A/视黄醇（μg RAE）", { standalone: true });
    nutrient("vitamin_b1", "维生素B1（mg）", { standalone: true });
    nutrient("vitamin_b2", "维生素B2（mg）", { standalone: true });
    nutrient("vitamin_c", "维生素C（mg）", { standalone: true });
    nutrient("vitamin_e", "维生素E（mg α-TE）", { standalone: true });
    nutrient("niacin", "维生素PP/烟酸（mg NE）", { standalone: true });
    nutrient("potassium", "钾（mg）", { standalone: true });
    nutrient("magnesium", "镁（mg）", { standalone: true });
    nutrient("iron", "铁（mg）", { standalone: true });
    nutrient("zinc", "锌（mg）", { standalone: true });
    nutrient("phosphorus", "磷（mg）", { standalone: true });
    nutrient("selenium", "硒（μg）", { standalone: true });
    return rows;
}

function renderNutritionCells(index, rows, analysis) {
    if (index < 20) {
        const row = rows[index];
        let html = "";
        if (row.group) html += `<td class="nutrient-group" rowspan="${row.groupRows}">${escapeHtml(row.group)}</td>`;
        html += row.standalone
            ? `<td colspan="2" class="nutrient-label">${escapeHtml(row.label)}</td>`
            : `<td class="nutrient-label">${escapeHtml(row.label)}</td>`;
        html += `<td class="number-cell">${escapeHtml(row.full)}</td><td class="number-cell">${escapeHtml(row.garden)}</td><td class="number-cell">${escapeHtml(row.actual)}</td><td class="number-cell">${escapeHtml(row.rate)}</td><td class="evaluation ${row.evaluation === "适宜" ? "good" : "warn"}">${escapeHtml(row.evaluation)}</td>`;
        return html;
    }
    if (index === 20) return '<td colspan="7" rowspan="2" class="blank-panel"></td>';
    if (index === 28) return `<td colspan="7" rowspan="6" class="conclusion">${escapeHtml(analysis.conclusion || "暂无结论")}</td>`;
    return "";
}

function evaluateNutrient(key, percent) {
    if (key === "energy") return percent >= 90 && percent <= 110 ? "适宜" : (percent < 90 ? "偏低" : "偏高");
    if (key === "protein") return percent >= 80 && percent <= 120 ? "适宜" : (percent < 80 ? "偏低" : "偏高");
    return percent >= 80 ? "适宜" : "偏低";
}

function numberValue(value) {
    const numeric = Number(value || 0);
    return Number.isFinite(numeric) ? numeric : 0;
}

function formatNumber(value, digits = 1) {
    const numeric = numberValue(value);
    const fixed = numeric.toFixed(digits);
    return fixed.includes(".") ? fixed.replace(/0+$/, "").replace(/\.$/, "") : fixed;
}

function populationSummary(population) {
    if (!population || !Number(population.student_count)) return "";
    const groups = (population.groups || []).map((group) => String(group)).join("、") || "全部启用班级";
    const composition = (population.composition || [])
        .map((item) => `${item.label} ${item.count}人`)
        .join("、") || "年龄性别构成未记录";
    return `统计 ${formatNumber(population.student_count, 0)} 人（${escapeHtml(groups)}；${escapeHtml(composition)}）`;
}

function escapeHtml(value) {
    return frappe.utils.escape_html(String(value ?? ""));
}
