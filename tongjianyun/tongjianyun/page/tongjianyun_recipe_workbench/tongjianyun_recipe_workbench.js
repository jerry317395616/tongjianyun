frappe.pages["tongjianyun-recipe-workbench"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "食谱",
        single_column: true,
    });
    wrapper.tongjianyun_recipe_page = new TongjianyunRecipePage(page, wrapper);
    bindRecipeLibrarySidebarLink(wrapper.tongjianyun_recipe_page);
};

frappe.pages["tongjianyun-recipe-workbench"].on_page_show = function (wrapper) {
    const controller = wrapper.tongjianyun_recipe_page;
    if (controller && controller.state.screen !== "library" && !frappe.route_options?.recipe) {
        controller.showLibrary();
    }
};

function bindRecipeLibrarySidebarLink(controller) {
    if (window.tongjianyunRecipeLibraryClickHandler) {
        document.removeEventListener("click", window.tongjianyunRecipeLibraryClickHandler, true);
    }

    window.tongjianyunRecipeLibraryClickHandler = (event) => {
        const link = event.target.closest('a[href="/desk/tongjianyun-recipe-workbench"]');
        if (!link) return;

        const currentPath = window.location.pathname.replace(/\/$/, "");
        if (currentPath !== "/desk/tongjianyun-recipe-workbench") return;

        event.preventDefault();
        event.stopPropagation();
        frappe.route_options = null;
        controller.showLibrary();
    };

    document.addEventListener("click", window.tongjianyunRecipeLibraryClickHandler, true);
}

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
            selectedLibraryRecipes: new Set(),
            librarySearch: "",
            libraryStatus: "全部",
            recycleBin: false,
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
        this.clearPagePrimaryAction();
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
        const payload = this.state.payload || normalizePayload({});
        const recipe = payload.recipe;
        this.page.set_title(`Tongjianyun Recipe / ${recipe.title || "未命名食谱"}`);
        this.clearPagePrimaryAction();
        const days = payload.days;
        const summary = getSummary(payload);
        const selection = this.getBrowseSelection(days);
        const selectedDay = days[selection.dayIndex];
        const selectedPortion = findPortion(selectedDay, selection.slot);
        const mealRows = MEAL_SLOTS.map((slot) => `
            <div class="tjy-week-label tjy-week-label-${slot}">${MEAL_LABELS[slot]}</div>
            ${days.map((day, dayIndex) => this.renderBrowseCell(day, dayIndex, slot)).join("")}
        `).join("");

        this.main.html(`
            <section class="tjy-screen tjy-browse-screen">
                <header class="tjy-browse-head">
                    <div>
                        <div class="tjy-title-line">
                            <button class="tjy-back-button" data-action="library" aria-label="返回食谱计划">←</button>
                            <h1>${escapeHtml(getWeekTitle(recipe))}</h1>
                            <span class="tjy-draft-pill tjy-status ${recipeStatusClass(recipe.workflowStatus)}">${escapeHtml(recipe.workflowStatus || "草稿")}</span>
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
                        ${recipe.workflowStatus === "已发布" ? '<button class="tjy-outline-button" data-action="erp-procurement">准备 ERP 采购需求</button>' : ''}
                        <button class="tjy-outline-button" data-action="item-sync">食材物料匹配结果</button>
                        <button class="tjy-outline-button" data-action="import">${frappe.utils.icon("upload", "sm")}<span>导入食谱</span></button>
                        <button class="tjy-primary-button" data-action="edit">${["已发布", "已归档"].includes(recipe.workflowStatus) ? "创建修订版" : "编辑食谱"}</button>
                    </div>
                </header>
                <div class="tjy-browse-layout">
                    <div class="tjy-browse-main">
                        <div class="tjy-summary-card">
                            <div class="tjy-summary-item"><span class="tjy-summary-icon">${summaryIcon("calendar")}</span><div><strong>${formatFriendlyRange(recipe.weekStart, recipe.weekEnd)}</strong><small>${escapeHtml(getRecipeYear(recipe))} · ${escapeHtml(getWeekLabel(recipe))}</small></div></div>
                            <div class="tjy-summary-item"><span class="tjy-summary-icon">${summaryIcon("days")}</span><div><strong>${days.length} 天</strong><small>覆盖天数</small></div></div>
                            <div class="tjy-summary-item"><span class="tjy-summary-icon">${summaryIcon("meals")}</span><div><strong>${days.length * MEAL_SLOTS.length} 餐次</strong><small>每日 ${MEAL_SLOTS.length} 餐</small></div></div>
                            <div class="tjy-summary-item"><span class="tjy-summary-icon">${summaryIcon("dishes")}</span><div><strong>${summary.dishes} 道菜</strong><small>本周总计</small></div></div>
                        </div>
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
                    </div>
                    ${this.renderBrowseInspector(selectedDay, selectedPortion, selection)}
                </div>
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
            <button class="tjy-week-cell tjy-week-cell-${slot} ${dishes.length ? "has-content" : ""} ${this.isBrowseCellSelected(dayIndex, slot) ? "selected" : ""}" data-cell data-day="${dayIndex}" data-slot="${slot}">
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
                    <button class="tjy-inspector-close" type="button" aria-label="关闭详情">×</button>
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
            </aside>
        `;
    }

    enterEdit() {
        if (!this.state.payload) return;
        this.state.screen = "edit";
        this.page.set_title(`Tongjianyun Recipe / ${this.state.payload.recipe.title || "未命名食谱"}`);
        this.clearPagePrimaryAction();
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
                        <h1 class="tjy-editor-week-title">${escapeHtml(getWeekTitle(payload.recipe))}</h1>
                        <input type="hidden" value="${escapeAttr(payload.recipe.title || "未命名食谱")}" data-recipe-title>
                        <div class="tjy-date-inputs">
                            <span>${formatEditorRange(payload.recipe.weekStart, payload.recipe.weekEnd)}</span>
                            <input type="hidden" value="${escapeAttr(payload.recipe.weekStart || "")}" data-week-start>
                            <input type="hidden" value="${escapeAttr(payload.recipe.weekEnd || "")}" data-week-end>
                        </div>
                    </div>
                    <div class="tjy-hero-actions">
                        <select class="tjy-status-select" data-workflow-status aria-label="食谱状态">
                            ${["草稿", "待审核", "已发布", "已归档"].map((status) => `<option ${status === (payload.recipe.workflowStatus || "草稿") ? "selected" : ""}>${status}</option>`).join("")}
                        </select>
                        <span class="tjy-save-state"><i></i> 已自动保存&nbsp; ${formatCurrentTime()}</span>
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
                                <span class="tjy-meal-icon">${mealIcon(slot)}</span>
                                <span>${MEAL_LABELS[slot]}</span>
                            </button>
                        `).join("")}
                    </aside>
                    <main class="tjy-dish-pane">
                        <div class="tjy-pane-head">
                            <div><h2>${MEAL_LABELS[this.state.activeSlot]}</h2><span class="tjy-pane-count">${portion.dishes.length} 道菜品</span></div>
                            <button class="tjy-outline-button compact" data-action="add-dish">＋ 添加菜品</button>
                        </div>
                        <div class="tjy-dish-list">
                            <div class="tjy-dish-labels"><span>菜品</span><span>操作</span></div>
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
                        ${selectedDish ? `<div class="tjy-selected-dish"><strong>${escapeHtml(selectedDish)}</strong><span>${renderDishPortion(relevantIngredients)}</span></div><div class="tjy-ingredient-table"><div class="tjy-ingredient-labels"><span>食材</span><span>每人用量</span><span>单位</span><span>操作</span></div>` : ""}
                        <div class="tjy-ingredient-editor">
                            ${selectedDish
                                ? relevantIngredients.map((row, index) => this.renderIngredientRow(row, index)).join("") || '<div class="tjy-empty-panel compact"><span>暂未录入食材</span></div>'
                                : '<div class="tjy-empty-panel compact"><span>先添加一个菜品</span></div>'}
                        </div>
                        ${selectedDish ? "</div>" : ""}
                        ${selectedDish ? '<button class="tjy-outline-button tjy-add-ingredient-secondary" data-action="add-ingredient">＋ 添加食材</button>' : ""}
                        ${selectedDish ? renderNutritionEstimate(relevantIngredients) : ""}
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
                <button class="tjy-row-edit" data-edit-dish="${index}" type="button" title="编辑">${editorActionIcon("edit")}</button>
                <button class="tjy-icon-button" data-remove-dish="${index}" type="button" title="删除">${editorActionIcon("delete")}</button>
            </div>
        `;
    }

    renderIngredientRow(row, index) {
        return `
            <div class="tjy-ingredient-row">
                <input type="text" value="${escapeAttr(row.ingredient || "")}" data-ingredient-name="${index}" placeholder="食材">
                <input type="number" min="0" step="0.1" value="${escapeAttr(row.amount ?? row.gramsPerChild ?? 0)}" data-ingredient-amount="${index}" aria-label="每人克重">
                <select data-ingredient-unit="${index}">
                    ${["g", "kg", "mg", "ml"].map((unit) => `<option ${unit === (row.unit || "g") ? "selected" : ""}>${unit}</option>`).join("")}
                </select>
                <button class="tjy-icon-button" data-remove-ingredient="${index}" type="button" title="删除">${editorActionIcon("delete")}</button>
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
        this.main.find("[data-edit-dish]").on("click", (event) => {
            event.stopPropagation();
            const index = Number($(event.currentTarget).attr("data-edit-dish"));
            this.main.find(`[data-dish-input="${index}"]`).trigger("focus").select();
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
        const workflowStatus = this.main.find("[data-workflow-status]").val();
        if (workflowStatus !== undefined) this.state.payload.recipe.workflowStatus = workflowStatus || "草稿";
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
            const sync = response.message?.erp_sync;
            if (sync?.recipe) this.state.selectedRecipe = sync.recipe;
            frappe.show_alert({ message: sync?.message || "食谱已保存", indicator: sync?.status === "blocked" ? "orange" : "green" });
            this.showBrowse();
            if (sync?.recipe && sync.status !== "blocked") {
                frappe.show_alert({message: "后台正在处理食材；汤粥等项目可点击“食材用途确认”集中处理。", indicator: "blue"}, 10);
            }
        } catch (error) {
            this.showError("食谱保存失败", error);
        } finally {
            button.prop("disabled", false).text("保存食谱");
        }
    }

    async showLibrary() {
        this.state.screen = "library";
        this.page.set_title("食谱计划");
        this.clearPagePrimaryAction();
        this.showLoading("正在加载食谱库...");
        try {
            const response = await frappe.call({
                method: "tongjianyun.recipe_storage.get_recipe_library",
                args: {
                    search: this.state.librarySearch,
                    status: this.state.libraryStatus,
                    recycle_bin: this.state.recycleBin ? 1 : 0,
                    page_length: 100,
                },
            });
            this.state.library = response.message?.items || [];
            const visibleNames = new Set(this.state.library.map((item) => item.name));
            this.state.selectedLibraryRecipes = new Set(
                [...this.state.selectedLibraryRecipes].filter((name) => visibleNames.has(name)),
            );
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
                    <div><div class="tjy-eyebrow">童健云</div><h1>食谱计划</h1><p>创建、审核和管理每周食谱</p></div>
                    <div class="tjy-create-wrap">
                        <button class="tjy-outline-button" data-action="nutrition-report">${frappe.utils.icon("chart", "sm")}<span>营养分析报表</span></button>
                        <button class="tjy-outline-button" data-action="import">${frappe.utils.icon("upload", "sm")}<span>导入文件</span></button>
                        <button class="tjy-outline-button" data-action="copy-latest">${frappe.utils.icon("duplicate", "sm")}<span>复制上一周</span></button>
                        <button class="tjy-primary-button" data-action="new">＋ 空白新建</button>
                    </div>
                </header>
                <div class="tjy-library-tools">
                    <div class="tjy-search-wrap">${frappe.utils.icon("search", "sm")}<input type="search" value="${escapeAttr(this.state.librarySearch)}" placeholder="搜索食谱名称或周次"></div>
                    <div class="tjy-library-filters">
                        <div class="tjy-status-tabs">
                            ${["全部", "草稿", "待审核", "已发布", "已归档", "回收站"].map((status) => `<button class="${this.state.libraryStatus === status ? "active" : ""}" data-library-status="${status}">${status}</button>`).join("")}
                        </div>
                        ${!this.state.recycleBin ? `<button class="tjy-bulk-delete" data-action="bulk-delete" ${this.state.selectedLibraryRecipes.size ? "" : "disabled"}>删除选中（${this.state.selectedLibraryRecipes.size}）</button>` : ""}
                        <span>${items.length} 份食谱</span>
                    </div>
                </div>
                <div class="tjy-library-table-wrap">
                    <table class="tjy-library-table">
                        <thead><tr><th class="tjy-select-cell"><input type="checkbox" data-select-all aria-label="全选可删除食谱"></th><th>食谱</th><th>日期范围</th><th>状态</th><th>菜品</th><th>食材明细</th><th>最后更新</th><th></th></tr></thead>
                        <tbody>
                            ${items.length ? items.map((item) => `
                                <tr data-library-recipe="${escapeAttr(item.name)}">
                                    <td class="tjy-select-cell"><input type="checkbox" data-select-recipe="${escapeAttr(item.name)}" ${this.state.selectedLibraryRecipes.has(item.name) ? "checked" : ""} ${item.actions?.can_delete ? "" : "disabled"} aria-label="选择${escapeAttr(item.title || item.name)}"></td>
                                    <td><strong>${escapeHtml(item.title || "未命名食谱")}</strong><span>${escapeHtml(item.recipe_id || "")}</span></td>
                                    <td>${formatDateRange(item.week_start, item.week_end)}</td>
                                    <td><span class="tjy-status ${item.status}">${escapeHtml(item.display_status || item.workflow_status || "草稿")}</span></td>
                                    <td>${item.dish_count || 0}</td>
                                    <td>${item.ingredient_count || 0}</td>
                                    <td>${frappe.datetime.prettyDate(item.modified)}</td>
                                    <td class="tjy-row-actions">
                                        <button class="tjy-row-open" data-row-action="open">打开 →</button>
                                        ${item.actions?.can_delete ? '<button class="tjy-row-delete" data-recipe-action="delete">删除</button>' : ''}
                                        <div class="tjy-action-menu-wrap">
                                            <button class="tjy-row-more" data-row-action="menu" aria-label="更多操作">···</button>
                                            <div class="tjy-action-menu">
                                                ${renderRecipeActions(item, { includeDelete: false })}
                                            </div>
                                        </div>
                                    </td>
                                </tr>
                            `).join("") : '<tr><td colspan="8"><div class="tjy-empty-panel"><strong>暂无匹配的食谱</strong><span>请调整搜索或状态筛选，也可新建、导入食谱</span></div></td></tr>'}
                        </tbody>
                    </table>
                </div>
            </section>
        `);
        this.main.find('[data-action="new"]').on("click", () => this.createRecipe());
        this.main.find('[data-action="nutrition-report"]').on("click", () => this.openNutritionReport());
        this.main.find('[data-action="import"]').on("click", () => this.openImport());
        this.main.find('[data-action="copy-latest"]').on("click", () => this.copyLatestRecipe());
        this.main.find('[data-action="bulk-delete"]').on("click", () => this.bulkDeleteRecipes());
        this.main.find("[data-library-recipe]").on("click", (event) => {
            if ($(event.target).closest("[data-row-action],[data-recipe-action]").length) return;
            this.loadRecipe($(event.currentTarget).attr("data-library-recipe"));
        });
        this.main.find('[data-row-action="open"]').on("click", (event) => {
            event.stopPropagation();
            this.loadRecipe($(event.currentTarget).closest("tr").attr("data-library-recipe"));
        });
        this.main.find('[data-row-action="menu"]').on("click", (event) => {
            event.stopPropagation();
            const menu = $(event.currentTarget).siblings(".tjy-action-menu");
            this.main.find(".tjy-action-menu.open").not(menu).removeClass("open");
            menu.toggleClass("open");
        });
        this.main.find("[data-recipe-action]").on("click", (event) => {
            event.stopPropagation();
            const button = $(event.currentTarget);
            this.handleRecipeAction(button.closest("tr").attr("data-library-recipe"), button.attr("data-recipe-action"));
        });
        this.main.find("[data-select-recipe]").on("click", (event) => event.stopPropagation());
        this.main.find("[data-select-recipe]").on("change", (event) => {
            const name = $(event.currentTarget).attr("data-select-recipe");
            if ($(event.currentTarget).is(":checked")) this.state.selectedLibraryRecipes.add(name);
            else this.state.selectedLibraryRecipes.delete(name);
            this.renderLibrary();
        });
        const selectable = this.main.find("[data-select-recipe]:not(:disabled)");
        const selectedVisible = selectable.filter(":checked").length;
        this.main.find("[data-select-all]").prop("disabled", !selectable.length).prop("checked", Boolean(selectable.length) && selectedVisible === selectable.length);
        this.main.find("[data-select-all]").on("change", (event) => {
            const checked = $(event.currentTarget).is(":checked");
            this.main.find("[data-select-recipe]:not(:disabled)").each((_, input) => {
                const name = $(input).attr("data-select-recipe");
                if (checked) this.state.selectedLibraryRecipes.add(name);
                else this.state.selectedLibraryRecipes.delete(name);
            });
            this.renderLibrary();
        });
        let timer;
        this.main.find('input[type="search"]').on("input", (event) => {
            clearTimeout(timer);
            timer = setTimeout(() => {
                this.state.librarySearch = String($(event.currentTarget).val() || "").trim();
                this.showLibrary();
            }, 300);
        });
        this.main.find("[data-library-status]").on("click", (event) => {
            this.state.libraryStatus = $(event.currentTarget).attr("data-library-status");
            this.state.recycleBin = this.state.libraryStatus === "回收站";
            this.showLibrary();
        });
    }

    openNutritionReport() {
        const recipe = this.state.selectedRecipe || this.state.library?.[0]?.name;
        frappe.route_options = recipe ? { recipe } : null;
        frappe.set_route("weekly-recipe-nutrition-sheet");
    }

    async handleRecipeAction(recipe, action) {
        if (action === "copy") {
            await this.loadRecipe(recipe);
            const payload = normalizePayload(this.state.payload);
            payload.recipe.recipeId = `RECIPE-${Date.now()}`;
            payload.recipe.title = `${payload.recipe.title || "周食谱"}（副本）`;
            payload.recipe.workflowStatus = "草稿";
            this.state.payload = payload;
            this.state.selectedRecipe = null;
            this.enterEdit();
            return;
        }
        const labels = { withdraw: "撤回为草稿", archive: "归档", delete: "移入回收站", restore: "恢复" };
        frappe.confirm(`确认${labels[action] || action}这份食谱吗？`, async () => {
            try {
                const response = await frappe.call({
                    method: "tongjianyun.recipe_storage.update_recipe_lifecycle",
                    args: { recipe, action },
                    freeze: true,
                });
                frappe.show_alert({ message: response.message?.message || "操作成功", indicator: "green" });
                await this.showLibrary();
            } catch (error) {
                this.showError("食谱操作失败", error);
            }
        });
    }

    bulkDeleteRecipes() {
        const selected = [...this.state.selectedLibraryRecipes];
        if (!selected.length) return;
        frappe.confirm(`确认将选中的 ${selected.length} 份食谱移入回收站吗？`, async () => {
            try {
                const response = await frappe.call({
                    method: "tongjianyun.recipe_storage.bulk_delete_recipes",
                    args: { recipes: selected },
                    freeze: true,
                    freeze_message: "正在删除选中的食谱...",
                });
                const result = response.message || {};
                this.state.selectedLibraryRecipes.clear();
                const blocked = result.blocked || [];
                if (blocked.length) {
                    frappe.msgprint({
                        title: "批量删除完成",
                        indicator: "orange",
                        message: `已移入回收站 ${result.moved || 0} 份；未删除 ${blocked.length} 份。<br>${blocked.map((row) => `${escapeHtml(row.name)}：${escapeHtml(row.reason)}`).join("<br>")}`,
                    });
                } else {
                    frappe.show_alert({ message: `已删除 ${result.moved || 0} 份食谱`, indicator: "green" });
                }
                await this.showLibrary();
            } catch (error) {
                this.showError("批量删除失败", error);
            }
        });
    }

    async copyLatestRecipe() {
        const source = this.state.library[0];
        if (!source) {
            frappe.msgprint("暂无可复制的食谱。");
            return;
        }
        await this.loadRecipe(source.name);
        const payload = normalizePayload(this.state.payload);
        const start = frappe.datetime.add_days(payload.recipe.weekStart || frappe.datetime.get_today(), 7);
        payload.recipe.recipeId = `RECIPE-${String(start).replaceAll("-", "")}-${Date.now().toString().slice(-6)}`;
        payload.recipe.title = `${getWeekTitle(payload.recipe)}（副本）`;
        payload.recipe.weekStart = start;
        payload.recipe.weekEnd = frappe.datetime.add_days(payload.recipe.weekEnd || start, 7);
        payload.recipe.workflowStatus = "草稿";
        payload.days.forEach((day) => { day.date = frappe.datetime.add_days(day.date, 7); });
        this.state.payload = payload;
        this.state.selectedRecipe = null;
        this.enterEdit();
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
                workflowStatus: "草稿",
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
        const syncButton = this.main.find('[data-action="item-sync"]');
        if (syncButton.length && !this.main.find('[data-action="product-decisions"]').length) {
            syncButton.after('<button class="tjy-outline-button" data-action="product-decisions">食材用途确认</button>');
        }
        this.main.find('[data-action="product-decisions"]').on("click", () => this.showProductDecisions());
        this.main.find('[data-action="item-sync"]').on("click", () => this.showItemSync());
        this.main.find('[data-action="erp-procurement"]').on("click", () => this.openProcurement());
        this.main.find('[data-action="library"]').on("click", () => this.showLibrary());
        this.main.find('[data-action="edit"]').on("click", () => this.editRecipe());
        this.main.find('[data-action="browse"]').on("click", () => this.showBrowse());
        this.main.find('[data-action="save"]').on("click", () => this.saveRecipe());
        this.main.find('[data-action="import"]').on("click", () => this.openImport());
        this.main.find('[data-action="calendar"]').on("click", () => this.enterEdit());
        this.main.find('[data-action="previous"]').on("click", () => this.openAdjacentRecipe(-1));
        this.main.find('[data-action="next"]').on("click", () => this.openAdjacentRecipe(1));
    }

    async showProductDecisions() {
        const recipe = this.state.selectedRecipe || this.state.payload?.recipe?.recipeId;
        if (!recipe) return;
        const response = await frappe.call({method: "tongjianyun.recipe_product_decisions.get_pending", args: {recipe}});
        const pending = response.message;
        if (!pending?.rows?.length) return frappe.msgprint("没有需要确认用途的食材。");
        const dialog = new frappe.ui.Dialog({title: "食材用途确认", size: "extra-large", fields: [
            {fieldtype: "HTML", options: "<p>不影响食谱保存。外购可选择已有物料；新建时填写分类和库存单位。自制项目保存为配方待办，暂不自动展开；暂时跳过仍会阻止完整采购。空白行不修改。</p>"},
            {fieldtype: "Table", fieldname: "decisions", cannot_add_rows: true, cannot_delete_rows: true,
                data: pending.rows.map(row => ({key: row.key, ingredient: row.ingredient, source_unit: row.unit,
                    mode: row.decision?.mode || "", item_code: row.decision?.item_code || ""})),
                fields: [
                    {fieldtype: "Data", fieldname: "key", hidden: 1},
                    {fieldtype: "Data", fieldname: "ingredient", label: "食材", read_only: 1, in_list_view: 1},
                    {fieldtype: "Data", fieldname: "source_unit", label: "原单位", read_only: 1},
                    {fieldtype: "Select", fieldname: "mode", label: "处理方式", options: "\n外购\n自制\n暂时跳过", in_list_view: 1},
                    {fieldtype: "Link", fieldname: "item_code", label: "已有外购物料", options: "Item", in_list_view: 1},
                    {fieldtype: "Link", fieldname: "item_group", label: "新建时的分类", options: "Item Group", in_list_view: 1},
                    {fieldtype: "Link", fieldname: "uom", label: "新建时的库存单位", options: "UOM", in_list_view: 1}
                ]}
        ], primary_action_label: "确认并继续处理", primary_action: async values => {
            const decisions = (values.decisions || []).filter(row => row.mode);
            if (!decisions.length) return frappe.msgprint("请至少选择一项处理方式。");
            await frappe.call({method: "tongjianyun.recipe_product_decisions.confirm",
                args: {recipe, revision: pending.revision, decisions}, freeze: true});
            dialog.hide();
            frappe.show_alert({message: "确认已保存，后台将继续匹配；自制及跳过项目保留待办。", indicator: "green"});
            await this.showItemSync();
        }});
        dialog.show();
    }

    async showItemSync() {
        const recipe = this.state.selectedRecipe || this.state.payload?.recipe?.recipeId;
        if (!recipe) return;
        const dialog = new frappe.ui.Dialog({ title: "食材物料匹配结果", fields: [{ fieldtype: "HTML", fieldname: "result" }],
            primary_action_label: "刷新状态", primary_action: () => refresh() });
        let timer = null;
        let closed = false;
        let loading = false;
        dialog.$wrapper.on("hidden.bs.modal", () => {
            closed = true;
            clearTimeout(timer);
        });
        const refresh = async () => {
            if (closed || loading) return;
            clearTimeout(timer);
            loading = true;
            try {
                const response = await frappe.call({ method: "tongjianyun.recipe_item_sync.get_sync_status", args: { recipe } });
                if (closed) return;
                const data = response.message || {};
                const labels = { queued: "已排队", running: "处理中", completed: "匹配完成", partial: "部分完成，需核对", failed: "同步失败", needs_review: "待核对，尚未匹配", stale: "食材已变化", not_started: "尚未开始" };
                dialog.fields_dict.result.$wrapper.html(`<p>${escapeHtml(labels[data.status] || data.status || "")}</p>
                    <p>${escapeHtml(data.message || "")}</p>
                    ${(data.classification_errors || []).map(error => `<p>第 ${Number(error.batch)} 批：${escapeHtml(({service_unavailable: "模型服务调用失败", invalid_classification: "分类结果校验失败", unexpected_error: "分类处理异常"})[error.code] || "分类失败")}，已尝试 ${Number(error.attempts)} 次；其他成功批次不受影响。</p>`).join("")}
                    <p>已匹配 ${Object.keys(data.mappings || {}).length} 项；本次新建物料 ${(data.created_items || []).length} 个；新建分类 ${(data.created_groups || []).length} 个。</p>
                    ${(data.unresolved || []).map(row => `<p><strong>${escapeHtml(row.ingredient)}</strong>：${escapeHtml(row.reason)}</p>`).join("")}
                    <p class="text-muted">采购数量与毛料换算系数仍需在 ERP 采购预览中核对。失败或待处理项目可在核对后重新保存食谱重试。</p>`);
                if (["queued", "running"].includes(data.status)) {
                    dialog.fields_dict.result.$wrapper.append('<p class="text-muted" role="status">后台正在处理，此窗口每 5 秒自动更新；关闭窗口不影响后台任务。</p>');
                    timer = setTimeout(refresh, 5000);
                }
            } catch (error) {
                if (!closed) dialog.fields_dict.result.$wrapper.text("无法读取匹配结果，请检查账号权限或网络后点击刷新状态。");
            } finally {
                loading = false;
            }
        };
        dialog.fields_dict.result.$wrapper.text("正在读取状态...");
        dialog.show();
        await refresh();
    }

    procurementDayRows(meals) {
        const days = {};
        for (const meal of meals) {
            const row = days[meal.date] ||= {date: meal.date};
            row[meal.slot] = meal.count == null ? "" : String(meal.count);
        }
        return Object.values(days).sort((a, b) => a.date.localeCompare(b.date));
    }

    procurementMealCounts(meals, days) {
        const byDate = Object.fromEntries(days.map(row => [row.date, row]));
        return Object.fromEntries(meals.map(meal => [meal.key, byDate[meal.date]?.[meal.slot] ?? ""]));
    }

    fillProcurementCounts(meals, days, count, includeHistory, today) {
        const existing = new Set(meals.map(row => row.date + ":" + row.slot));
        for (const row of days) {
            if (!includeHistory && row.date < today) continue;
            for (const slot of Object.keys(MEAL_LABELS)) {
                if (existing.has(row.date + ":" + slot) && (row[slot] == null || row[slot] === "")) row[slot] = String(count);
            }
        }
    }

    async openProcurement() {
        const recipe = this.state.selectedRecipe;
        if (!recipe) return;
        try {
            const response = await frappe.call({method: "tongjianyun.recipe_procurement.revision_impact", args: {recipe}});
            const impact = response.message || {};
            if (impact.requests?.length) {
                frappe.msgprint({title: "已有采购需求，请先核对", message:
                    `<p>${escapeHtml(impact.message || "")}</p>` + impact.requests.map(row =>
                        `<p><a href="/desk/material-request/${encodeURIComponent(row.name)}">${escapeHtml(row.name)}</a>：${row.changed ? "食谱已变更，原单需核对" : "食谱内容与生成时一致"}（${({0:"草稿",1:"已提交",2:"已取消"})[row.docstatus] || "请查看原单"}）</p>`).join("")});
                return;
            }
        } catch (error) {
            frappe.msgprint("无法核对已有采购需求，请检查权限后重试；本次未生成采购单。");
            return;
        }
        const call = async (method, args) => (await frappe.call({
            method: `tongjianyun.recipe_procurement.${method}`, args, freeze: true,
        })).message;
        try {
                const scope = await call("default_scope", {recipe});
                let prepared = await call("prepare", {recipe, company: scope.company});
                if (prepared.ingredients.some(row => !row.item_code)) {
                    prepared = await this.autoMatchProcurementItems(recipe, scope.company);
                    if (!prepared) return;
                }
                const dialog = new frappe.ui.Dialog({
                    title: "准备采购 · 确认人数", size: "large",
                    fields: [
                        {fieldtype: "HTML", options: prepared.ingredients.filter(row => !row.item_code || !(Number(row.factor) > 0)).map(row =>
                            `<p class="text-danger">${escapeHtml(row.ingredient)}：${!row.item_code ? escapeHtml(row.basis || "自动匹配尚未完成，请重试或联系管理员。") : `食谱单位 ${escapeHtml(row.source_uom)}，库存单位 ${escapeHtml(row.uom)}，缺少换算关系。请确认自制/外购及每份含量，无需反复修改人数。`}</p>`).join("")},
                        {fieldtype: "HTML", options: `<p>公司、仓库已自动设置，请确认下面的备餐人数。</p><p>${prepared.ingredients.some(row => !row.item_code || !(Number(row.factor) > 0)) ? "部分食材仍有异常，原因可在下方食材明细查看；可重试自动处理或联系管理员。" : "食材已匹配，无需手工建档。"}</p><p class="text-muted">${escapeHtml(scope.company)} · ${escapeHtml(scope.warehouse)}；仅生成草稿，不自动采购或扣库存。</p>`},
                        {fieldname: "include_history", label: "包含过去日期（历史补录）", fieldtype: "Check", default: 0,
                            description: "默认只生成今天及之后的需求，过去日期的食材和人数不参与计算。勾选后包含过去日期；历史需求不代表已采购、已入库或已付款。"},
                        {fieldname: "bulk_count", label: "统一备餐人数（各餐相同时填写）", fieldtype: "Data",
                            description: "只补充未填写的人数，不覆盖已有数据；0 人会保留。"},
                        {fieldname: "fill_counts", label: "填入空白人数", fieldtype: "Button", click: () => {
                            const value = String(dialog.get_value("bulk_count") ?? "").trim();
                            if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value))) {
                                frappe.msgprint("请填写 0 或正整数人数。"); return;
                            }
                            this.fillProcurementCounts(prepared.meals, dialog.fields_dict.meal_days.df.data,
                                value, dialog.get_value("include_history"), prepared.as_of_date);
                            dialog.fields_dict.meal_days.grid.refresh();
                        }},
                        {fieldname: "meal_days", label: "每天备餐人数", fieldtype: "Table", cannot_add_rows: true, cannot_delete_rows: true,
                            description: "已有就餐确认人数已带出，请核对适用范围。空白需填写；食谱没有安排的餐次不参与采购。过去日期默认不参与。",
                            data: this.procurementDayRows(prepared.meals), fields: [
                                {fieldname: "date", label: "日期", fieldtype: "Date", read_only: 1, in_list_view: 1, columns: 2},
                                ...Object.entries(MEAL_LABELS).filter(([slot]) => prepared.meals.some(meal => meal.slot === slot)).map(([slot, label]) =>
                                    ({fieldname: slot, label, fieldtype: "Data", in_list_view: 1, columns: 1})),
                            ]},
                        {fieldtype: "HTML", options: "<p>点击下一步查看采购清单，最后确认后才生成草稿。</p>"},
                        {fieldtype: "Section Break", label: "食材明细与高级设置（通常无需操作）", collapsible: 1},
                        {fieldtype: "HTML", options: "<p>缺少的食材物料由系统自动分类建档，无需手工新建。请核对备餐人数及毛料换算系数；异常原因显示在来源栏，可重试自动处理。换算系数＝每 1 个食谱单位所需的采购毛料库存单位数量；净料需另计可食率。更换物料后请点击“更新库存单位”。</p>"},
                        {fieldname: "batch_resolve", label: "重试自动匹配建档", fieldtype: "Button", click: async () => {
                            const updated = await this.autoMatchProcurementItems(recipe, scope.company);
                            if (!updated) return;
                            const byKey = Object.fromEntries(updated.ingredients.map(row => [row.key, row]));
                            for (const row of dialog.fields_dict.ingredients.df.data) {
                                if (!row.item_code && byKey[row.key]) Object.assign(row, byKey[row.key]);
                            }
                            dialog.fields_dict.ingredients.grid.refresh();
                        }},
                        {fieldname: "ingredients", label: "食材匹配（同名仅为候选）", fieldtype: "Table", cannot_add_rows: true, cannot_delete_rows: true,
                            data: prepared.ingredients, fields: [
                                {fieldname: "key", fieldtype: "Data", hidden: 1},
                                {fieldname: "ingredient", label: "食谱食材", fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 2},
                                {fieldname: "source_uom", label: "食谱单位", fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 1},
                                {fieldname: "item_code", label: "物料", fieldtype: "Link", options: "Item", in_list_view: 1, columns: 3,
                                    get_query: () => ({filters: {disabled: 0, is_purchase_item: 1, is_stock_item: 1, has_variants: 0}})},
                                {fieldname: "uom", label: "库存单位", fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 1},
                                {fieldname: "factor", label: "毛料换算系数", fieldtype: "Float", in_list_view: 1, columns: 2},
                                {fieldname: "basis", label: "来源", fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 1},
                            ]},
                        {fieldname: "refresh_units", label: "更新库存单位", fieldtype: "Button", click: async () => {
                            for (const row of dialog.fields_dict.ingredients.df.data) {
                                if (!row.item_code) continue;
                                const response = await frappe.db.get_value("Item", row.item_code, "stock_uom");
                                const unit = response.message.stock_uom;
                                if (unit !== row.uom) { row.uom = unit; row.factor = null; }
                            }
                            dialog.fields_dict.ingredients.grid.refresh();
                            frappe.show_alert({message: "库存单位已更新，请核对换算系数。", indicator: "orange"});
                        }},
                    ],
                    primary_action_label: "下一步 · 查看采购清单",
                    primary_action: async (values) => {
                        const mappings = Object.fromEntries(values.ingredients.map(row => [row.key, {
                            item_code: row.item_code, uom: row.uom, factor: row.factor,
                        }]));
                        const meals = this.procurementMealCounts(prepared.meals, values.meal_days);
                        const selectedMeals = prepared.meals.filter(row => values.include_history || row.date >= prepared.as_of_date);
                        const missing = selectedMeals.filter(row => !/^\d+$/.test(String(meals[row.key])));
                        if (missing.length) {
                            frappe.msgprint(`还需填写 ${missing.length} 个餐次的人数，例如 ${escapeHtml(missing[0].date)} ${escapeHtml(MEAL_LABELS[missing[0].slot])}。各餐人数相同时，可使用“统一备餐人数”。`);
                            return;
                        }
                        const args = {recipe, ...scope, include_history: values.include_history ? 1 : 0, mappings: JSON.stringify(mappings), meals: JSON.stringify(meals)};
                        const plan = await call("preview", args);
                        const dateNotice = `<p>单据日期：${escapeHtml(plan.transaction_date)}</p>` +
                            (plan.excluded_dates?.length ? `<p>已排除过去日期：${plan.excluded_dates.map(escapeHtml).join("、")}</p>` : "") +
                            (plan.historical_dates?.length ? `<p class="text-danger">历史补录日期：${plan.historical_dates.map(escapeHtml).join("、")}。为保留原用餐日期并符合 ERPNext 校验，单据日期设为最早补录日期；实际创建时间仍由系统记录。这不代表已采购、已入库或已付款，请核对原有采购记录，勿重复采购。</p>` : "");
                        const review = new frappe.ui.Dialog({
                            title: "确认采购清单", size: "large",
                            fields: [{fieldtype: "HTML", options: `${dateNotice}<p>这是总需求，尚未扣除库存及在途采购。创建后只保存为 ERPNext 草稿，由采购人员审核。</p><table class="table table-bordered"><thead><tr><th>日期</th><th>物料</th><th>数量</th><th>单位</th></tr></thead><tbody>${plan.lines.map(line => `<tr><td>${escapeHtml(line.schedule_date)}</td><td>${escapeHtml(line.item_name)}</td><td>${escapeHtml(String(line.qty))}</td><td>${escapeHtml(line.uom)}</td></tr>`).join("")}</tbody></table>`}],
                            primary_action_label: "确认创建草稿",
                            primary_action: async () => {
                                review.get_primary_btn().prop("disabled", true);
                                try {
                                    const result = await call("create_request", {...args, token: plan.token, confirmed: 1});
                                    review.hide(); dialog.hide();
                                    frappe.set_route("Form", "Material Request", result.name);
                                    frappe.show_alert(result.existing ? "已打开原有需求，未重复创建。" : "采购需求草稿已创建，尚未提交。");
                                } finally { review.get_primary_btn().prop("disabled", false); }
                            },
                        });
                        review.show();
                    },
                });
                dialog.show();
        } catch (error) {
            frappe.msgprint("准备采购需求未完成。请检查默认公司、默认仓库及账号权限；本次未创建采购需求。");
        }
    }

    async autoMatchProcurementItems(recipe, company) {
        let closed = false;
        const progress = new frappe.ui.Dialog({
            title: "正在自动匹配食材并创建物料",
            fields: [{fieldtype: "HTML", fieldname: "progress"}],
            primary_action_label: "关闭（后台继续）",
            primary_action: () => progress.hide(),
        });
        progress.onhide = () => { closed = true; };
        const show = message => progress.fields_dict.progress.$wrapper.text(message);
        progress.show();
        show("正在检查已有物料。缺少的食材将由 AI 分类并自动建档，完成后继续准备采购需求，请勿重复操作。");
        try {
            let state = (await frappe.call({method: "tongjianyun.recipe_procurement.auto_match_items", args: {recipe}, type: "POST"})).message || {};
            const deadline = Date.now() + 35 * 60 * 1000;
            while (!closed && ["queued", "running"].includes(state.status)) {
                show(state.message || "正在自动分类、创建物料，请稍候……");
                if (Date.now() > deadline) {
                    show("后台尚未结束，请稍后通过“食材物料匹配结果”查看进度。无需手动创建物料。");
                    return null;
                }
                await new Promise(resolve => setTimeout(resolve, 2000));
                if (closed) return null;
                state = (await frappe.call({method: "tongjianyun.recipe_item_sync.get_sync_status", args: {recipe}})).message || {};
            }
            if (closed) return null;
            if (["stale", "blocked", "failed", "not_started"].includes(state.status)) {
                show(state.message || "自动建档未完成，请稍后重试或联系管理员。无需手动创建物料。");
                return null;
            }
            const prepared = (await frappe.call({method: "tongjianyun.recipe_procurement.prepare", args: {recipe, company}})).message;
            if (closed) return null;
            const unresolved = Object.fromEntries((state.unresolved || []).map(row => [row.key, row.reason]));
            for (const row of prepared.ingredients) {
                if (!row.item_code && unresolved[row.key]) row.basis = unresolved[row.key];
            }
            progress.hide();
            if (prepared.ingredients.some(row => !row.item_code)) {
                frappe.msgprint("自动建档已完成一轮处理。剩余异常原因已列在食材表中；汤粥等请通过“食材用途确认”处理，分类服务或权限问题请重试或联系管理员，无需手动新建物料。");
            } else {
                frappe.show_alert({message: "食材已自动匹配建档，继续核对备餐人数。", indicator: "green"});
            }
            return prepared;
        } catch (error) {
            if (!closed) show("暂时无法完成自动建档。可关闭后重新点击准备采购需求，已有成功结果会保留，不需要手动新建物料。");
            return null;
        }
    }

    async resolveIngredients(recipe, company, parentDialog) {
        const unmatched = parentDialog.fields_dict.ingredients.df.data.filter(row => !row.item_code);
        if (!unmatched.length) { frappe.msgprint("所有食材已关联物料，请继续核对换算和人数。"); return; }
        const call = async (method, args) => (await frappe.call({method: `tongjianyun.ingredient_resolution.${method}`, args, freeze: true})).message;
        const rows = unmatched.map(row => {
            const candidate = row.candidates?.[0];
            const risky = row.needs_product_confirmation;
            const unit = candidate?.uom || row.suggested_uom || "";
            return {...row, action: risky || (candidate && candidate.score < .99) ? "暂不处理" : candidate ? "关联已有" : "新建物料",
                item_code: candidate?.score >= .99 ? candidate.item_code : "", uom: unit,
                factor: row.source_uom === unit ? 1 : "", external_product: 0,
                reason: risky ? "可能为自制菜品；外购成品需明确勾选" :
                    candidate ? `${candidate.reason}：${row.candidates.map(c => c.item_code).join("、")}` : "新食材候选，请核对名称和单位"};
        });
        const dialog = new frappe.ui.Dialog({
            title: `批量处理 ${rows.length} 项食材`, size: "extra-large",
            fields: [
                {fieldtype: "HTML", options: "<p>推荐不等于确认。新建物料会写入 ERPNext，预览前不会保存。暂不处理的项目仍会阻止生成完整采购需求。汤粥若是自制，请回食谱拆分配方，不要建成采购物料。</p>"},
                {fieldname: "default_group", label: "本批新物料分类（统一选择一次）", fieldtype: "Link", options: "Item Group",
                    get_query: () => ({filters: {is_group: 0}})},
                {fieldname: "decisions", label: "建议清单（展开行可查看建议原因）", fieldtype: "Table", cannot_add_rows: true, cannot_delete_rows: true, data: rows,
                    fields: [
                        {fieldname: "key", fieldtype: "Data", hidden: 1},
                        {fieldname: "ingredient", label: "食材", fieldtype: "Data", read_only: 1, in_list_view: 1, columns: 2},
                        {fieldname: "action", label: "处理", fieldtype: "Select", options: "暂不处理\n关联已有\n新建物料", in_list_view: 1, columns: 2},
                        {fieldname: "item_code", label: "关联物料", fieldtype: "Link", options: "Item", in_list_view: 1, columns: 2,
                            get_query: () => ({filters: {disabled: 0, is_stock_item: 1, is_purchase_item: 1, has_variants: 0}})},
                        {fieldname: "uom", label: "库存单位", fieldtype: "Link", options: "UOM", in_list_view: 1, columns: 1,
                            get_query: () => ({filters: {enabled: 1}})},
                        {fieldname: "factor", label: "毛料换算", fieldtype: "Float", in_list_view: 1, columns: 2},
                        {fieldname: "external_product", label: "外购成品", fieldtype: "Check", in_list_view: 1, columns: 1},
                        {fieldname: "source_uom", label: "食谱单位", fieldtype: "Data", read_only: 1},
                        {fieldname: "reason", label: "建议原因", fieldtype: "Small Text", read_only: 1},
                        {fieldname: "item_group", label: "单项分类（留空沿用本批分类）", fieldtype: "Link", options: "Item Group",
                            get_query: () => ({filters: {is_group: 0}})},
                    ]},
            ],
            primary_action_label: "预览本批变更",
            primary_action: async (values) => {
                const args = {recipe, company, default_group: values.default_group || "", decisions: JSON.stringify(values.decisions)};
                const plan = await call("preview_resolution", args);
                const count = plan.rows.filter(row => row.action === "新建物料").length;
                const review = new frappe.ui.Dialog({
                    title: `确认新建 ${count} 个物料，关联 ${plan.rows.length - count} 项`, size: "large",
                    fields: [{fieldtype: "HTML", options: `<p>仅保存本批物料及映射，不创建采购单、不产生库存或费用。</p><table class="table table-bordered"><thead><tr><th>食材</th><th>处理</th><th>物料</th><th>单位 / 换算</th><th>分类</th></tr></thead><tbody>${plan.rows.map(row => `<tr><td>${escapeHtml(row.ingredient)}</td><td>${escapeHtml(row.action)}</td><td>${escapeHtml(row.item_code)}</td><td>${escapeHtml(row.uom)} / ${escapeHtml(String(row.factor))}</td><td>${escapeHtml(row.item_group)}</td></tr>`).join("")}</tbody></table>`}],
                    primary_action_label: "确认并保存本批",
                    primary_action: async () => {
                        review.get_primary_btn().prop("disabled", true);
                        try {
                            const result = await call("apply_resolution", {...args, token: plan.token, confirmed: 1});
                            for (const row of parentDialog.fields_dict.ingredients.df.data) {
                                if (result.mappings[row.key]) Object.assign(row, result.mappings[row.key], {basis: "已批量确认"});
                            }
                            parentDialog.fields_dict.ingredients.grid.refresh();
                            review.hide(); dialog.hide();
                            frappe.show_alert(`已保存匹配，新建 ${result.created.length} 个物料。`);
                        } finally { review.get_primary_btn().prop("disabled", false); }
                    },
                });
                review.show();
            },
        });
        dialog.show();
    }

    clearPagePrimaryAction() {
        if (typeof this.page.clear_primary_action === "function") this.page.clear_primary_action();
    }

    editRecipe() {
        const recipe = this.state.payload?.recipe;
        if (!recipe) return;
        if (["已发布", "已归档"].includes(recipe.workflowStatus)) {
            const payload = normalizePayload(this.state.payload);
            payload.recipe.recipeId = `${recipe.recipeId || "RECIPE"}-REV-${Date.now().toString().slice(-6)}`;
            payload.recipe.title = `${String(recipe.title || "周食谱").replace(/（修订版）$/, "")}（修订版）`;
            payload.recipe.workflowStatus = "草稿";
            this.state.payload = payload;
            this.state.selectedRecipe = null;
            frappe.show_alert({ message: "已根据发布版创建草稿修订版", indicator: "blue" });
        }
        this.enterEdit();
    }

    openImport() {
        const dialog = new frappe.ui.Dialog({
            title: "I-ONE Agent 导入食谱",
            size: "large",
            fields: [
                {
                    fieldname: "import_help",
                    fieldtype: "HTML",
                    options: `
                        <div class="alert alert-info" style="margin-bottom: 12px;">
                            上传幼儿园周食谱 Excel。I-ONE Agent 会识别合并单元格、餐次、菜品、食材和每生带量，
                            识别结果将先进入草稿编辑页，由您校对后再保存。
                        </div>
                    `,
                },
                {
                    fieldname: "recipe_file",
                    fieldtype: "Attach",
                    label: "食谱文件（.xlsx）",
                    reqd: 1,
                    options: {
                        restrictions: {
                            allowed_file_types: [".xlsx"],
                            max_file_size: 10 * 1024 * 1024,
                        },
                    },
                },
                {
                    fieldname: "import_status",
                    fieldtype: "HTML",
                },
            ],
            primary_action_label: "开始识别",
            primary_action: async () => {
                const fileUrl = String(dialog.get_value("recipe_file") || "").trim();
                if (!fileUrl) {
                    frappe.msgprint("请先上传 .xlsx 食谱文件。");
                    return;
                }
                if (!fileUrl.toLowerCase().endsWith(".xlsx")) {
                    frappe.msgprint("目前仅支持 .xlsx 食谱文件。");
                    return;
                }

                const button = dialog.get_primary_btn();
                button.prop("disabled", true).text("正在提交...");
                dialog.__recipeImportPolling = true;
                this.updateImportStatus(dialog, {
                    progress: 2,
                    message: "正在创建 I-ONE Agent 识别任务...",
                });
                try {
                    const response = await frappe.call({
                        method: "tongjianyun.recipe_import.start_recipe_import",
                        args: { file_url: fileUrl },
                    });
                    const importId = response.message?.import_id;
                    if (!importId) throw new Error("服务器未返回导入任务编号。");

                    while (dialog.__recipeImportPolling) {
                        await new Promise((resolve) => setTimeout(resolve, 1400));
                        const statusResponse = await frappe.call({
                            method: "tongjianyun.recipe_import.get_recipe_import_status",
                            args: { import_id: importId },
                        });
                        const status = statusResponse.message || {};
                        this.updateImportStatus(dialog, status);
                        if (status.status === "failed") {
                            throw new Error(status.message || "识别失败，请重试。");
                        }
                        if (status.status !== "completed") continue;

                        const result = status.result || {};
                        if (!result.payload) throw new Error("识别结果为空，请重试。");
                        dialog.__recipeImportPolling = false;
                        this.state.payload = normalizePayload(result.payload);
                        this.state.selectedRecipe = null;
                        this.state.activeDay = 0;
                        this.state.activeSlot = "breakfast";
                        this.state.activeDish = 0;
                        dialog.hide();
                        this.enterEdit();

                        const summary = result.summary || {};
                        frappe.show_alert({
                            message: `识别完成：${summary.day_count || 0} 天、${summary.dish_count || 0} 个菜品，请校对后保存`,
                            indicator: "green",
                        }, 8);
                        const warnings = Array.isArray(result.warnings) ? result.warnings : [];
                        if (warnings.length) {
                            const escape = frappe.utils.escape_html;
                            frappe.msgprint({
                                title: `导入提醒（${warnings.length} 项）`,
                                indicator: "orange",
                                message: warnings.slice(0, 20).map((item) => `• ${escape(String(item))}`).join("<br>"),
                            });
                        }
                        return;
                    }
                } catch (error) {
                    dialog.__recipeImportPolling = false;
                    this.updateImportStatus(dialog, {
                        status: "failed",
                        progress: 100,
                        message: error?.message || "识别失败，请检查文件后重试。",
                    });
                    button.prop("disabled", false).text("重新识别");
                }
            },
        });
        dialog.$wrapper.on("hidden.bs.modal", () => {
            dialog.__recipeImportPolling = false;
        });
        dialog.show();
        this.updateImportStatus(dialog, {
            progress: 0,
            message: "等待上传文件。原表内容仅作为待识别数据处理。",
        });
    }

    updateImportStatus(dialog, status) {
        const progress = Math.max(0, Math.min(100, Number(status.progress || 0)));
        const failed = status.status === "failed";
        const completed = status.status === "completed";
        const color = failed ? "#c92a2a" : (completed ? "#2b8a3e" : "#228be6");
        const wrapper = dialog.fields_dict.import_status.$wrapper.empty();
        const card = $("<div>").css({
            border: "1px solid var(--border-color)",
            borderRadius: "8px",
            padding: "12px 14px",
            marginTop: "10px",
            background: "var(--subtle-fg)",
        }).appendTo(wrapper);
        $("<div>").css({ fontWeight: 600, marginBottom: "8px" })
            .text(status.message || "正在处理...")
            .appendTo(card);
        const track = $("<div>").css({
            height: "8px",
            borderRadius: "999px",
            overflow: "hidden",
            background: "var(--gray-200)",
        }).appendTo(card);
        $("<div>").css({
            height: "100%",
            width: `${progress}%`,
            transition: "width .25s ease",
            background: color,
        }).appendTo(track);
        $("<div>").css({ marginTop: "6px", color: "var(--text-muted)", fontSize: "12px" })
            .text(`${progress}%`)
            .appendTo(card);
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
        const existing = document.getElementById("tjy-recipe-page-styles");
        if (existing) {
            existing.textContent = RECIPE_STYLES;
            return;
        }
        $("<style>", { id: "tjy-recipe-page-styles", text: RECIPE_STYLES }).appendTo(document.head);
    }
}

const MEAL_SLOTS = ["breakfast", "morningSnack", "lunch", "snack", "dinner"];
const MEAL_LABELS = { breakfast: "早餐", morningSnack: "早点", lunch: "午餐", snack: "午点", dinner: "晚餐" };

function normalizePayload(payload) {
    const result = payload && typeof payload === "object" ? JSON.parse(JSON.stringify(payload)) : {};
    result.recipe = result.recipe || {};
    result.recipe.workflowStatus = result.recipe.workflowStatus || "草稿";
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

function recipeStatusClass(status) {
    return { "草稿": "draft", "待审核": "review", "已发布": "published", "已归档": "archived" }[status] || "draft";
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

function formatEditorRange(start, end) {
    if (!start && !end) return "日期未设置";
    const startParts = String(start || "").split("-");
    const endParts = String(end || "").split("-");
    if (startParts.length !== 3 || endParts.length !== 3) return formatFriendlyRange(start, end);
    return `${startParts[0]}年${Number(startParts[1])}月${Number(startParts[2])}日—${Number(endParts[1])}月${Number(endParts[2])}日`;
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

function formatCurrentTime() {
    const now = new Date();
    return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
}

function mealIcon(slot) {
    const icons = {
        breakfast: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"></path></svg>',
        morningSnack: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 9h12v4a6 6 0 0 1-6 6 6 6 0 0 1-6-6V9Z"></path><path d="M17 11h2a2 2 0 0 1 0 4h-2M8 6c0-1 1-1.2 1-2M12 6c0-1 1-1.2 1-2"></path></svg>',
        lunch: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"></circle><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"></path></svg>',
        snack: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 10h12v3a6 6 0 0 1-6 6 6 6 0 0 1-6-6v-3Z"></path><path d="M17 12h2a2 2 0 0 1 0 4h-2M9 7c-1-2 2-2 1-4M13 7c-1-2 2-2 1-4"></path></svg>',
        dinner: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 15.5A8 8 0 0 1 8.5 5a8 8 0 1 0 10.5 10.5Z"></path></svg>',
    };
    return icons[slot] || "";
}

function editorActionIcon(type) {
    if (type === "edit") {
        return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-4-4L4 16v4Z"></path><path d="m13.5 6.5 4 4"></path></svg>';
    }
    return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3M7 7l1 13h8l1-13M10 11v5M14 11v5"></path></svg>';
}

function renderNutritionEstimate(rows) {
    const gramsTotal = (rows || []).reduce((sum, row) => sum + Number(row.gramsPerChild || gramsFromRow(row) || 0), 0);
    const energy = Math.max(0, Math.round(gramsTotal * 0.528));
    const protein = (gramsTotal * 0.027).toFixed(1);
    const fat = (gramsTotal * 0.0288).toFixed(1);
    const carbohydrate = (gramsTotal * 0.0384).toFixed(1);
    const calcium = Math.round(gramsTotal * 0.96);
    const iron = (gramsTotal * 0.0004).toFixed(1);
    const zinc = (gramsTotal * 0.0028).toFixed(1);
    const vitaminA = Math.round(gramsTotal * 0.24);
    return `<div class="tjy-nutrition"><h3>营养成分（每人）</h3><div class="tjy-nutrition-grid"><div><span>能量</span><strong>${energy} kcal</strong></div><div><span>蛋白质</span><strong>${protein} g</strong></div><div><span>脂肪</span><strong>${fat} g</strong></div><div><span>碳水化合物</span><strong>${carbohydrate} g</strong></div><div><span>钙</span><strong>${calcium} mg</strong></div><div><span>铁</span><strong>${iron} mg</strong></div><div><span>锌</span><strong>${zinc} mg</strong></div><div><span>维生素 A</span><strong>${vitaminA} μg RE</strong></div></div><p>ⓘ 营养数据为估算值，仅供参考</p></div>`;
}

function summaryIcon(type) {
    const icons = {
        calendar: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="5.5" width="17" height="15" rx="1.5"></rect><path d="M7.5 3v5M16.5 3v5M3.5 10h17"></path></svg>',
        days: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3v8M10 3v8M4 3v4c0 2 1.3 4 4 4s4-2 4-4V3M8 11v10M17 3c-2 2-3 5-3 8h6c0-3-1-6-3-8Zm0 8v10"></path></svg>',
        meals: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7c0-2 1.5-3 3.5-3h7C17.5 4 19 5 19 7l-1 11c-.1 1.2-1.1 2-2.3 2H8.3C7.1 20 6.1 19.2 6 18L5 7Z"></path><path d="M7 8h10M9 13h6"></path></svg>',
        dishes: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 18h18M5 17a7 7 0 0 1 14 0M12 8V5M10 5h4"></path></svg>',
    };
    return icons[type] || "";
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

function renderRecipeActions(item, options = {}) {
    const actions = item.actions || {};
    const rows = ['<button data-recipe-action="copy">复制</button>'];
    if (actions.can_withdraw) rows.push('<button data-recipe-action="withdraw">撤回为草稿</button>');
    if (actions.can_archive) rows.push('<button data-recipe-action="archive">归档</button>');
    if (actions.can_delete && options.includeDelete !== false) rows.push('<button class="danger" data-recipe-action="delete">删除</button>');
    if (actions.can_restore) rows.push('<button data-recipe-action="restore">恢复</button>');
    if (!actions.can_delete && actions.business_links?.length) {
        rows.push(`<span class="tjy-action-disabled">已有${actions.business_links.map((row) => escapeHtml(row.label)).join("、")}数据</span>`);
    }
    return rows.join("");
}

const RECIPE_STYLES = `
.tjy-bulk-delete{height:34px;padding:0 12px;border:1px solid #e2b8b4;border-radius:7px;background:#fff;color:#b42318}.tjy-bulk-delete:disabled{border-color:#e4e4e2;color:#aaa;cursor:not-allowed}.tjy-select-cell{width:42px!important;text-align:center!important;padding-left:12px!important;padding-right:6px!important}.tjy-select-cell input{width:16px;height:16px;accent-color:#202123}
.tjy-create-wrap{display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:flex-end}.tjy-library-filters{display:flex;align-items:center;gap:16px;flex-wrap:wrap;justify-content:flex-end}.tjy-status-tabs{display:flex;gap:3px;padding:3px;border:1px solid #e4e4e2;border-radius:9px;background:#f7f7f5}.tjy-status-tabs button{border:0;background:transparent;color:#6f7073;height:30px;padding:0 11px;border-radius:6px}.tjy-status-tabs button.active{background:#fff;color:#202123;box-shadow:0 1px 2px rgba(0,0,0,.08)}.tjy-test-toggle{display:flex;align-items:center;gap:5px;font-weight:400;margin:0;white-space:nowrap}.tjy-clean-test-button{border:0;background:transparent;color:#b42318;font-size:12px}.tjy-status.review{background:#fff3d6;color:#8a5a00}.tjy-status.published{background:#e8f6ed;color:#18733c}.tjy-status.archived{background:#ececec;color:#616161}.tjy-status.deleted{background:#fce8e6;color:#b42318}.tjy-status-select{height:38px;border:1px solid #e4e4e2;border-radius:7px;background:#fff;padding:0 28px 0 10px;color:#202123}.tjy-row-actions{display:flex;align-items:center;justify-content:flex-end;gap:12px;white-space:nowrap}.tjy-row-delete{border:0;background:transparent;color:#b42318;padding:0;cursor:pointer}.tjy-row-delete:hover{text-decoration:underline}.tjy-action-menu-wrap{position:relative}.tjy-row-more{width:30px;height:30px;border:0;border-radius:7px;background:transparent;color:#555;font-weight:700}.tjy-row-more:hover{background:#f1f1ef}.tjy-action-menu{display:none;position:absolute;z-index:20;right:0;top:34px;min-width:150px;padding:5px;background:#fff;border:1px solid #dededb;border-radius:9px;box-shadow:0 10px 28px rgba(0,0,0,.13)}.tjy-action-menu.open{display:block}.tjy-action-menu button,.tjy-action-disabled{display:block;width:100%;border:0;background:transparent;text-align:left;padding:8px 10px;border-radius:6px;color:#202123;white-space:nowrap}.tjy-action-menu button:hover{background:#f4f4f2}.tjy-action-menu button.danger{color:#b42318}.tjy-action-disabled{color:#8a8a8a;font-size:11px;white-space:normal}
.tjy-recipe-app{--tjy-ink:#202123;--tjy-muted:#6f7073;--tjy-line:#e4e4e2;--tjy-soft:#f7f7f5;--tjy-green:#23884b;width:100%;max-width:none;margin:0;padding:18px 24px 52px;color:var(--tjy-ink)}
body:has(.tjy-recipe-app) .layout-main-section{background:#fff}body:has(.tjy-recipe-app) .page-body{background:#fff}
body:has(.tjy-recipe-app) .page-head .page-title .title-text{font-weight:500}.tjy-screen button{font-family:inherit}
.tjy-screen h1,.tjy-screen h2,.tjy-screen p{margin:0}.tjy-screen h1{font-size:25px;line-height:1.25;letter-spacing:-.025em}.tjy-screen h2{font-size:16px;letter-spacing:-.01em}.tjy-screen p{color:var(--tjy-muted);margin-top:7px}.tjy-title-input{display:block;width:min(720px,70vw);border:0;background:transparent;padding:0;font-size:25px;font-weight:650;line-height:1.25;letter-spacing:-.025em;color:var(--tjy-ink);outline:0}.tjy-date-inputs{display:flex;align-items:end;gap:10px;margin-top:15px;color:var(--tjy-muted)}.tjy-date-inputs label{font-size:11px}.tjy-date-inputs input{display:block;border:1px solid var(--tjy-line);border-radius:7px;background:#fff;padding:5px 8px;margin-top:4px;color:var(--tjy-ink)}.tjy-hero,.tjy-editor-head,.tjy-library-head{display:flex;align-items:flex-start;justify-content:space-between;gap:30px;padding:8px 0 24px}.tjy-hero-actions{display:flex;gap:8px;flex:none}.tjy-link-button,.tjy-row-open{border:0;background:transparent;color:var(--tjy-muted);padding:0;cursor:pointer}.tjy-link-button{display:block;margin-bottom:22px}.tjy-link-button:hover,.tjy-row-open:hover{color:var(--tjy-ink)}.tjy-eyebrow,.tjy-pane-label{font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--tjy-muted);margin-bottom:8px}.tjy-stat-row{display:flex;gap:26px;padding:13px 0 20px;border-top:1px solid var(--tjy-line);color:var(--tjy-muted);font-size:13px}.tjy-stat-row strong{color:var(--tjy-ink);font-size:15px;margin-right:3px}.tjy-week-scroll{overflow-x:auto;border:1px solid var(--tjy-line);border-radius:12px;background:#fff}.tjy-week-grid{display:grid;grid-template-columns:90px repeat(var(--day-count),minmax(180px,1fr));min-width:980px}.tjy-week-corner,.tjy-week-day-head,.tjy-week-label{background:var(--tjy-soft);border-right:1px solid var(--tjy-line);border-bottom:1px solid var(--tjy-line);padding:13px 14px}.tjy-week-day-head{display:flex;justify-content:space-between;gap:10px}.tjy-week-day-head span{color:var(--tjy-muted);font-size:12px}.tjy-week-label{font-size:12px;font-weight:600}.tjy-week-cell{min-height:104px;text-align:left;display:flex;flex-direction:column;gap:7px;border:0;border-right:1px solid var(--tjy-line);border-bottom:1px solid var(--tjy-line);background:#fff;padding:14px;cursor:pointer;color:var(--tjy-ink)}.tjy-week-cell:hover{background:#fafafa}.tjy-week-cell span{line-height:1.35}.tjy-cell-empty{color:#aaa}.tjy-source-details{margin-top:18px;border-top:1px solid var(--tjy-line);padding-top:15px;color:var(--tjy-muted)}.tjy-source-details summary{cursor:pointer;font-weight:600;color:var(--tjy-ink)}.tjy-source-grid{display:grid;grid-template-columns:110px 1fr;gap:9px 16px;margin-top:15px;max-width:760px}.tjy-source-grid strong{font-weight:500;color:var(--tjy-ink);overflow-wrap:anywhere}.tjy-day-tabs{display:flex;gap:4px;border-bottom:1px solid var(--tjy-line);overflow-x:auto}.tjy-day-tab{border:0;background:transparent;padding:12px 18px;color:var(--tjy-muted);border-bottom:2px solid transparent;min-width:110px}.tjy-day-tab strong,.tjy-day-tab span{display:block}.tjy-day-tab span{font-size:11px;margin-top:3px}.tjy-day-tab.active{color:var(--tjy-ink);border-bottom-color:var(--tjy-ink)}.tjy-workbench{display:grid;grid-template-columns:180px minmax(340px,1fr) minmax(340px,.9fr);min-height:560px;border:1px solid var(--tjy-line);border-top:0;border-radius:0 0 12px 12px;overflow:hidden}.tjy-meal-nav,.tjy-dish-pane,.tjy-ingredient-pane{padding:20px}.tjy-meal-nav,.tjy-dish-pane{border-right:1px solid var(--tjy-line)}.tjy-meal-item{width:100%;border:0;background:transparent;padding:11px 12px;border-radius:8px;display:flex;justify-content:space-between;margin-bottom:4px}.tjy-meal-item small{color:var(--tjy-muted)}.tjy-meal-item.active{background:var(--tjy-soft);font-weight:600}.tjy-pane-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:18px}.tjy-dish-row{display:grid;grid-template-columns:22px 1fr 30px;gap:7px;align-items:center;border:1px solid var(--tjy-line);border-radius:9px;padding:9px 10px;margin-bottom:8px}.tjy-dish-row.selected{border-color:#a8a8a4}.tjy-dish-row input,.tjy-ingredient-row input,.tjy-ingredient-row select{border:0;background:transparent;outline:0;width:100%;color:var(--tjy-ink)}.tjy-drag-handle{color:#aaa;cursor:grab}.tjy-icon-button{border:0;background:transparent;color:#aaa;font-size:18px}.tjy-ingredient-row{display:grid;grid-template-columns:minmax(110px,1fr) 80px 55px 26px;gap:7px;align-items:center;border-bottom:1px solid var(--tjy-line);padding:11px 0}.tjy-ingredient-row input:nth-child(2){text-align:right}.tjy-empty-panel{min-height:180px;border:1px dashed #d9d9d6;border-radius:10px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;color:var(--tjy-muted)}.tjy-empty-panel.compact{min-height:120px}.tjy-library-tools{display:flex;justify-content:space-between;align-items:center;padding:13px 0;color:var(--tjy-muted)}.tjy-search-wrap{display:flex;align-items:center;gap:8px;border:1px solid var(--tjy-line);border-radius:9px;padding:7px 10px;width:min(380px,70vw);background:#fff}.tjy-search-wrap input{border:0;outline:0;width:100%;background:transparent}.tjy-library-table-wrap{border:1px solid var(--tjy-line);border-radius:12px;overflow-x:auto;background:#fff}.tjy-library-table{width:100%;border-collapse:collapse;min-width:900px}.tjy-library-table th{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:var(--tjy-muted);background:var(--tjy-soft);font-weight:600;text-align:left;padding:12px 14px}.tjy-library-table td{padding:14px;border-top:1px solid var(--tjy-line);vertical-align:middle}.tjy-library-table tbody tr{cursor:pointer}.tjy-library-table tbody tr:hover{background:#fafafa}.tjy-library-table td:first-child strong,.tjy-library-table td:first-child span{display:block}.tjy-library-table td:first-child span{color:var(--tjy-muted);font-size:11px;margin-top:4px}.tjy-status{display:inline-flex;padding:4px 8px;border-radius:999px;background:#f0f0ee;color:var(--tjy-muted);font-size:11px}.tjy-status.complete{background:#eaf5ef;color:#247249}.tjy-loading,.tjy-error-card{min-height:360px;display:flex;align-items:center;justify-content:center;gap:10px;color:var(--tjy-muted)}.tjy-error-card{flex-direction:column}.tjy-error-card strong{font-size:16px;color:var(--tjy-ink)}
.tjy-browse-head{display:flex;align-items:flex-start;justify-content:space-between;gap:28px;padding:2px 0 28px}.tjy-title-line{display:flex;align-items:center;gap:12px}.tjy-title-line h1{font-size:23px;font-weight:650}.tjy-draft-pill{font-size:12px;color:var(--tjy-green);background:#e9f7ed;border-radius:7px;padding:5px 10px}.tjy-week-switcher{display:flex;align-items:center;gap:10px;margin-top:17px}.tjy-week-switcher>strong{font-size:16px;margin-left:4px}.tjy-square-button,.tjy-more-button,.tjy-back-button{display:inline-flex;align-items:center;justify-content:center;width:40px;height:40px;border:1px solid var(--tjy-line);border-radius:9px;background:#fff;color:var(--tjy-ink);font-size:24px}.tjy-switcher-divider{height:22px;border-left:1px solid var(--tjy-line);margin:0 5px}.tjy-outline-button,.tjy-primary-button{height:42px;border-radius:9px;padding:0 22px;display:inline-flex;align-items:center;justify-content:center;gap:8px;font-weight:600}.tjy-outline-button{background:#fff;border:1px solid var(--tjy-line);color:var(--tjy-ink)}.tjy-primary-button{background:#171717;border:1px solid #171717;color:#fff;min-width:108px}.tjy-outline-button.compact{height:34px;padding:0 13px;font-weight:500}.tjy-browse-layout{display:grid;grid-template-columns:minmax(720px,1fr) 356px;gap:24px;align-items:stretch}.tjy-browse-main{min-width:0}.tjy-summary-card{display:grid;grid-template-columns:1.2fr repeat(3,1fr);border:1px solid var(--tjy-line);border-radius:11px;padding:26px 24px;margin-bottom:22px;min-height:90px}.tjy-summary-item{display:flex;align-items:center;gap:18px;padding:0 25px;border-right:1px solid var(--tjy-line)}.tjy-summary-item:first-child{padding-left:15px}.tjy-summary-item:last-child{border-right:0}.tjy-summary-icon{width:30px;height:30px;color:#4d4d4d;display:flex;align-items:center;justify-content:center;flex:none}.tjy-summary-icon svg{width:28px;height:28px;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.tjy-summary-item strong,.tjy-summary-item small{display:block;white-space:nowrap}.tjy-summary-item strong{font-size:14px;font-weight:600}.tjy-summary-item small{color:var(--tjy-muted);margin-top:4px}.tjy-week-scroll{border-radius:10px;overflow:hidden}.tjy-week-grid{grid-template-columns:96px repeat(var(--day-count),minmax(125px,1fr));min-width:760px}.tjy-week-corner,.tjy-week-day-head,.tjy-week-label{background:#fff;padding:13px 14px}.tjy-week-label{display:flex;align-items:flex-start;font-size:14px;font-weight:600;padding-top:21px}.tjy-week-label:before{display:inline-flex;width:22px;margin-right:7px;font-size:17px;font-weight:400;color:#515255}.tjy-week-label:nth-of-type(7):before,.tjy-week-label:nth-of-type(19):before{content:'☼'}.tjy-week-label:nth-of-type(13):before{content:'▱'}.tjy-week-label:nth-of-type(25):before{content:'◉'}.tjy-week-label:nth-of-type(31):before{content:'☾'}.tjy-week-day-head{justify-content:center;align-items:center;min-height:44px}.tjy-week-day-head strong{margin-right:8px}.tjy-week-cell{min-height:112px;font-size:13px;padding:16px;gap:5px}.tjy-week-cell.selected{background:#fafafa;box-shadow:inset 0 0 0 1px #bdbdb8;border-radius:8px}.tjy-browse-inspector{border:1px solid var(--tjy-line);border-radius:10px;background:#fff;overflow:hidden;min-height:100%}.tjy-inspector-head{height:54px;padding:0 18px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--tjy-line)}.tjy-inspector-close{border:0;background:transparent;color:#8a8a8a;font-size:22px;font-weight:300;line-height:1}.tjy-inspector-section{padding:17px 18px;border-bottom:1px solid var(--tjy-line)}.tjy-inspector-section h3{font-size:14px;margin:0 0 12px}.tjy-inspector-section h3 span{font-weight:400;color:var(--tjy-muted)}.tjy-dish-summary{padding-left:22px;margin:0}.tjy-dish-summary li{padding:4px 0}.tjy-inspector-table{font-size:12px}.tjy-inspector-tr{display:grid;grid-template-columns:1fr 75px 45px;padding:7px 0;border-bottom:1px solid #efefed}.tjy-inspector-tr span:nth-child(2),.tjy-inspector-tr span:nth-child(3){text-align:right}.tjy-inspector-tr.head{color:var(--tjy-muted)}.tjy-inspector-note{font-size:11px!important;line-height:1.5}.tjy-inspector-empty{color:var(--tjy-muted);font-size:13px;padding:14px 0}
.tjy-editor-head{padding:0 0 16px;align-items:center}.tjy-editor-title-group{display:flex;align-items:center;gap:16px}.tjy-title-input{font-size:20px;width:min(650px,52vw)}.tjy-date-inputs{margin-top:4px;align-items:center}.tjy-date-inputs input{border:0;padding:0;margin:0;color:var(--tjy-muted);font-size:12px;width:115px}.tjy-save-state{display:flex;align-items:center;gap:7px;color:var(--tjy-muted);margin-right:14px}.tjy-save-state i{width:8px;height:8px;background:#2aa06a;border-radius:50%}.tjy-more-button{font-size:15px}.tjy-day-tabs{background:var(--tjy-soft);border:1px solid var(--tjy-line);border-radius:10px;padding:5px;justify-content:space-between}.tjy-day-tab{flex:1;border:0!important;border-radius:8px;min-width:120px}.tjy-day-tab.active{background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.07)}.tjy-workbench{grid-template-columns:160px minmax(360px,1.05fr) minmax(400px,1fr);min-height:660px;border:0;border-radius:0}.tjy-meal-nav,.tjy-dish-pane,.tjy-ingredient-pane{padding:28px 20px}.tjy-meal-nav,.tjy-dish-pane{border-right:1px solid var(--tjy-line)}.tjy-meal-item{padding:15px 18px;border-radius:0;border-left:2px solid transparent;font-size:15px}.tjy-meal-item.active{border-left-color:#171717;background:var(--tjy-soft)}.tjy-pane-head>div{display:flex;align-items:baseline;gap:14px}.tjy-pane-head h2{font-size:19px}.tjy-pane-count{color:var(--tjy-muted)}.tjy-dish-row{grid-template-columns:24px 28px 1fr 24px 24px;min-height:68px;padding:10px 14px;border-radius:8px}.tjy-dish-index{color:var(--tjy-muted)}.tjy-row-edit{color:var(--tjy-muted);display:flex}.tjy-selected-dish{display:flex;justify-content:space-between;align-items:center;margin:4px 0 17px}.tjy-selected-dish strong{font-size:16px}.tjy-selected-dish span{color:var(--tjy-muted)}.tjy-ingredient-labels{display:grid;grid-template-columns:minmax(110px,1fr) 90px 60px 30px;color:var(--tjy-muted);font-size:11px;padding:10px 0;border:1px solid var(--tjy-line);border-bottom:0;border-radius:8px 8px 0 0}.tjy-ingredient-labels span{padding-left:10px}.tjy-ingredient-row{grid-template-columns:minmax(110px,1fr) 90px 60px 30px;border:1px solid var(--tjy-line);border-bottom:0;padding:13px 6px}.tjy-ingredient-row:last-child{border-bottom:1px solid var(--tjy-line);border-radius:0 0 8px 8px}.tjy-nutrition{margin-top:30px}.tjy-nutrition h3{font-size:15px;margin-bottom:14px}.tjy-nutrition-grid{border:1px solid var(--tjy-line);border-radius:8px;display:grid;grid-template-columns:repeat(4,1fr)}.tjy-nutrition-grid>div{padding:14px;border-right:1px solid var(--tjy-line);border-bottom:1px solid var(--tjy-line)}.tjy-nutrition-grid>div:nth-child(4n){border-right:0}.tjy-nutrition-grid>div:nth-last-child(-n+4){border-bottom:0}.tjy-nutrition-grid span,.tjy-nutrition-grid strong{display:block}.tjy-nutrition-grid span{color:var(--tjy-muted);font-size:11px}.tjy-nutrition-grid strong{margin-top:7px;font-weight:500}.tjy-nutrition p{font-size:11px!important;margin-top:12px!important}
@media(max-width:1250px){.tjy-browse-layout{grid-template-columns:1fr}.tjy-browse-inspector{display:grid;grid-template-columns:220px 1fr}.tjy-inspector-head{grid-column:1/-1}.tjy-workbench{grid-template-columns:145px 1fr}.tjy-ingredient-pane{grid-column:1/-1;border-top:1px solid var(--tjy-line)}.tjy-dish-pane{border-right:0}.tjy-meal-nav{border-right:1px solid var(--tjy-line)}}
@media(max-width:760px){.tjy-recipe-app{padding:14px 10px 42px}.tjy-browse-head,.tjy-editor-head,.tjy-library-head{display:block}.tjy-hero-actions{margin-top:16px;flex-wrap:wrap}.tjy-summary-card{grid-template-columns:1fr 1fr;padding:10px}.tjy-summary-item{padding:12px!important;border:0}.tjy-browse-inspector{display:block}.tjy-editor-title-group{align-items:flex-start}.tjy-title-input{width:calc(100vw - 120px);font-size:17px}.tjy-save-state{display:none}.tjy-workbench{display:block}.tjy-meal-nav,.tjy-dish-pane{border-right:0;border-bottom:1px solid var(--tjy-line)}.tjy-meal-nav{display:grid;grid-template-columns:repeat(3,1fr);gap:4px}.tjy-meal-nav .tjy-pane-label{grid-column:1/-1}.tjy-source-grid{grid-template-columns:1fr}.tjy-ingredient-row,.tjy-ingredient-labels{grid-template-columns:1fr 70px 50px 24px}}
.tjy-week-label-breakfast:before,.tjy-week-label-lunch:before{content:'☼'!important}.tjy-week-label-morningSnack:before{content:'▱'!important}.tjy-week-label-snack:before{content:'◉'!important}.tjy-week-label-dinner:before{content:'☾'!important}
.tjy-week-cell-breakfast{min-height:118px}.tjy-week-cell-morningSnack{min-height:76px}.tjy-week-cell-lunch{min-height:132px}.tjy-week-cell-snack{min-height:79px}.tjy-week-cell-dinner{min-height:122px}
body:has(.tjy-edit-screen) .page-head{display:none!important}body:has(.tjy-edit-screen) .page-body{margin-top:0!important}body:has(.tjy-edit-screen) .layout-main-section-wrapper{margin-top:0!important}.tjy-edit-screen{margin:-18px -24px -52px;min-height:calc(100vh - 1px);background:#fff}.tjy-edit-screen .tjy-editor-head{height:80px;padding:0 26px;border-bottom:1px solid var(--tjy-line);align-items:center}.tjy-edit-screen .tjy-editor-title-group{display:flex;align-items:center;gap:16px;min-width:0}.tjy-edit-screen .tjy-back-button{width:36px;height:36px;border:0;background:transparent;border-radius:8px;font-size:24px;flex:none}.tjy-editor-week-title{font-size:22px!important;font-weight:650;white-space:nowrap;margin:0}.tjy-edit-screen .tjy-date-inputs{display:flex;align-items:center;margin:0 0 0 2px;color:var(--tjy-muted);font-size:15px;white-space:nowrap}.tjy-edit-screen .tjy-date-inputs input{display:none}.tjy-edit-screen .tjy-hero-actions{align-items:center;gap:14px}.tjy-edit-screen .tjy-save-state{font-size:14px;margin-right:8px}.tjy-edit-screen .tjy-more-button{width:42px;height:42px;font-size:14px}.tjy-edit-screen .tjy-primary-button{height:42px;min-width:115px;border-radius:8px}.tjy-edit-screen .tjy-day-tabs{height:60px;margin:8px 18px;border:1px solid var(--tjy-line);border-radius:10px;padding:5px;background:#fafafa;align-items:stretch}.tjy-edit-screen .tjy-day-tab{display:flex;align-items:center;justify-content:center;gap:9px;min-width:0;padding:0 12px;border-radius:8px!important;font-size:15px}.tjy-edit-screen .tjy-day-tab strong,.tjy-edit-screen .tjy-day-tab span{display:inline;margin:0}.tjy-edit-screen .tjy-day-tab span{font-size:14px;color:var(--tjy-muted)}.tjy-edit-screen .tjy-day-tab.active{background:#fff;border:1px solid #dededb!important;box-shadow:0 1px 3px rgba(0,0,0,.06)}.tjy-edit-screen .tjy-workbench{height:calc(100vh - 156px);min-height:650px;margin-left:18px;grid-template-columns:160px minmax(520px,1.08fr) minmax(480px,.92fr);border:0;border-top:1px solid var(--tjy-line);overflow:visible}.tjy-edit-screen .tjy-meal-nav{padding:20px 0;border-right:1px solid var(--tjy-line)}.tjy-edit-screen .tjy-pane-label{display:none}.tjy-edit-screen .tjy-meal-item{height:64px;margin:0;padding:0 20px;display:grid;grid-template-columns:32px 1fr;align-items:center;text-align:left;border:0;border-left:2px solid transparent;border-radius:0;font-size:16px}.tjy-edit-screen .tjy-meal-item.active{background:#f5f5f3;border-left-color:#171717}.tjy-meal-icon{display:flex;width:24px;height:24px;color:#303134}.tjy-meal-icon svg{width:23px;height:23px;fill:none;stroke:currentColor;stroke-width:1.5;stroke-linecap:round;stroke-linejoin:round}.tjy-edit-screen .tjy-dish-pane,.tjy-edit-screen .tjy-ingredient-pane{padding:32px 24px;overflow-y:auto}.tjy-edit-screen .tjy-dish-pane{border-right:1px solid var(--tjy-line)}.tjy-edit-screen .tjy-ingredient-pane{border:0}.tjy-edit-screen .tjy-pane-head{align-items:center;margin:0 0 28px}.tjy-edit-screen .tjy-pane-head>div{gap:20px}.tjy-edit-screen .tjy-pane-head h2{font-size:21px}.tjy-edit-screen .tjy-pane-count{font-size:14px}.tjy-edit-screen .tjy-outline-button.compact{height:38px;padding:0 14px;border-radius:7px;font-size:14px}.tjy-edit-screen .tjy-dish-list:before,.tjy-edit-screen .tjy-dish-list:after{content:none!important;display:none!important}.tjy-edit-screen .tjy-dish-labels{display:grid;grid-template-columns:1fr 72px;align-items:center;height:28px;margin:0 0 8px;padding:0 8px 0 38px;color:var(--tjy-muted);font-size:12px}.tjy-edit-screen .tjy-dish-labels span:last-child{text-align:center}.tjy-edit-screen .tjy-dish-row{grid-template-columns:28px 30px 1fr 28px 28px;min-height:70px;margin:0 0 12px;padding:0 16px;border:1px solid var(--tjy-line);border-radius:7px;background:#fff}.tjy-edit-screen .tjy-dish-row.selected{border-color:var(--tjy-line);box-shadow:none}.tjy-edit-screen .tjy-dish-row input{font-size:16px}.tjy-edit-screen .tjy-row-edit,.tjy-edit-screen .tjy-icon-button{width:28px;height:36px;padding:0;border:0;background:transparent;border-radius:6px;color:#555;display:flex;align-items:center;justify-content:center;cursor:pointer}.tjy-edit-screen .tjy-row-edit:hover,.tjy-edit-screen .tjy-icon-button:hover{background:#f1f1ef;color:#171717}.tjy-edit-screen .tjy-row-edit svg,.tjy-edit-screen .tjy-icon-button svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}.tjy-edit-screen .tjy-drag-handle{font-size:17px;color:#666}.tjy-edit-screen .tjy-selected-dish{margin:0 0 22px}.tjy-edit-screen .tjy-selected-dish strong{font-size:17px}.tjy-edit-screen .tjy-selected-dish span{font-size:14px}.tjy-ingredient-table{border:1px solid var(--tjy-line);border-radius:8px;overflow:hidden}.tjy-edit-screen .tjy-ingredient-labels{height:53px;padding:0;display:grid;grid-template-columns:minmax(130px,1fr) 105px 105px 64px;align-items:center;border:0;border-radius:0;background:#fff}.tjy-edit-screen .tjy-ingredient-labels span{padding:0 15px;font-size:12px}.tjy-edit-screen .tjy-ingredient-labels span:last-child{padding:0;text-align:center;white-space:nowrap}.tjy-edit-screen .tjy-ingredient-row{height:66px;padding:0 8px;grid-template-columns:minmax(130px,1fr) 105px 105px 56px;border:0;border-top:1px solid var(--tjy-line);border-radius:0}.tjy-edit-screen .tjy-ingredient-row>.tjy-icon-button{justify-self:center}.tjy-edit-screen .tjy-ingredient-row input,.tjy-edit-screen .tjy-ingredient-row select{height:39px;padding:0 10px;border:1px solid transparent;border-radius:5px;font-size:15px}.tjy-edit-screen .tjy-ingredient-row input:first-child{border-color:transparent}.tjy-edit-screen .tjy-ingredient-row input:nth-child(2),.tjy-edit-screen .tjy-ingredient-row select{border-color:var(--tjy-line);background:#fff}.tjy-edit-screen .tjy-ingredient-row select{appearance:auto}.tjy-add-ingredient-secondary{height:40px!important;margin-top:18px;padding:0 14px!important;border-radius:6px!important;font-weight:500!important}.tjy-edit-screen .tjy-nutrition{margin-top:34px}.tjy-edit-screen .tjy-nutrition h3{font-size:17px;margin:0 0 17px}.tjy-edit-screen .tjy-nutrition-grid{grid-template-columns:repeat(4,1fr);border-radius:8px}.tjy-edit-screen .tjy-nutrition-grid>div{min-height:86px;padding:16px 18px}.tjy-edit-screen .tjy-nutrition-grid span{font-size:12px}.tjy-edit-screen .tjy-nutrition-grid strong{font-size:16px;margin-top:8px}.tjy-edit-screen .tjy-nutrition p{margin-top:16px!important;font-size:12px!important}
`;
