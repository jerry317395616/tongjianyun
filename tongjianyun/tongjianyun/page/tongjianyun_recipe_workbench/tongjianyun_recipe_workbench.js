frappe.pages["tongjianyun-recipe-workbench"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "食谱",
        single_column: true,
    });
    new TongjianyunRecipePage(page, wrapper);
};

class TongjianyunRecipePage {
    constructor(page, wrapper) {
        this.page = page;
        this.wrapper = $(wrapper);
        this.state = {
            screen: "browse",
            selectedRecipe: null,
            payload: null,
            activeDay: 0,
            activeSlot: "breakfast",
            activeDish: 0,
            selectedBrowseCell: null,
            library: [],
            librarySearch: "",
        };
        this.mount();
        this.bindPageActions();
        this.loadInitialRecipe();
    }

    mount() {
        this.main = $('<div class="tjy-recipe-app"></div>').appendTo(this.page.main);
        this.installStyles();
    }

    bindPageActions() {
        this.page.set_primary_action("编辑食谱", () => this.enterEdit(), "edit");
        this.page.add_menu_item("全部食谱", () => this.showLibrary());
        this.page.add_menu_item("新建食谱", () => this.createRecipe());
    }

    async loadInitialRecipe() {
        this.showLoading("正在加载食谱...");
        try {
            const routeOptions = frappe.route_options || {};
            frappe.route_options = null;
            const requested = routeOptions.recipe || this.getRecipeFromUrl();
            if (requested) {
                await this.loadRecipe(requested);
                return;
            }
            const current = await frappe.call({
                method: "tongjianyun.recipe_storage.get_current_recipe",
            });
            if (current.message) {
                this.state.payload = normalizePayload(current.message);
                this.state.selectedRecipe = current.message.recipe?.recipeId || "current";
                this.showBrowse();
                return;
            }
            await this.showLibrary();
        } catch (error) {
            this.showError("食谱加载失败", error);
        }
    }

    getRecipeFromUrl() {
        const query = new URLSearchParams(window.location.search);
        return query.get("recipe") || "";
    }

    async loadRecipe(recipe) {
        this.showLoading("正在加载食谱...");
        try {
            const response = await frappe.call({
                method: "tongjianyun.recipe_storage.get_recipe_detail",
                args: { recipe },
            });
            this.state.payload = normalizePayload(response.message || {});
            this.state.selectedRecipe = recipe;
            this.state.activeDay = 0;
            this.state.activeSlot = "breakfast";
            this.state.activeDish = 0;
            this.showBrowse();
        } catch (error) {
            this.showError("无法打开该食谱", error);
        }
    }

    showBrowse() {
        this.state.screen = "browse";
        this.page.set_title("食谱 · 周历总览");
        this.page.set_primary_action("编辑食谱", () => this.enterEdit(), "edit");
        const payload = this.state.payload || normalizePayload({});
        const recipe = payload.recipe;
        const days = payload.days;
        const summary = getSummary(payload);
        const selection = this.getBrowseSelection(days);
        const selectedDay = days[selection.dayIndex];
        const selectedPortion = findPortion(selectedDay, selection.slot);
        const mealRows = MEAL_SLOTS.map((slot) => `
            <div class="tjy-week-label">${MEAL_LABELS[slot]}</div>
            ${days.map((day, dayIndex) => this.renderBrowseCell(day, dayIndex, slot)).join("")}
        `).join("");

        this.main.html(`
            <section class="tjy-screen tjy-browse-screen">
                <header class="tjy-browse-head">
                    <div>
                        <div class="tjy-title-line">
                            <h1>${escapeHtml(getWeekTitle(recipe))}</h1>
                            <span class="tjy-draft-pill">草稿</span>
                        </div>
                        <div class="tjy-week-switcher">
                            <button class="tjy-square-button" data-action="previous" aria-label="上一份食谱">‹</button>
                            <button class="tjy-square-button" data-action="calendar" aria-label="日期">${frappe.utils.icon("calendar", "sm")}</button>
                            <button class="tjy-square-button" data-action="next" aria-label="下一份食谱">›</button>
                            <span class="tjy-switcher-divider"></span>
                            <strong>${formatFriendlyRange(recipe.weekStart, recipe.weekEnd)}</strong>
                        </div>
                    </div>
                    <div class="tjy-hero-actions">
                        <button class="tjy-outline-button" data-action="import">${frappe.utils.icon("upload", "sm")}<span>导入食谱</span></button>
                        <button class="tjy-primary-button" data-action="edit">编辑食谱</button>
                    </div>
                </header>
                <div class="tjy-summary-card">
                    <div class="tjy-summary-item"><span class="tjy-summary-icon">${frappe.utils.icon("calendar", "md")}</span><div><strong>${formatFriendlyRange(recipe.weekStart, recipe.weekEnd)}</strong><small>${escapeHtml(getRecipeYear(recipe))} · ${escapeHtml(getWeekLabel(recipe))}</small></div></div>
                    <div class="tjy-summary-item"><span class="tjy-summary-icon">♨</span><div><strong>${days.length} 天</strong><small>覆盖天数</small></div></div>
                    <div class="tjy-summary-item"><span class="tjy-summary-icon">▱</span><div><strong>${days.length * MEAL_SLOTS.length} 餐次</strong><small>每日 ${MEAL_SLOTS.length} 餐</small></div></div>
                    <div class="tjy-summary-item"><span class="tjy-summary-icon">⌒</span><div><strong>${summary.dishes} 道菜</strong><small>本周总计</small></div></div>
                </div>
                <div class="tjy-browse-layout">
                    <div class="tjy-week-scroll">
                        <div class="tjy-week-grid" style="--day-count:${Math.max(days.length, 1)}">
                            <div class="tjy-week-corner"></div>
                            ${days.map((day) => `
                                <div class="tjy-week-day-head">
                                    <strong>${escapeHtml(shortWeekday(day.day))}</strong>
                                    <span>${formatShortDate(day.date)}</span>
                                </div>
                            `).join("")}
                            ${mealRows || '<div class="tjy-empty-inline">暂无食谱明细</div>'}
                        </div>
                    </div>
                    ${this.renderBrowseInspector(selectedDay, selectedPortion, selection)}
                </div>
                <details class="tjy-source-details">
                    <summary>导入信息</summary>
                    <div class="tjy-source-grid">
                        <span>原始文件</span><strong>${escapeHtml(recipe.sourceFileName || "无")}</strong>
                        <span>解析方式</span><strong>${escapeHtml(recipe.parser || "未记录")}</strong>
                        <span>关系来源</span><strong>${escapeHtml(recipe.relationSource || "未记录")}</strong>
                        <span>导入时间</span><strong>${escapeHtml(recipe.importedAt || "未记录")}</strong>
                    </div>
                </details>
            </section>
        `);
        this.bindCommonActions();
        this.main.find("[data-cell]").on("click", (event) => {
            const target = $(event.currentTarget);
            this.state.selectedBrowseCell = {
                dayIndex: Number(target.attr("data-day")),
                slot: target.attr("data-slot"),
            };
            this.showBrowse();
        });
        this.main.find('[data-action="edit-selected"]').on("click", () => {
            this.state.activeDay = selection.dayIndex;
            this.state.activeSlot = selection.slot;
            this.state.activeDish = 0;
            this.enterEdit();
        });
    }

    renderBrowseCell(day, dayIndex, slot) {
        const portion = findPortion(day, slot);
        const dishes = portion?.dishes || [];
        return `
            <button class="tjy-week-cell ${dishes.length ? "has-content" : ""} ${this.isBrowseCellSelected(dayIndex, slot) ? "selected" : ""}" data-cell data-day="${dayIndex}" data-slot="${slot}">
                ${dishes.length
                    ? dishes.map((dish) => `<span>${escapeHtml(dish)}</span>`).join("")
                    : '<span class="tjy-cell-empty">未安排</span>'}
            </button>
        `;
    }

    getBrowseSelection(days) {
        const current = this.state.selectedBrowseCell;
        if (current && days[current.dayIndex]) return current;
        const preferredDay = Math.min(3, Math.max(0, days.length - 1));
        const preferredSlot = findPortion(days[preferredDay], "lunch") ? "lunch" : "breakfast";
        this.state.selectedBrowseCell = { dayIndex: preferredDay, slot: preferredSlot };
        return this.state.selectedBrowseCell;
    }

    isBrowseCellSelected(dayIndex, slot) {
        return this.state.selectedBrowseCell?.dayIndex === dayIndex && this.state.selectedBrowseCell?.slot === slot;
    }

    renderBrowseInspector(day, portion, selection) {
        const dishes = portion?.dishes || [];
        const rows = portion?.dishIngredientRows || [];
        return `
            <aside class="tjy-browse-inspector">
                <div class="tjy-inspector-head">
                    <strong>已选择：${escapeHtml(shortWeekday(day?.day || ""))} · ${MEAL_LABELS[selection.slot]}</strong>
                    <button class="tjy-icon-button" data-action="edit-selected" title="编辑此餐">${frappe.utils.icon("edit", "sm")}</button>
                </div>
                <div class="tjy-inspector-section">
                    <h3>菜品</h3>
                    ${dishes.length ? `<ol class="tjy-dish-summary">${dishes.map((dish) => `<li>${escapeHtml(dish)}</li>`).join("")}</ol>` : '<div class="tjy-inspector-empty">本餐尚未安排菜品</div>'}
                </div>
                <div class="tjy-inspector-section tjy-inspector-ingredients">
                    <h3>食材与用量 <span>（每人食谱）</span></h3>
                    ${rows.length ? `
                        <div class="tjy-inspector-table">
                            <div class="tjy-inspector-tr head"><span>食材</span><span>净用量</span><span>单位</span></div>
                            ${rows.map((row) => `<div class="tjy-inspector-tr"><span>${escapeHtml(row.ingredient || "未命名食材")}</span><span>${formatNumber(row.amount ?? row.gramsPerChild ?? 0)}</span><span>${escapeHtml(row.unit || "g")}</span></div>`).join("")}
                        </div>
                    ` : '<div class="tjy-inspector-empty">暂无食材用量</div>'}
                    <p class="tjy-inspector-note">食材用量为供餐净量，可根据实际就餐人数调整</p>
                </div>
                <button class="tjy-inspector-edit" data-action="edit-selected">编辑此餐</button>
            </aside>
        `;
    }

    enterEdit() {
        if (!this.state.payload) return;
        this.state.screen = "edit";
        this.page.set_title("食谱 · 餐次工作台");
        this.page.set_primary_action("保存食谱", () => this.saveRecipe(), "check");
        this.renderEditor();
    }

    renderEditor() {
        const payload = this.state.payload;
        const days = payload.days;
        if (!days.length) this.addInitialDay();
        const day = payload.days[this.state.activeDay] || payload.days[0];
        const portion = ensurePortion(day, this.state.activeSlot);
        this.state.activeDish = Math.max(0, Math.min(this.state.activeDish, Math.max(0, portion.dishes.length - 1)));
        const selectedDish = portion.dishes[this.state.activeDish] || "";
        const relevantIngredients = portion.dishIngredientRows.filter(
            (row) => !selectedDish || row.dishName === selectedDish,
        );
        this.main.html(`
            <section class="tjy-screen tjy-edit-screen">
                <header class="tjy-editor-head">
                    <div class="tjy-editor-title-group">
                        <button class="tjy-back-button" data-action="browse" aria-label="返回周历">←</button>
                        <div>
                            <input class="tjy-title-input" type="text" value="${escapeAttr(payload.recipe.title || "未命名食谱")}" data-recipe-title aria-label="食谱名称">
                            <div class="tjy-date-inputs">
                                <input type="date" value="${escapeAttr(payload.recipe.weekStart || "")}" data-week-start aria-label="开始日期">
                                <span>—</span>
                                <input type="date" value="${escapeAttr(payload.recipe.weekEnd || "")}" data-week-end aria-label="结束日期">
                            </div>
                        </div>
                    </div>
                    <div class="tjy-hero-actions">
                        <span class="tjy-save-state"><i></i> 已自动保存</span>
                        <button class="tjy-more-button" aria-label="更多">•••</button>
                        <button class="tjy-primary-button" data-action="save">保存更改</button>
                    </div>
                </header>
                <nav class="tjy-day-tabs">
                    ${payload.days.map((item, index) => `
                        <button class="tjy-day-tab ${index === this.state.activeDay ? "active" : ""}" data-day-tab="${index}">
                            <strong>${escapeHtml(item.day || `第 ${index + 1} 天`)}</strong>
                            <span>${formatShortDate(item.date)}</span>
                        </button>
                    `).join("")}
                </nav>
                <div class="tjy-workbench">
                    <aside class="tjy-meal-nav">
                        <div class="tjy-pane-label">餐次</div>
                        ${MEAL_SLOTS.map((slot) => `
                            <button class="tjy-meal-item ${slot === this.state.activeSlot ? "active" : ""}" data-meal="${slot}">
                                <span>${MEAL_LABELS[slot]}</span>
                                <small>${findPortion(day, slot)?.dishes?.length || 0}</small>
                            </button>
                        `).join("")}
                    </aside>
                    <main class="tjy-dish-pane">
                        <div class="tjy-pane-head">
                            <div><h2>${MEAL_LABELS[this.state.activeSlot]}</h2><span class="tjy-pane-count">${portion.dishes.length} 道菜品</span></div>
                            <button class="tjy-outline-button compact" data-action="add-dish">＋ 添加菜品</button>
                        </div>
                        <div class="tjy-dish-list">
                            ${portion.dishes.length
                                ? portion.dishes.map((dish, index) => this.renderDishRow(dish, index, index === this.state.activeDish)).join("")
                                : '<div class="tjy-empty-panel"><strong>尚未安排菜品</strong><span>点击“添加菜品”开始录入</span></div>'}
                        </div>
                    </main>
                    <aside class="tjy-ingredient-pane">
                        <div class="tjy-pane-head">
                            <div><h2>食材明细</h2></div>
                            ${selectedDish ? '<button class="tjy-outline-button compact" data-action="add-ingredient">＋ 添加食材</button>' : ""}
                        </div>
                        ${selectedDish ? `<div class="tjy-selected-dish"><strong>${escapeHtml(selectedDish)}</strong><span>${renderDishPortion(relevantIngredients)}</span></div><div class="tjy-ingredient-labels"><span>食材</span><span>每人用量</span><span>单位</span><span>操作</span></div>` : ""}
                        <div class="tjy-ingredient-editor">
                            ${selectedDish
                                ? relevantIngredients.map((row, index) => this.renderIngredientRow(row, index)).join("") || '<div class="tjy-empty-panel compact"><span>暂未录入食材</span></div>'
                                : '<div class="tjy-empty-panel compact"><span>先添加一个菜品</span></div>'}
                        </div>
                        ${selectedDish ? '<div class="tjy-nutrition"><h3>营养成分（每人）</h3><div class="tjy-nutrition-grid"><div><span>能量</span><strong>— kcal</strong></div><div><span>蛋白质</span><strong>— g</strong></div><div><span>脂肪</span><strong>— g</strong></div><div><span>碳水化合物</span><strong>— g</strong></div><div><span>钙</span><strong>— mg</strong></div><div><span>铁</span><strong>— mg</strong></div><div><span>锌</span><strong>— mg</strong></div><div><span>维生素 A</span><strong>— μg RE</strong></div></div><p>ⓘ 营养数据为估算值，仅供参考</p></div>' : ""}
                    </aside>
                </div>
            </section>
        `);
        this.bindEditorActions(day, portion, selectedDish);
    }

    renderDishRow(dish, index, selected) {
        return `
            <div class="tjy-dish-row ${selected ? "selected" : ""}" data-select-dish="${index}">
                <span class="tjy-drag-handle">⋮⋮</span>
                <span class="tjy-dish-index">${index + 1}</span>
                <input type="text" value="${escapeAttr(dish)}" data-dish-input="${index}" aria-label="菜品名称">
                <span class="tjy-row-edit">${frappe.utils.icon("edit", "sm")}</span>
                <button class="tjy-icon-button" data-remove-dish="${index}" title="删除">×</button>
            </div>
        `;
    }

    renderIngredientRow(row, index) {
        return `
            <div class="tjy-ingredient-row">
                <input type="text" value="${escapeAttr(row.ingredient || "")}" data-ingredient-name="${index}" placeholder="食材">
                <input type="number" min="0" step="0.1" value="${escapeAttr(row.amount ?? row.gramsPerChild ?? 0)}" data-ingredient-amount="${index}" aria-label="每人克重">
                <select data-ingredient-unit="${index}">
                    ${["g", "kg", "mg"].map((unit) => `<option ${unit === (row.unit || "g") ? "selected" : ""}>${unit}</option>`).join("")}
                </select>
                <button class="tjy-icon-button" data-remove-ingredient="${index}" title="删除">×</button>
            </div>
        `;
    }

    bindEditorActions(day, portion, selectedDish) {
        this.bindCommonActions();
        this.main.find("[data-day-tab]").on("click", (event) => {
            this.captureEditor(day, portion, selectedDish);
            this.state.activeDay = Number($(event.currentTarget).attr("data-day-tab"));
            this.state.activeDish = 0;
            this.renderEditor();
        });
        this.main.find("[data-meal]").on("click", (event) => {
            this.captureEditor(day, portion, selectedDish);
            this.state.activeSlot = $(event.currentTarget).attr("data-meal");
            this.state.activeDish = 0;
            this.renderEditor();
        });
        this.main.find("[data-select-dish]").on("click", (event) => {
            if ($(event.target).is("button,input")) return;
            const nextIndex = Number($(event.currentTarget).attr("data-select-dish"));
            if (nextIndex === this.state.activeDish) return;
            this.captureEditor(day, portion, selectedDish);
            this.state.activeDish = nextIndex;
            this.renderEditor();
            this.main.find(`[data-dish-input="${nextIndex}"]`).trigger("focus").select();
        });
        this.main.find("[data-dish-input]").on("focus", (event) => {
            const nextIndex = Number($(event.currentTarget).attr("data-dish-input"));
            if (nextIndex === this.state.activeDish) return;
            this.captureEditor(day, portion, selectedDish);
            this.state.activeDish = nextIndex;
            this.renderEditor();
            this.main.find(`[data-dish-input="${nextIndex}"]`).trigger("focus").select();
        });
        this.main.find('[data-action="add-dish"]').on("click", () => {
            this.captureEditor(day, portion, selectedDish);
            portion.dishes.push("新菜品");
            this.state.activeDish = portion.dishes.length - 1;
            this.renderEditor();
        });
        this.main.find("[data-remove-dish]").on("click", (event) => {
            const index = Number($(event.currentTarget).attr("data-remove-dish"));
            const removed = portion.dishes[index];
            portion.dishes.splice(index, 1);
            portion.dishIngredientRows = portion.dishIngredientRows.filter((row) => row.dishName !== removed);
            this.state.activeDish = Math.max(0, Math.min(this.state.activeDish, portion.dishes.length - 1));
            this.renderEditor();
        });
        this.main.find('[data-action="add-ingredient"]').on("click", () => {
            this.captureEditor(day, portion, selectedDish);
            const currentDish = portion.dishes[this.state.activeDish] || selectedDish;
            portion.dishIngredientRows.push({ dishName: currentDish, ingredient: "", amount: 0, unit: "g", gramsPerChild: 0 });
            this.renderEditor();
        });
        this.main.find("[data-remove-ingredient]").on("click", (event) => {
            const relevant = portion.dishIngredientRows.filter((row) => row.dishName === selectedDish);
            const row = relevant[Number($(event.currentTarget).attr("data-remove-ingredient"))];
            const realIndex = portion.dishIngredientRows.indexOf(row);
            if (realIndex >= 0) portion.dishIngredientRows.splice(realIndex, 1);
            this.renderEditor();
        });
    }

    captureEditor(day, portion, selectedDish) {
        const title = this.main.find("[data-recipe-title]").val();
        if (title !== undefined) this.state.payload.recipe.title = String(title || "").trim();
        const weekStart = this.main.find("[data-week-start]").val();
        const weekEnd = this.main.find("[data-week-end]").val();
        if (weekStart !== undefined) this.state.payload.recipe.weekStart = weekStart || "";
        if (weekEnd !== undefined) this.state.payload.recipe.weekEnd = weekEnd || "";
        const oldDishes = [...portion.dishes];
        const selectedOldName = oldDishes[this.state.activeDish] || selectedDish;
        this.main.find("[data-dish-input]").each((_, input) => {
            const index = Number($(input).attr("data-dish-input"));
            const oldName = oldDishes[index];
            const newName = String($(input).val() || "").trim();
            portion.dishes[index] = newName;
            if (oldName !== newName) {
                portion.dishIngredientRows.forEach((row) => {
                    if (row.dishName === oldName) row.dishName = newName;
                });
            }
        });
        if (!selectedDish) return;
        const currentDish = portion.dishes[this.state.activeDish] || selectedDish;
        const relevant = portion.dishIngredientRows.filter(
            (row) => row.dishName === selectedOldName || row.dishName === currentDish,
        );
        relevant.forEach((row, index) => {
            row.ingredient = String(this.main.find(`[data-ingredient-name="${index}"]`).val() || "").trim();
            row.amount = Number(this.main.find(`[data-ingredient-amount="${index}"]`).val() || 0);
            row.unit = this.main.find(`[data-ingredient-unit="${index}"]`).val() || "g";
            row.gramsPerChild = grams(row.amount, row.unit);
            row.dishName = currentDish;
        });
    }

    async saveRecipe() {
        const day = this.state.payload.days[this.state.activeDay];
        const portion = ensurePortion(day, this.state.activeSlot);
        this.captureEditor(day, portion, portion.dishes[this.state.activeDish] || "");
        if (!String(this.state.payload.recipe.title || "").trim()) {
            frappe.msgprint("食谱名称不能为空。");
            return;
        }
        const invalidDish = this.state.payload.days.some((item) =>
            item.portions.some((entry) => entry.dishes.some((dish) => !String(dish || "").trim())),
        );
        if (invalidDish) {
            frappe.msgprint("菜品名称不能为空。");
            return;
        }
        const button = this.main.find('[data-action="save"]');
        button.prop("disabled", true).text("正在保存...");
        try {
            const response = await frappe.call({
                method: "tongjianyun.recipe_storage.save_current_recipe",
                args: { payload: this.state.payload },
                freeze: true,
                freeze_message: "正在保存食谱...",
            });
            this.state.payload = normalizePayload(response.message || this.state.payload);
            frappe.show_alert({ message: "食谱已保存", indicator: "green" });
            this.showBrowse();
        } catch (error) {
            this.showError("食谱保存失败", error);
        } finally {
            button.prop("disabled", false).text("保存食谱");
        }
    }

    async showLibrary() {
        this.state.screen = "library";
        this.page.set_title("食谱库");
        this.page.set_primary_action("新建食谱", () => this.createRecipe(), "add");
        this.showLoading("正在加载食谱库...");
        try {
            const response = await frappe.call({
                method: "tongjianyun.recipe_storage.get_recipe_library",
                args: { search: this.state.librarySearch, page_length: 100 },
            });
            this.state.library = response.message?.items || [];
            this.renderLibrary();
        } catch (error) {
            this.showError("食谱库加载失败", error);
        }
    }

    renderLibrary() {
        const items = this.state.library;
        this.main.html(`
            <section class="tjy-screen tjy-library-screen">
                <header class="tjy-library-head">
                    <div><div class="tjy-eyebrow">童健云</div><h1>食谱库</h1><p>查找、查看和管理所有历史食谱</p></div>
                    <div class="tjy-hero-actions"><button class="btn btn-primary btn-sm" data-action="new">＋ 新建食谱</button></div>
                </header>
                <div class="tjy-library-tools">
                    <div class="tjy-search-wrap">${frappe.utils.icon("search", "sm")}<input type="search" value="${escapeAttr(this.state.librarySearch)}" placeholder="搜索食谱名称或周次"></div>
                    <span>${items.length} 份食谱</span>
                </div>
                <div class="tjy-library-table-wrap">
                    <table class="tjy-library-table">
                        <thead><tr><th>食谱</th><th>日期范围</th><th>状态</th><th>菜品</th><th>食材明细</th><th>最后更新</th><th></th></tr></thead>
                        <tbody>
                            ${items.length ? items.map((item) => `
                                <tr data-library-recipe="${escapeAttr(item.name)}">
                                    <td><strong>${escapeHtml(item.title || "未命名食谱")}</strong><span>${escapeHtml(item.recipe_id || "")}</span></td>
                                    <td>${formatDateRange(item.week_start, item.week_end)}</td>
                                    <td><span class="tjy-status ${item.status}">${item.status === "complete" ? "已完成" : "草稿"}</span></td>
                                    <td>${item.dish_count || 0}</td>
                                    <td>${item.ingredient_count || 0}</td>
                                    <td>${frappe.datetime.prettyDate(item.modified)}</td>
                                    <td><button class="tjy-row-open">打开 →</button></td>
                                </tr>
                            `).join("") : '<tr><td colspan="7"><div class="tjy-empty-panel"><strong>暂无食谱</strong><span>新建或导入一份食谱后会显示在这里</span></div></td></tr>'}
                        </tbody>
                    </table>
                </div>
            </section>
        `);
        this.main.find('[data-action="new"]').on("click", () => this.createRecipe());
        this.main.find("[data-library-recipe]").on("click", (event) => this.loadRecipe($(event.currentTarget).attr("data-library-recipe")));
        let timer;
        this.main.find('input[type="search"]').on("input", (event) => {
            clearTimeout(timer);
            timer = setTimeout(() => {
                this.state.librarySearch = String($(event.currentTarget).val() || "").trim();
                this.showLibrary();
            }, 300);
        });
    }

    createRecipe() {
        const today = frappe.datetime.get_today();
        const start = getMonday(today);
        const payload = normalizePayload({
            recipe: {
                recipeId: `RECIPE-${String(start).replaceAll("-", "")}-${Date.now().toString().slice(-6)}`,
                title: "新建周食谱",
                weekStart: start,
                weekEnd: frappe.datetime.add_days(start, 4),
            },
            days: Array.from({ length: 5 }, (_, index) => ({
                id: `DAY-${index + 1}`,
                date: frappe.datetime.add_days(start, index),
                day: ["星期一", "星期二", "星期三", "星期四", "星期五"][index],
                portions: [],
                version: 1,
            })),
        });
        this.state.payload = payload;
        this.state.selectedRecipe = null;
        this.state.activeDay = 0;
        this.state.activeSlot = "breakfast";
        this.state.activeDish = 0;
        this.enterEdit();
    }

    addInitialDay() {
        const start = this.state.payload.recipe.weekStart || frappe.datetime.get_today();
        this.state.payload.days.push({ id: "DAY-1", date: start, day: "星期一", portions: [], version: 1 });
        this.state.activeDay = 0;
    }

    bindCommonActions() {
        this.main.find('[data-action="library"]').on("click", () => this.showLibrary());
        this.main.find('[data-action="edit"]').on("click", () => this.enterEdit());
        this.main.find('[data-action="browse"]').on("click", () => this.showBrowse());
        this.main.find('[data-action="save"]').on("click", () => this.saveRecipe());
        this.main.find('[data-action="import"]').on("click", () => this.openImport());
        this.main.find('[data-action="calendar"]').on("click", () => this.enterEdit());
        this.main.find('[data-action="previous"]').on("click", () => this.openAdjacentRecipe(-1));
        this.main.find('[data-action="next"]').on("click", () => this.openAdjacentRecipe(1));
    }

    openImport() {
        frappe.set_route("data-import", "Tongjianyun Recipe");
    }

    openAdjacentRecipe(direction) {
        if (!this.state.library.length) {
            frappe.show_alert({ message: "请从食谱库选择其他周食谱", indicator: "blue" });
            return;
        }
        const current = this.state.library.findIndex((item) => item.name === this.state.selectedRecipe);
        const target = this.state.library[current + direction];
        if (target) this.loadRecipe(target.name);
        else frappe.show_alert({ message: direction < 0 ? "已经是最早一份食谱" : "已经是最新一份食谱", indicator: "blue" });
    }

    showLoading(message) {
        this.main.html(`<div class="tjy-loading">${frappe.utils.icon("loader", "md")}<span>${escapeHtml(message)}</span></div>`);
    }

    showError(title, error) {
        console.error(error);
        this.main.html(`<div class="tjy-error-card"><strong>${escapeHtml(title)}</strong><span>请刷新页面后重试。</span><button class="btn btn-default btn-sm" data-retry>重新加载</button></div>`);
        this.main.find("[data-retry]").on("click", () => this.loadInitialRecipe());
    }

    installStyles() {
        if (document.getElementById("tjy-recipe-page-styles")) return;
        $("<style>", { id: "tjy-recipe-page-styles", text: RECIPE_STYLES }).appendTo(document.head);
    }
}

const MEAL_SLOTS = ["breakfast", "morningSnack", "lunch", "snack", "dinner"];
const MEAL_LABELS = { breakfast: "早餐", morningSnack: "早点", lunch: "午餐", snack: "午点", dinner: "晚餐" };

function normalizePayload(payload) {
    const result = payload && typeof payload === "object" ? JSON.parse(JSON.stringify(payload)) : {};
    result.recipe = result.recipe || {};
    result.days = Array.isArray(result.days) ? result.days : [];
    result.days.forEach((day, index) => {
        day.id = day.id || `DAY-${index + 1}`;
        day.portions = Array.isArray(day.portions) ? day.portions : [];
        day.version = Math.max(1, Number(day.version || 1));
        day.portions.forEach((portion) => {
            portion.dishes = Array.isArray(portion.dishes) ? portion.dishes : [];
            portion.dishIngredientRows = Array.isArray(portion.dishIngredientRows) ? portion.dishIngredientRows : [];
        });
    });
    return result;
}

function ensurePortion(day, slot) {
    let portion = findPortion(day, slot);
    if (!portion) {
        portion = { slot, label: MEAL_LABELS[slot], dishes: [], amountPerChild: "", totalAmount: "", dishIngredientRows: [] };
        day.portions.push(portion);
    }
    return portion;
}

function findPortion(day, slot) {
    return (day?.portions || []).find((portion) => portion.slot === slot);
}

function getSummary(payload) {
    const portions = payload.days.flatMap((day) => day.portions || []);
    const rows = portions.flatMap((portion) => portion.dishIngredientRows || []);
    return {
        dishes: portions.reduce((sum, portion) => sum + (portion.dishes || []).length, 0),
        ingredientRows: rows.length,
        ingredients: new Set(rows.map((row) => row.ingredient).filter(Boolean)).size,
    };
}

function formatDateRange(start, end) {
    if (!start && !end) return "日期未设置";
    return `${escapeHtml(start || "—")} — ${escapeHtml(end || "—")}`;
}

function formatShortDate(value) {
    if (!value) return "—";
    const parts = String(value).split("-");
    return parts.length === 3 ? `${Number(parts[1])}月${Number(parts[2])}日` : escapeHtml(value);
}

function formatFriendlyRange(start, end) {
    if (!start && !end) return "日期未设置";
    const format = (value) => {
        const parts = String(value || "").split("-");
        return parts.length === 3 ? `${Number(parts[1])}月${Number(parts[2])}日` : value || "—";
    };
    return `${format(start)}—${format(end)}`;
}

function getWeekTitle(recipe) {
    const title = String(recipe.title || "").trim();
    const match = title.match(/第[^周]{1,8}周/);
    return match ? `${match[0]}食谱` : title || "周食谱";
}

function getWeekLabel(recipe) {
    const title = String(recipe.title || "");
    return title.match(/第[^周]{1,8}周/)?.[0] || recipe.recipeId || "周食谱";
}

function getRecipeYear(recipe) {
    return String(recipe.weekStart || "").split("-")[0] || "—";
}

function shortWeekday(value) {
    return String(value || "").replace("星期", "周");
}

function formatNumber(value) {
    const number = Number(value);
    return Number.isFinite(number) ? Number(number.toFixed(2)).toString() : "0";
}

function renderDishPortion(rows) {
    const grams = (rows || []).reduce((sum, row) => sum + Number(row.gramsPerChild || gramsFromRow(row) || 0), 0);
    return grams > 0 ? `每人 ${formatNumber(grams)} g` : "维护每人用量";
}

function gramsFromRow(row) {
    return grams(Number(row.amount || 0), row.unit || "g");
}

function grams(amount, unit) {
    if (unit === "kg") return amount * 1000;
    if (unit === "mg") return amount / 1000;
    return amount;
}

function getMonday(value) {
    const date = new Date(`${value}T00:00:00`);
    const day = date.getDay() || 7;
    date.setDate(date.getDate() - day + 1);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function escapeHtml(value) {
    return frappe.utils.escape_html(String(value ?? ""));
}

function escapeAttr(value) {
    return escapeHtml(value).replaceAll('"', "&quot;");
}

const RECIPE_STYLES = `
.tjy-recipe-app{--tjy-ink:#171717;--tjy-muted:#6b6b6b;--tjy-line:#e5e5e2;--tjy-soft:#f7f7f5;--tjy-green:#23884b;max-width:1540px;margin:0 auto;padding:18px 24px 60px;color:var(--tjy-ink)}
.page-head .page-title .title-text{font-weight:500}.page-head .primary-action{background:#171717!important;border-color:#171717!important}.tjy-screen button{font-family:inherit}
.tjy-screen h1,.tjy-screen h2,.tjy-screen p{margin:0}.tjy-screen h1{font-size:25px;line-height:1.25;letter-spacing:-.025em}.tjy-screen h2{font-size:16px;letter-spacing:-.01em}.tjy-screen p{color:var(--tjy-muted);margin-top:7px}.tjy-title-input{display:block;width:min(720px,70vw);border:0;background:transparent;padding:0;font-size:25px;font-weight:650;line-height:1.25;letter-spacing:-.025em;color:var(--tjy-ink);outline:0}.tjy-date-inputs{display:flex;align-items:end;gap:10px;margin-top:15px;color:var(--tjy-muted)}.tjy-date-inputs label{font-size:11px}.tjy-date-inputs input{display:block;border:1px solid var(--tjy-line);border-radius:7px;background:#fff;padding:5px 8px;margin-top:4px;color:var(--tjy-ink)}.tjy-hero,.tjy-editor-head,.tjy-library-head{display:flex;align-items:flex-start;justify-content:space-between;gap:30px;padding:8px 0 24px}.tjy-hero-actions{display:flex;gap:8px;flex:none}.tjy-link-button,.tjy-row-open{border:0;background:transparent;color:var(--tjy-muted);padding:0;cursor:pointer}.tjy-link-button{display:block;margin-bottom:22px}.tjy-link-button:hover,.tjy-row-open:hover{color:var(--tjy-ink)}.tjy-eyebrow,.tjy-pane-label{font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--tjy-muted);margin-bottom:8px}.tjy-stat-row{display:flex;gap:26px;padding:13px 0 20px;border-top:1px solid var(--tjy-line);color:var(--tjy-muted);font-size:13px}.tjy-stat-row strong{color:var(--tjy-ink);font-size:15px;margin-right:3px}.tjy-week-scroll{overflow-x:auto;border:1px solid var(--tjy-line);border-radius:12px;background:#fff}.tjy-week-grid{display:grid;grid-template-columns:90px repeat(var(--day-count),minmax(180px,1fr));min-width:980px}.tjy-week-corner,.tjy-week-day-head,.tjy-week-label{background:var(--tjy-soft);border-right:1px solid var(--tjy-line);border-bottom:1px solid var(--tjy-line);padding:13px 14px}.tjy-week-day-head{display:flex;justify-content:space-between;gap:10px}.tjy-week-day-head span{color:var(--tjy-muted);font-size:12px}.tjy-week-label{font-size:12px;font-weight:600}.tjy-week-cell{min-height:104px;text-align:left;display:flex;flex-direction:column;gap:7px;border:0;border-right:1px solid var(--tjy-line);border-bottom:1px solid var(--tjy-line);background:#fff;padding:14px;cursor:pointer;color:var(--tjy-ink)}.tjy-week-cell:hover{background:#fafafa}.tjy-week-cell span{line-height:1.35}.tjy-cell-empty{color:#aaa}.tjy-source-details{margin-top:18px;border-top:1px solid var(--tjy-line);padding-top:15px;color:var(--tjy-muted)}.tjy-source-details summary{cursor:pointer;font-weight:600;color:var(--tjy-ink)}.tjy-source-grid{display:grid;grid-template-columns:110px 1fr;gap:9px 16px;margin-top:15px;max-width:760px}.tjy-source-grid strong{font-weight:500;color:var(--tjy-ink);overflow-wrap:anywhere}.tjy-day-tabs{display:flex;gap:4px;border-bottom:1px solid var(--tjy-line);overflow-x:auto}.tjy-day-tab{border:0;background:transparent;padding:12px 18px;color:var(--tjy-muted);border-bottom:2px solid transparent;min-width:110px}.tjy-day-tab strong,.tjy-day-tab span{display:block}.tjy-day-tab span{font-size:11px;margin-top:3px}.tjy-day-tab.active{color:var(--tjy-ink);border-bottom-color:var(--tjy-ink)}.tjy-workbench{display:grid;grid-template-columns:180px minmax(340px,1fr) minmax(340px,.9fr);min-height:560px;border:1px solid var(--tjy-line);border-top:0;border-radius:0 0 12px 12px;overflow:hidden}.tjy-meal-nav,.tjy-dish-pane,.tjy-ingredient-pane{padding:20px}.tjy-meal-nav,.tjy-dish-pane{border-right:1px solid var(--tjy-line)}.tjy-meal-item{width:100%;border:0;background:transparent;padding:11px 12px;border-radius:8px;display:flex;justify-content:space-between;margin-bottom:4px}.tjy-meal-item small{color:var(--tjy-muted)}.tjy-meal-item.active{background:var(--tjy-soft);font-weight:600}.tjy-pane-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:18px}.tjy-dish-row{display:grid;grid-template-columns:22px 1fr 30px;gap:7px;align-items:center;border:1px solid var(--tjy-line);border-radius:9px;padding:9px 10px;margin-bottom:8px}.tjy-dish-row.selected{border-color:#a8a8a4}.tjy-dish-row input,.tjy-ingredient-row input,.tjy-ingredient-row select{border:0;background:transparent;outline:0;width:100%;color:var(--tjy-ink)}.tjy-drag-handle{color:#aaa;cursor:grab}.tjy-icon-button{border:0;background:transparent;color:#aaa;font-size:18px}.tjy-ingredient-row{display:grid;grid-template-columns:minmax(110px,1fr) 80px 55px 26px;gap:7px;align-items:center;border-bottom:1px solid var(--tjy-line);padding:11px 0}.tjy-ingredient-row input:nth-child(2){text-align:right}.tjy-empty-panel{min-height:180px;border:1px dashed #d9d9d6;border-radius:10px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;color:var(--tjy-muted)}.tjy-empty-panel.compact{min-height:120px}.tjy-library-tools{display:flex;justify-content:space-between;align-items:center;padding:13px 0;color:var(--tjy-muted)}.tjy-search-wrap{display:flex;align-items:center;gap:8px;border:1px solid var(--tjy-line);border-radius:9px;padding:7px 10px;width:min(380px,70vw);background:#fff}.tjy-search-wrap input{border:0;outline:0;width:100%;background:transparent}.tjy-library-table-wrap{border:1px solid var(--tjy-line);border-radius:12px;overflow-x:auto;background:#fff}.tjy-library-table{width:100%;border-collapse:collapse;min-width:900px}.tjy-library-table th{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--tjy-muted);background:var(--tjy-soft);font-weight:600;text-align:left;padding:12px 14px}.tjy-library-table td{padding:14px;border-top:1px solid var(--tjy-line);vertical-align:middle}.tjy-library-table tbody tr{cursor:pointer}.tjy-library-table tbody tr:hover{background:#fafafa}.tjy-library-table td:first-child strong,.tjy-library-table td:first-child span{display:block}.tjy-library-table td:first-child span{color:var(--tjy-muted);font-size:11px;margin-top:4px}.tjy-status{display:inline-flex;padding:4px 8px;border-radius:999px;background:#f0f0ee;color:var(--tjy-muted);font-size:11px}.tjy-status.complete{background:#eaf5ef;color:#247249}.tjy-loading,.tjy-error-card{min-height:360px;display:flex;align-items:center;justify-content:center;gap:10px;color:var(--tjy-muted)}.tjy-error-card{flex-direction:column}.tjy-error-card strong{font-size:16px;color:var(--tjy-ink)}
.tjy-browse-head{display:flex;align-items:flex-start;justify-content:space-between;gap:28px;padding:2px 0 22px}.tjy-title-line{display:flex;align-items:center;gap:12px}.tjy-title-line h1{font-size:24px}.tjy-draft-pill{font-size:12px;color:var(--tjy-green);background:#e9f7ed;border-radius:7px;padding:5px 10px}.tjy-week-switcher{display:flex;align-items:center;gap:10px;margin-top:17px}.tjy-week-switcher>strong{font-size:15px;margin-left:4px}.tjy-square-button,.tjy-more-button,.tjy-back-button{display:inline-flex;align-items:center;justify-content:center;width:38px;height:38px;border:1px solid var(--tjy-line);border-radius:9px;background:#fff;color:var(--tjy-ink)}.tjy-switcher-divider{height:22px;border-left:1px solid var(--tjy-line);margin:0 5px}.tjy-outline-button,.tjy-primary-button{height:40px;border-radius:9px;padding:0 20px;display:inline-flex;align-items:center;justify-content:center;gap:8px;font-weight:600}.tjy-outline-button{background:#fff;border:1px solid var(--tjy-line);color:var(--tjy-ink)}.tjy-primary-button{background:#171717;border:1px solid #171717;color:#fff;min-width:105px}.tjy-outline-button.compact{height:34px;padding:0 13px;font-weight:500}.tjy-summary-card{display:grid;grid-template-columns:1.2fr repeat(3,1fr);border:1px solid var(--tjy-line);border-radius:11px;padding:22px 24px;margin-bottom:22px}.tjy-summary-item{display:flex;align-items:center;gap:15px;padding:0 28px;border-right:1px solid var(--tjy-line)}.tjy-summary-item:first-child{padding-left:12px}.tjy-summary-item:last-child{border-right:0}.tjy-summary-icon{font-size:22px;color:#4d4d4d;display:flex}.tjy-summary-item strong,.tjy-summary-item small{display:block}.tjy-summary-item strong{font-size:14px;font-weight:600}.tjy-summary-item small{color:var(--tjy-muted);margin-top:4px}.tjy-browse-layout{display:grid;grid-template-columns:minmax(780px,1fr) 330px;gap:20px;align-items:stretch}.tjy-week-scroll{border-radius:10px}.tjy-week-grid{grid-template-columns:88px repeat(var(--day-count),minmax(130px,1fr));min-width:850px}.tjy-week-corner,.tjy-week-day-head,.tjy-week-label{background:#fff}.tjy-week-label{display:flex;align-items:center;font-size:13px}.tjy-week-day-head{justify-content:center;align-items:center}.tjy-week-day-head strong{margin-right:7px}.tjy-week-cell{min-height:112px;font-size:13px}.tjy-week-cell.selected{background:#fafafa;box-shadow:inset 0 0 0 1px #bdbdb8;border-radius:8px}.tjy-browse-inspector{border:1px solid var(--tjy-line);border-radius:10px;background:#fff;overflow:hidden}.tjy-inspector-head{height:54px;padding:0 18px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--tjy-line)}.tjy-inspector-section{padding:17px 18px;border-bottom:1px solid var(--tjy-line)}.tjy-inspector-section h3{font-size:14px;margin:0 0 12px}.tjy-inspector-section h3 span{font-weight:400;color:var(--tjy-muted)}.tjy-dish-summary{padding-left:22px;margin:0}.tjy-dish-summary li{padding:4px 0}.tjy-inspector-table{font-size:12px}.tjy-inspector-tr{display:grid;grid-template-columns:1fr 75px 45px;padding:7px 0;border-bottom:1px solid #efefed}.tjy-inspector-tr span:nth-child(2),.tjy-inspector-tr span:nth-child(3){text-align:right}.tjy-inspector-tr.head{color:var(--tjy-muted)}.tjy-inspector-note{font-size:11px!important;line-height:1.5}.tjy-inspector-empty{color:var(--tjy-muted);font-size:13px;padding:14px 0}.tjy-inspector-edit{width:calc(100% - 36px);margin:14px 18px;height:36px;border:1px solid var(--tjy-line);border-radius:8px;background:#fff}
.tjy-editor-head{padding:0 0 16px;align-items:center}.tjy-editor-title-group{display:flex;align-items:center;gap:16px}.tjy-title-input{font-size:20px;width:min(650px,52vw)}.tjy-date-inputs{margin-top:4px;align-items:center}.tjy-date-inputs input{border:0;padding:0;margin:0;color:var(--tjy-muted);font-size:12px;width:115px}.tjy-save-state{display:flex;align-items:center;gap:7px;color:var(--tjy-muted);margin-right:14px}.tjy-save-state i{width:8px;height:8px;background:#2aa06a;border-radius:50%}.tjy-more-button{font-size:15px}.tjy-day-tabs{background:var(--tjy-soft);border:1px solid var(--tjy-line);border-radius:10px;padding:5px;justify-content:space-between}.tjy-day-tab{flex:1;border:0!important;border-radius:8px;min-width:120px}.tjy-day-tab.active{background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.07)}.tjy-workbench{grid-template-columns:160px minmax(360px,1.05fr) minmax(400px,1fr);min-height:660px;border:0;border-radius:0}.tjy-meal-nav,.tjy-dish-pane,.tjy-ingredient-pane{padding:28px 20px}.tjy-meal-nav,.tjy-dish-pane{border-right:1px solid var(--tjy-line)}.tjy-meal-item{padding:15px 18px;border-radius:0;border-left:2px solid transparent;font-size:15px}.tjy-meal-item.active{border-left-color:#171717;background:var(--tjy-soft)}.tjy-pane-head>div{display:flex;align-items:baseline;gap:14px}.tjy-pane-head h2{font-size:19px}.tjy-pane-count{color:var(--tjy-muted)}.tjy-dish-row{grid-template-columns:24px 28px 1fr 24px 24px;min-height:68px;padding:10px 14px;border-radius:8px}.tjy-dish-index{color:var(--tjy-muted)}.tjy-row-edit{color:var(--tjy-muted);display:flex}.tjy-selected-dish{display:flex;justify-content:space-between;align-items:center;margin:4px 0 17px}.tjy-selected-dish strong{font-size:16px}.tjy-selected-dish span{color:var(--tjy-muted)}.tjy-ingredient-labels{display:grid;grid-template-columns:minmax(110px,1fr) 90px 60px 30px;color:var(--tjy-muted);font-size:11px;padding:10px 0;border:1px solid var(--tjy-line);border-bottom:0;border-radius:8px 8px 0 0}.tjy-ingredient-labels span{padding-left:10px}.tjy-ingredient-row{grid-template-columns:minmax(110px,1fr) 90px 60px 30px;border:1px solid var(--tjy-line);border-bottom:0;padding:13px 6px}.tjy-ingredient-row:last-child{border-bottom:1px solid var(--tjy-line);border-radius:0 0 8px 8px}.tjy-nutrition{margin-top:30px}.tjy-nutrition h3{font-size:15px;margin-bottom:14px}.tjy-nutrition-grid{border:1px solid var(--tjy-line);border-radius:8px;display:grid;grid-template-columns:repeat(4,1fr)}.tjy-nutrition-grid>div{padding:14px;border-right:1px solid var(--tjy-line);border-bottom:1px solid var(--tjy-line)}.tjy-nutrition-grid>div:nth-child(4n){border-right:0}.tjy-nutrition-grid>div:nth-last-child(-n+4){border-bottom:0}.tjy-nutrition-grid span,.tjy-nutrition-grid strong{display:block}.tjy-nutrition-grid span{color:var(--tjy-muted);font-size:11px}.tjy-nutrition-grid strong{margin-top:7px;font-weight:500}.tjy-nutrition p{font-size:11px!important;margin-top:12px!important}
@media(max-width:1250px){.tjy-browse-layout{grid-template-columns:1fr}.tjy-browse-inspector{display:grid;grid-template-columns:220px 1fr}.tjy-inspector-head{grid-column:1/-1}.tjy-workbench{grid-template-columns:145px 1fr}.tjy-ingredient-pane{grid-column:1/-1;border-top:1px solid var(--tjy-line)}.tjy-dish-pane{border-right:0}.tjy-meal-nav{border-right:1px solid var(--tjy-line)}}
@media(max-width:760px){.tjy-recipe-app{padding:14px 10px 42px}.tjy-browse-head,.tjy-editor-head,.tjy-library-head{display:block}.tjy-hero-actions{margin-top:16px;flex-wrap:wrap}.tjy-summary-card{grid-template-columns:1fr 1fr;padding:10px}.tjy-summary-item{padding:12px!important;border:0}.tjy-browse-inspector{display:block}.tjy-editor-title-group{align-items:flex-start}.tjy-title-input{width:calc(100vw - 120px);font-size:17px}.tjy-save-state{display:none}.tjy-workbench{display:block}.tjy-meal-nav,.tjy-dish-pane{border-right:0;border-bottom:1px solid var(--tjy-line)}.tjy-meal-nav{display:grid;grid-template-columns:repeat(3,1fr);gap:4px}.tjy-meal-nav .tjy-pane-label{grid-column:1/-1}.tjy-source-grid{grid-template-columns:1fr}.tjy-ingredient-row,.tjy-ingredient-labels{grid-template-columns:1fr 70px 50px 24px}}
`;
