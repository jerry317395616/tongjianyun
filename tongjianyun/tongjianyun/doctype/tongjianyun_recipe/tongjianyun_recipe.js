frappe.ui.form.on("Tongjianyun Recipe", {
    refresh(frm) {
        if (frm.is_new()) {
            frm.fields_dict.recipe_detail_html.$wrapper.html(
                '<div class="text-muted">保存食谱后显示菜品和食材明细。</div>',
            );
            return;
        }
        load_recipe_detail(frm);
    },
});

async function load_recipe_detail(frm) {
    const wrapper = frm.fields_dict.recipe_detail_html.$wrapper;
    wrapper.html(`
        <div class="tjy-recipe-loading text-muted">
            ${frappe.utils.icon("loader", "sm")}<span>正在加载食谱明细...</span>
        </div>
    `);
    try {
        const response = await frappe.call({
            method: "tongjianyun.recipe_storage.get_recipe_detail",
            args: { recipe: frm.doc.name },
        });
        render_recipe_detail(wrapper, response.message || {});
    } catch (error) {
        wrapper.html(`
            <div class="tjy-recipe-error">
                <span>食谱明细加载失败。</span>
                <button type="button" class="btn btn-xs btn-default tjy-recipe-retry">重新加载</button>
            </div>
        `);
        wrapper.find(".tjy-recipe-retry").on("click", () => load_recipe_detail(frm));
    }
}

function render_recipe_detail(wrapper, payload) {
    const days = Array.isArray(payload.days) ? payload.days : [];
    const dish_count = days.reduce(
        (total, day) => total + (day.portions || []).reduce((sum, portion) => sum + (portion.dishes || []).length, 0),
        0,
    );
    const ingredient_rows = days.flatMap((day) =>
        (day.portions || []).flatMap((portion) => portion.dishIngredientRows || []),
    );
    const ingredient_count = new Set(ingredient_rows.map((row) => row.ingredient).filter(Boolean)).size;

    const content = days.length
        ? days.map((day) => render_recipe_day(day)).join("")
        : '<div class="tjy-recipe-empty text-muted">该食谱暂时没有菜品明细。</div>';

    wrapper.html(`
        <style>
            .tjy-recipe-detail { border-top: 1px solid var(--border-color); }
            .tjy-recipe-summary { display: flex; flex-wrap: wrap; gap: 20px; padding: 12px 4px; color: var(--text-muted); }
            .tjy-recipe-summary strong { color: var(--text-color); font-size: 15px; margin-right: 4px; }
            .tjy-recipe-day { border-bottom: 1px solid var(--border-color); }
            .tjy-recipe-day summary { cursor: pointer; display: flex; align-items: center; gap: 10px; padding: 13px 4px; font-weight: 600; color: var(--text-color); list-style: none; }
            .tjy-recipe-day summary::-webkit-details-marker { display: none; }
            .tjy-recipe-day summary::before { content: "›"; font-size: 20px; line-height: 1; color: var(--text-muted); transform: rotate(0deg); transition: transform 120ms ease; }
            .tjy-recipe-day[open] summary::before { transform: rotate(90deg); }
            .tjy-recipe-date { color: var(--text-muted); font-weight: 400; }
            .tjy-recipe-table-wrap { overflow-x: auto; padding: 0 0 14px 28px; }
            .tjy-recipe-table { width: 100%; min-width: 680px; border-collapse: collapse; table-layout: fixed; }
            .tjy-recipe-table th { color: var(--text-muted); font-size: 12px; font-weight: 500; text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--border-color); }
            .tjy-recipe-table td { vertical-align: top; padding: 11px 10px; border-bottom: 1px solid var(--border-color); }
            .tjy-recipe-table tbody tr:last-child td { border-bottom: 0; }
            .tjy-meal-slot { width: 14%; color: var(--text-muted); }
            .tjy-dish-name { width: 28%; font-weight: 600; color: var(--text-color); }
            .tjy-ingredient-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 5px 14px; }
            .tjy-ingredient-item { display: flex; justify-content: space-between; gap: 10px; min-width: 0; }
            .tjy-ingredient-name { overflow-wrap: anywhere; color: var(--text-color); }
            .tjy-ingredient-grams { white-space: nowrap; color: var(--text-muted); font-variant-numeric: tabular-nums; }
            .tjy-recipe-loading, .tjy-recipe-error, .tjy-recipe-empty { display: flex; align-items: center; gap: 8px; min-height: 64px; }
            @media (max-width: 767px) {
                .tjy-recipe-summary { gap: 10px 16px; }
                .tjy-recipe-table-wrap { padding-left: 0; }
            }
        </style>
        <div class="tjy-recipe-detail">
            <div class="tjy-recipe-summary">
                <span><strong>${days.length}</strong>天</span>
                <span><strong>${dish_count}</strong>道菜品</span>
                <span><strong>${ingredient_rows.length}</strong>条食材明细</span>
                <span><strong>${ingredient_count}</strong>种食材</span>
            </div>
            ${content}
        </div>
    `);
}

function render_recipe_day(day) {
    const portions = Array.isArray(day.portions) ? day.portions : [];
    const rows = portions.flatMap((portion) => render_portion_rows(portion));
    return `
        <details class="tjy-recipe-day" open>
            <summary>
                <span>${escape_html(day.day || "未命名日期")}</span>
                <span class="tjy-recipe-date">${escape_html(day.date || "")}</span>
            </summary>
            <div class="tjy-recipe-table-wrap">
                <table class="tjy-recipe-table">
                    <thead><tr><th class="tjy-meal-slot">餐次</th><th class="tjy-dish-name">菜品</th><th>食材与每人克重</th></tr></thead>
                    <tbody>${rows.join("")}</tbody>
                </table>
            </div>
        </details>
    `;
}

function render_portion_rows(portion) {
    const dishes = Array.isArray(portion.dishes) ? portion.dishes : [];
    const ingredient_rows = Array.isArray(portion.dishIngredientRows) ? portion.dishIngredientRows : [];
    return dishes.map((dish_name, index) => {
        const ingredients = ingredient_rows.filter((row) => row.dishName === dish_name);
        const ingredient_html = ingredients.length
            ? ingredients.map((row) => render_ingredient(row)).join("")
            : '<span class="text-muted">暂无食材克重</span>';
        return `
            <tr>
                <td class="tjy-meal-slot">${index === 0 ? escape_html(portion.label || portion.slot || "") : ""}</td>
                <td class="tjy-dish-name">${escape_html(dish_name)}</td>
                <td><div class="tjy-ingredient-list">${ingredient_html}</div></td>
            </tr>
        `;
    });
}

function render_ingredient(row) {
    const grams = Number(row.gramsPerChild);
    const amount = Number(row.amount);
    const weight = Number.isFinite(grams) && grams > 0
        ? `${format_number(grams)} g`
        : `${format_number(amount)} ${escape_html(row.unit || "g")}`;
    return `
        <span class="tjy-ingredient-item">
            <span class="tjy-ingredient-name">${escape_html(row.ingredient || "未命名食材")}</span>
            <span class="tjy-ingredient-grams">${weight}</span>
        </span>
    `;
}

function format_number(value) {
    if (!Number.isFinite(value)) return "0";
    return Number(value.toFixed(3)).toString();
}

function escape_html(value) {
    return frappe.utils.escape_html(String(value ?? ""));
}
