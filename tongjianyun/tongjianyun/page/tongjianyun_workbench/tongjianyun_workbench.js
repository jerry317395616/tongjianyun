frappe.pages["tongjianyun-workbench"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "业务工作台",
        single_column: true,
    });
    new TongjianyunOperationsWorkbench(page);
};

class TongjianyunOperationsWorkbench {
    constructor(page) {
        this.page = page;
        this.main = $('<div class="tjy-ops-app"></div>').appendTo(page.main);
        this.installStyles();
        this.page.set_primary_action("编制食谱", () => this.openRoute("Page", "tongjianyun-recipe-workbench"));
        this.page.add_menu_item("刷新工作台", () => this.load());
        this.page.add_inner_button("上传学生名单", () => this.uploadRoster());
        this.page.add_inner_button("园区数字孪生", () => { window.location.href = "/tongjianyun-campus"; });
        if (frappe.session.user === "Administrator" || frappe.user.has_role("Tongjianyun Health Manager")) {
            this.page.add_inner_button("幼儿健康登记", () => frappe.require("/assets/tongjianyun/js/health_registration.js?v=1", () => window.tjyOpenHealthRegistration()));
        }
        this.page.add_menu_item("周食谱营养分析", () => this.openRoute("Page", "weekly-recipe-nutrition-sheet"));
        this.page.add_menu_item("食材营养统计", () => this.openRoute("Report", "Ingredient Nutrition Statistics"));
        this.page.add_menu_item("营养计算规则", () => this.openRoute("DocType", "Tongjianyun Nutrition Rule Set"));
        this.load();
    }

    uploadRoster() {
        const esc = value => frappe.utils.escape_html(String(value ?? ""));
        let token = null;
        let timer = null;
        let closed = false;
        let busy = false;
        const dialog = new frappe.ui.Dialog({title: "上传学生名单", size: "extra-large", fields: [
            {fieldtype: "HTML", options: "<p>支持 Excel / CSV，无需套模板。系统先预览，确认后才写入。不会删除学生、覆盖已有资料或自动转班。</p>"},
            {fieldtype: "Link", fieldname: "fallback", label: "名单未写班级时统一加入（选填）", options: "Student Group", get_query: () => ({filters: {disabled: 0}})},
            {fieldtype: "Check", fieldname: "auto_age", label: "无班级时按年龄生成分班建议", default: 0, description: "按当前学年9月1日满3岁小班、4岁中班、5—6岁大班；仅匹配当前学年已有同名班级。预览后确认，不转班。"},
            {fieldtype: "Button", fieldname: "upload", label: "选择名单文件", click: () => {
                if (busy) return;
                new frappe.ui.FileUploader({make_attachments_public: false, restrictions: {allowed_file_types: [".xlsx", ".xls", ".csv"], max_file_size: 5 * 1024 * 1024, max_number_of_files: 1}, on_success: async file => {
                    if (closed) return;
                    busy = true;
                    box().text("已上传，正在安排识别…");
                    try {
                        const response = await frappe.call({method: "tongjianyun.student_roster_upload.start", args: {file: file.name, fallback_group: dialog.get_value("fallback") || "", auto_age: dialog.get_value("auto_age") || 0}});
                        token = response.message.token;
                        sessionStorage.setItem(storageKey, token);
                        await poll();
                    } catch (error) { showError(error); busy = false; }
                }});
            }},
            {fieldtype: "HTML", fieldname: "progress"}
        ], primary_action_label: "确认导入预览中的学生", primary_action: async () => {
            if (!token || busy) return;
            busy = true;
            dialog.get_primary_btn().prop("disabled", true);
            try {
                await frappe.call({method: "tongjianyun.student_roster_upload.confirm", args: {token}});
                await poll();
            } catch (error) { showError(error); busy = false; }
        }});
        const storageKey = `tjy-roster-task:${frappe.session.user}`;
        const box = () => dialog.fields_dict.progress.$wrapper;
        const showError = error => box().text(error?.message || "操作失败，请检查提示后重试。");
        const poll = async () => {
            clearTimeout(timer);
            if (closed || !token) return;
            try {
                const response = await frappe.call({method: "tongjianyun.student_roster_upload.status", args: {token}});
                if (closed) return;
                const data = response.message;
                busy = ["queued", "running", "importing"].includes(data.status);
                dialog.get_primary_btn().prop("disabled", data.status !== "preview" || !data.rows.length);
                const labels = {create: "新增", add_to_group: "加入班级", unchanged: "保持不变"};
                let html = `<p role="status">${esc(data.message)}</p>`;
                if (data.status === "preview") {
                    html += `<p>新增 ${data.counts.create || 0} 人；已有学生加入班级 ${data.counts.add_to_group || 0} 人；保持不变 ${data.counts.unchanged || 0} 人；待核对 ${(data.errors || []).length} 项。</p>`;
                    html += `<details><summary>查看字段识别依据</summary>${(data.mappings || []).map(m => `<p>${esc(m.sheet)} 第${m.header}行表头（${m.ai ? "AI辅助识别，请核对" : "规则识别"}）：${esc(m.fields.join("；"))}</p>`).join("")}</details>`;
                    html += `<div style="max-height:300px;overflow:auto"><table class="table table-bordered"><thead><tr><th>来源</th><th>姓名</th><th>操作</th><th>班级</th><th>依据</th></tr></thead><tbody>${data.rows.map(r => `<tr><td>${esc(r.sheet)}:${r.row}</td><td>${esc(r.name)}</td><td>${esc(labels[r.action])}</td><td>${esc(r.group)}</td><td>${esc(r.basis)}</td></tr>`).join("")}</tbody></table></div>`;
                }
                if (data.errors?.length) html += `<details open><summary>待核对 ${data.errors.length} 项（本次不导入）</summary><div style="max-height:180px;overflow:auto">${data.errors.map(r => `<p>${esc(r.sheet)} 第${r.row}行 ${esc(r.name)}：${esc(r.reason)}</p>`).join("")}</div><p>修正原文件后重新上传，已导入学生会再次核对，不重复创建。</p></details>`;
                if (data.result) html += `<p>已新增 ${data.result.created} 人，加入班级 ${data.result.added_to_group} 人，保持不变 ${data.result.unchanged} 人。结果摘要已记录在上传文件的评论中。</p>`;
                box().html(html);
                if (busy) timer = setTimeout(poll, 2000);
                if (data.status === "completed") this.load();
            } catch (error) {
                busy = false;
                showError(error);
                box().append($('<button class="btn btn-default">重新读取任务状态</button>').on('click', poll));
            }
        };
        dialog.$wrapper.on("hidden.bs.modal", () => {closed = true; clearTimeout(timer);});
        dialog.show();
        dialog.get_primary_btn().prop("disabled", true);
        token = sessionStorage.getItem(storageKey);
        if (token) poll();
    }

    async load() {
        this.main.html(this.loadingView());
        try {
            const response = await frappe.call({
                method: "tongjianyun.workbench.get_overview",
                freeze: false,
            });
            this.state = response.message || {};
            this.render();
        } catch (error) {
            this.main.html(this.errorView(error));
            this.main.find("[data-retry]").on("click", () => this.load());
        }
    }

    render() {
        const state = this.state || {};
        const metrics = state.metrics || [];
        const steps = state.steps || [];
        const alerts = state.alerts || [];
        const next = state.next_step || {};
        const support = state.supporting || {};
        const recipe = state.recipe || null;
        const secondaryAction = next.secondary_action || {
            label: "查看营养分析",
            route_type: "Page",
            route: "weekly-recipe-nutrition-sheet",
        };
        const doneCount = Number(support.done_count || steps.filter((step) => step.status === "done").length);
        const progress = steps.length ? Math.round((doneCount / steps.length) * 100) : 0;
        const attentionCount = Number(support.attention_count || steps.filter((step) => step.status === "attention").length);
        const displayName = this.getDisplayName();
        const statusText = attentionCount ? attentionCount + " 个环节需要处理" : "关键业务运行正常";

        if (state.setup_required) {
            this.page.set_primary_action("补全基础资料", () => this.openRoute(next.route_type, next.route));
        } else {
            this.page.set_primary_action("编制食谱", () => this.openRoute("Page", "tongjianyun-recipe-workbench"));
        }

        this.main.html([
            '<main class="tjy-ops-shell">',
                '<header class="tjy-welcome">',
                    '<div class="tjy-welcome-copy">',
                        '<div class="tjy-product-label"><span></span>童健云 · 园所膳食运营中心</div>',
                        '<h1>' + escapeHtml(this.getGreeting()) + '，' + escapeHtml(displayName) + '</h1>',
                        '<p>' + escapeHtml(state.date_label || "今日") + ' · 从人数确认到食安追溯，掌握今天每一个关键环节。</p>',
                    '</div>',
                    '<div class="tjy-welcome-tools">',
                        '<button class="tjy-refresh-button" type="button" data-refresh>' + icon("refresh") + '<span>刷新数据</span></button>',
                        '<div class="tjy-health-pill ' + (attentionCount ? "is-warning" : "is-healthy") + '">',
                            '<i></i><span>' + escapeHtml(statusText) + '</span>',
                        '</div>',
                    '</div>',
                '</header>',

                '<section class="tjy-command-card">',
                    '<div class="tjy-command-copy">',
                        '<div class="tjy-command-kicker"><span>' + escapeHtml(next.kicker || "今日首要任务") + '</span><em class="tjy-status tjy-status-' + escapeHtml(next.status || "pending") + '">' + escapeHtml(next.status_label || "待处理") + '</em></div>',
                        '<h2>' + escapeHtml(next.title || "开始今日业务") + '</h2>',
                        '<p>' + escapeHtml(next.description || "按业务流程完成今日园所膳食工作。") + '</p>',
                        '<div class="tjy-command-actions">',
                            '<button class="tjy-command-primary" type="button" data-route-type="' + escapeHtml(next.route_type || "") + '" data-route="' + escapeHtml(next.route || "") + '">',
                                '<span>' + escapeHtml(next.action_label || "立即处理") + '</span>' + icon("arrow"),
                            '</button>',
                            '<button class="tjy-command-secondary" type="button" data-route-type="' + escapeHtml(secondaryAction.route_type || "") + '" data-route="' + escapeHtml(secondaryAction.route || "") + '">' + escapeHtml(secondaryAction.label || "查看营养分析") + '</button>',
                        '</div>',
                    '</div>',
                    '<div class="tjy-command-progress">',
                        '<div class="tjy-progress-ring" style="--progress:' + progress + '">',
                            '<div><strong>' + progress + '%</strong><span>' + (state.setup_required ? "启用进度" : "今日流程") + '</span></div>',
                        '</div>',
                        '<div class="tjy-progress-detail">',
                            '<span><b>' + doneCount + '</b> / ' + steps.length + ' 环节完成</span>',
                            '<small>' + (attentionCount ? attentionCount + ' 个环节需要优先处理' : '继续保持，运行状态良好') + '</small>',
                        '</div>',
                    '</div>',
                '</section>',

                '<section class="tjy-metric-grid">',
                    metrics.map((item, index) => this.renderMetric(item, index)).join(""),
                '</section>',

                '<section class="tjy-overview-grid">',
                    '<article class="tjy-panel tjy-week-panel">',
                        '<div class="tjy-panel-heading">',
                            '<div><span class="tjy-section-label">本周计划</span><h2>膳食安排</h2></div>',
                            '<button type="button" class="tjy-text-action" data-route-type="Page" data-route="tongjianyun-recipe-workbench">打开食谱' + icon("arrow") + '</button>',
                        '</div>',
                        this.renderRecipe(recipe),
                        '<div class="tjy-data-strip">',
                            this.renderDataPoint("菜品", support.dish_count, "道"),
                            this.renderDataPoint("采购任务", support.purchase_count, "项"),
                            this.renderDataPoint("待采购", support.purchase_open, "项"),
                            this.renderDataPoint("班级", support.group_count, "个"),
                        '</div>',
                    '</article>',

                    '<article class="tjy-panel tjy-alert-panel">',
                        '<div class="tjy-panel-heading">',
                            '<div><span class="tjy-section-label">今日关注</span><h2>待办与风险</h2></div>',
                            '<span class="tjy-panel-count">' + alerts.length + '</span>',
                        '</div>',
                        '<div class="tjy-alert-list">',
                            alerts.map((item) => this.renderAlert(item)).join(""),
                        '</div>',
                    '</article>',
                '</section>',

                '<section class="tjy-panel tjy-flow-panel">',
                    '<div class="tjy-panel-heading tjy-flow-heading">',
                        '<div><span class="tjy-section-label">每日闭环</span><h2>膳食业务流程</h2></div>',
                        '<p>先完善班级和学生资料，再依次完成就餐确认、食谱与采购，所有关键动作都有据可查。</p>',
                    '</div>',
                    '<div class="tjy-flow-track">',
                        steps.map((step, index) => this.renderFlowStep(step, index)).join(""),
                    '</div>',
                '</section>',

                '<section class="tjy-quick-section">',
                    '<div class="tjy-section-heading">',
                        '<div><span class="tjy-section-label">快捷入口</span><h2>常用业务</h2></div>',
                        '<p>直接进入最常用的童健云功能。</p>',
                    '</div>',
                    '<div class="tjy-action-grid">',
                        this.quickActions().map((item) => this.renderQuickAction(item)).join(""),
                    '</div>',
                '</section>',

                '<footer class="tjy-footer-note">',
                    '<span>数据更新于 ' + escapeHtml(this.formatGeneratedAt(state.generated_at)) + '</span>',
                    '<span>童健云 · 让园所膳食管理更安心、更清晰</span>',
                '</footer>',
            '</main>',
        ].join(""));

        this.bindEvents();
    }

    renderMetric(item, index) {
        const icons = ["users", "meal", "recipe", "shield"];
        const tones = ["green", "blue", "amber", Number(item.value || 0) ? "red" : "green"];
        return [
            '<article class="tjy-metric-card tjy-tone-' + tones[index % tones.length] + '">',
                '<div class="tjy-metric-top">',
                    '<span>' + escapeHtml(item.label || "") + '</span>',
                    '<i>' + icon(icons[index % icons.length]) + '</i>',
                '</div>',
                '<div class="tjy-metric-value"><strong>' + Number(item.value || 0).toLocaleString() + '</strong><em>' + escapeHtml(item.suffix || "") + '</em></div>',
                '<small>' + escapeHtml(item.hint || "") + '</small>',
                item.label === "在园幼儿" ? '<button type="button" class="btn btn-xs btn-default" style="float:right" data-upload-roster>上传学生名单</button>' : '',
            '</article>',
        ].join("");
    }

    renderRecipe(recipe) {
        if (!recipe) {
            return [
                '<div class="tjy-recipe-empty">',
                    '<div class="tjy-empty-icon">' + icon("recipe") + '</div>',
                    '<div><h3>本周食谱尚未建立</h3><p>创建或导入本周食谱，后续营养分析和采购任务将以此为依据。</p></div>',
                    '<button type="button" data-route-type="Page" data-route="tongjianyun-recipe-workbench">开始编制</button>',
                '</div>',
            ].join("");
        }
        const weekStart = this.formatDate(recipe.week_start);
        const weekEnd = this.formatDate(recipe.week_end);
        const title = recipe.title || recipe.recipe_id || "本周食谱";
        return [
            '<div class="tjy-recipe-card">',
                '<div class="tjy-recipe-icon">' + icon("recipe") + '</div>',
                '<div class="tjy-recipe-copy">',
                    '<span>' + escapeHtml(weekStart + " — " + weekEnd) + '</span>',
                    '<h3>' + escapeHtml(title) + '</h3>',
                    '<p><b>' + Number(recipe.dish_count || 0) + '</b> 道菜品已纳入本周计划，可继续进行营养分析与采购执行。</p>',
                '</div>',
                '<div class="tjy-recipe-actions">',
                    '<button type="button" data-route-type="Page" data-route="weekly-recipe-nutrition-sheet">营养分析</button>',
                    '<button type="button" data-route-type="Page" data-route="tongjianyun-recipe-workbench">编辑食谱</button>',
                '</div>',
            '</div>',
        ].join("");
    }

    renderDataPoint(label, value, suffix) {
        return [
            '<div class="tjy-data-point">',
                '<span>' + escapeHtml(label) + '</span>',
                '<strong>' + Number(value || 0).toLocaleString() + '<em>' + escapeHtml(suffix) + '</em></strong>',
            '</div>',
        ].join("");
    }

    renderAlert(item) {
        const tone = item.tone || "info";
        const toneIcon = tone === "danger" ? "alert" : tone === "warning" ? "clock" : tone === "success" ? "check" : "heart";
        return [
            '<button type="button" class="tjy-alert-item is-' + escapeHtml(tone) + '" data-route-type="' + escapeHtml(item.route_type || "") + '" data-route="' + escapeHtml(item.route || "") + '">',
                '<i>' + icon(toneIcon) + '</i>',
                '<span><strong>' + escapeHtml(item.title || "") + '</strong><small>' + escapeHtml(item.description || "") + '</small></span>',
                icon("arrow"),
            '</button>',
        ].join("");
    }

    renderFlowStep(step, index) {
        const statusIcon = step.status === "done" ? icon("check") : step.status === "attention" ? icon("alert") : String(index + 1).padStart(2, "0");
        return [
            '<button type="button" class="tjy-flow-step is-' + escapeHtml(step.status || "pending") + '" data-route-type="' + escapeHtml(step.route_type || "") + '" data-route="' + escapeHtml(step.route || "") + '">',
                '<div class="tjy-flow-number">' + statusIcon + '</div>',
                '<div class="tjy-flow-copy">',
                    '<span>' + escapeHtml(step.status_label || "") + '</span>',
                    '<strong>' + escapeHtml(step.title || "") + '</strong>',
                    '<small>' + escapeHtml(step.action_label || "打开") + '</small>',
                '</div>',
                icon("arrow"),
            '</button>',
        ].join("");
    }

    quickActions() {
        return [
            { icon: "meal", tone: "green", title: "今日出勤", hint: "记录幼儿出勤状态，确认备餐", type: "Page", route: "meal-attendance-teacher" },
            { icon: "meal", tone: "amber", title: "今日备餐", hint: "查看用餐人数，确认备餐完成", type: "Page", route: "meal-kitchen-dashboard" },
            { icon: "chart", tone: "violet", title: "周食谱营养分析", hint: "查看带量食谱与营养评价", type: "Page", route: "weekly-recipe-nutrition-sheet" },
            { icon: "chart", tone: "green", title: "食材营养统计", hint: "按食材查看全部营养指标贡献", type: "Report", route: "Ingredient Nutrition Statistics" },
            { icon: "chart", tone: "cyan", title: "营养计算规则", hint: "版本化维护营养公式、阈值与供能目标", type: "DocType", route: "Tongjianyun Nutrition Rule Set" },
            { icon: "supplier", tone: "cyan", title: "班级管理", hint: "维护班级、学年与在班幼儿", type: "DocType", route: "Student Group" },
            { icon: "meal", tone: "rose", title: "就餐调整记录", hint: "记录临时停餐与餐次调整", type: "DocType", route: "Tongjianyun Daily Meal Adjustment" },
            { icon: "users", tone: "orange", title: "幼儿档案", hint: "维护幼儿基础信息与入园状态", type: "DocType", route: "Student" },
            { icon: "users", tone: "red", title: "教职工档案", hint: "维护教师与教职工基础信息", type: "DocType", route: "Instructor" },
        ];
    }

    renderQuickAction(item) {
        return [
            '<button type="button" class="tjy-quick-action tjy-action-' + escapeHtml(item.tone) + '" data-route-type="' + escapeHtml(item.type) + '" data-route="' + escapeHtml(item.route) + '">',
                '<i>' + icon(item.icon) + '</i>',
                '<span><strong>' + escapeHtml(item.title) + '</strong><small>' + escapeHtml(item.hint) + '</small></span>',
                icon("arrow"),
            '</button>',
        ].join("");
    }

    bindEvents() {
        this.main.find("[data-upload-roster]").on("click", () => this.uploadRoster());
        this.main.find("[data-route]").on("click", (event) => {
            const target = $(event.currentTarget);
            this.openRoute(target.attr("data-route-type"), target.attr("data-route"));
        });
        this.main.find("[data-refresh]").on("click", () => this.load());
    }

    openRoute(routeType, route) {
        if (!route) return;
        if (routeType === "Page") {
            frappe.set_route(route);
            return;
        }
        if (routeType === "Report") {
            frappe.set_route("query-report", route);
            return;
        }
        frappe.set_route("List", route, "List");
    }

    getDisplayName() {
        const bootName = frappe.boot && frappe.boot.user ? frappe.boot.user.full_name : "";
        if (bootName) return bootName;
        if (frappe.session && frappe.session.user === "Administrator") return "管理员";
        return frappe.session && frappe.session.user ? frappe.session.user.split("@")[0] : "您好";
    }

    getGreeting() {
        const hour = new Date().getHours();
        if (hour < 6) return "夜深了";
        if (hour < 11) return "上午好";
        if (hour < 14) return "中午好";
        if (hour < 18) return "下午好";
        return "晚上好";
    }

    formatDate(value) {
        if (!value) return "日期待定";
        const text = String(value).slice(0, 10);
        const parts = text.split("-");
        if (parts.length !== 3) return text;
        return Number(parts[1]) + "月" + Number(parts[2]) + "日";
    }

    formatGeneratedAt(value) {
        if (!value) return "刚刚";
        const text = String(value).replace("T", " ");
        return text.slice(11, 16) || "刚刚";
    }

    loadingView() {
        return [
            '<main class="tjy-ops-shell tjy-is-loading">',
                '<div class="tjy-skeleton tjy-skeleton-title"></div>',
                '<div class="tjy-skeleton tjy-skeleton-hero"></div>',
                '<div class="tjy-loading-grid">',
                    '<div class="tjy-skeleton"></div><div class="tjy-skeleton"></div><div class="tjy-skeleton"></div><div class="tjy-skeleton"></div>',
                '</div>',
                '<p>正在汇总今日园所膳食数据...</p>',
            '</main>',
        ].join("");
    }

    errorView(error) {
        return [
            '<div class="tjy-state-card">',
                '<div class="tjy-state-icon">' + icon("alert") + '</div>',
                '<h2>工作台暂时无法加载</h2>',
                '<p>' + escapeHtml(error && error.message ? error.message : "请稍后刷新页面") + '</p>',
                '<button type="button" data-retry>重新加载</button>',
            '</div>',
        ].join("");
    }

    installStyles() {
        $("#tjy-operations-styles").remove();
        $("<style>", { id: "tjy-operations-styles", text: WORKBENCH_STYLES }).appendTo(document.head);
    }
}

function escapeHtml(value) {
    return $("<div>").text(value == null ? "" : String(value)).html();
}

function icon(name) {
    const paths = {
        refresh: '<path d="M20 6v5h-5"/><path d="M19 11a7 7 0 1 0 .5 5"/>',
        arrow: '<path d="M5 12h14"/><path d="m14 7 5 5-5 5"/>',
        users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
        meal: '<path d="M4 11h16a8 8 0 0 1-16 0Z"/><path d="M8 7c0-2 1-2 1-4"/><path d="M12 7c0-2 1-2 1-4"/><path d="M16 7c0-2 1-2 1-4"/>',
        heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0-.1-7.8Z"/>',
        shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/>',
        recipe: '<path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2Z"/><path d="M8 7h8M8 11h6"/>',
        chart: '<path d="M3 3v18h18"/><path d="m7 16 4-5 3 3 5-7"/>',
        cart: '<circle cx="9" cy="20" r="1"/><circle cx="18" cy="20" r="1"/><path d="M2 3h3l2.7 11.4a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 2-1.6L21 7H6"/>',
        supplier: '<path d="M3 21h18"/><path d="M5 21V8l7-5 7 5v13"/><path d="M9 21v-6h6v6"/><path d="M8 10h.01M12 10h.01M16 10h.01"/>',
        sample: '<path d="M9 2h6"/><path d="M10 2v6l-5 9a3 3 0 0 0 2.6 4.5h8.8A3 3 0 0 0 19 17l-5-9V2"/><path d="M7.5 15h9"/>',
        alert: '<path d="M10.3 2.9 1.8 17a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 2.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
        clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
        check: '<path d="m5 12 4 4L19 6"/>',
    };
    return '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + (paths[name] || paths.check) + '</svg>';
}

const WORKBENCH_STYLES = [
    '.page-container[data-page-route="tongjianyun-workbench"] .layout-main-section{max-width:none;padding:0;background:#f4f7f5}',
    '.page-container[data-page-route="tongjianyun-workbench"] .page-body{background:#f4f7f5}',
    '.page-container[data-page-route="tongjianyun-workbench"] .page-head{border-bottom-color:#e6ebe7}',
    '.tjy-ops-app{--ink:#14231d;--muted:#6f7d76;--line:#e2e8e4;--soft:#f4f7f5;--green:#19875f;--green-dark:#123f32;--green-soft:#e7f5ee;--amber:#bb7115;--amber-soft:#fff3df;--red:#c75252;--red-soft:#ffeded;--blue:#3979a8;--blue-soft:#eaf3fb;color:var(--ink);font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}',
    '.tjy-ops-app *{box-sizing:border-box}',
    '.tjy-ops-app button{font-family:inherit}',
    '.tjy-ops-app svg{display:block;width:18px;height:18px}',
    '.tjy-ops-shell{max-width:1440px;margin:0 auto;padding:30px 36px 62px}',
    '.tjy-welcome{display:flex;align-items:center;justify-content:space-between;gap:28px;margin-bottom:22px}',
    '.tjy-product-label{display:flex;align-items:center;gap:8px;margin-bottom:8px;color:#5d6f67;font-size:12px;font-weight:700;letter-spacing:.045em}',
    '.tjy-product-label span{width:7px;height:7px;border-radius:99px;background:#20a875;box-shadow:0 0 0 5px rgba(32,168,117,.11)}',
    '.tjy-welcome h1{margin:0 0 7px;font-size:29px;line-height:1.18;letter-spacing:-.035em;color:var(--ink);font-weight:750}',
    '.tjy-welcome p{margin:0;color:var(--muted);font-size:13px}',
    '.tjy-welcome-tools{display:flex;align-items:center;gap:10px}',
    '.tjy-refresh-button{display:flex;align-items:center;gap:7px;height:36px;padding:0 12px;border:1px solid var(--line);border-radius:10px;background:#fff;color:#4f6058;font-size:12px;font-weight:600;transition:.2s}',
    '.tjy-refresh-button:hover{border-color:#b9c9c0;background:#fafcfb}',
    '.tjy-refresh-button svg{width:14px;height:14px}',
    '.tjy-health-pill{display:flex;align-items:center;gap:8px;height:36px;padding:0 13px;border-radius:99px;font-size:12px;font-weight:650}',
    '.tjy-health-pill i{width:7px;height:7px;border-radius:50%}',
    '.tjy-health-pill.is-healthy{background:var(--green-soft);color:#176e50}.tjy-health-pill.is-healthy i{background:#1aa773;box-shadow:0 0 0 4px rgba(26,167,115,.12)}',
    '.tjy-health-pill.is-warning{background:var(--amber-soft);color:#8d5b16}.tjy-health-pill.is-warning i{background:#d78a21;box-shadow:0 0 0 4px rgba(215,138,33,.12)}',
    '.tjy-command-card{position:relative;overflow:hidden;display:grid;grid-template-columns:minmax(0,1.5fr) minmax(300px,.65fr);gap:42px;align-items:center;min-height:232px;padding:34px 40px;border-radius:22px;background:#123f32;color:#fff;box-shadow:0 16px 36px rgba(22,70,55,.13)}',
    '.tjy-command-card:after{content:"";position:absolute;width:360px;height:360px;border-radius:50%;right:-125px;top:-195px;border:76px solid rgba(255,255,255,.035);pointer-events:none}',
    '.tjy-command-copy{position:relative;z-index:1}',
    '.tjy-command-kicker{display:flex;align-items:center;gap:10px;margin-bottom:14px}',
    '.tjy-command-kicker>span{font-size:11px;font-weight:750;letter-spacing:.1em;color:#9ee0c7}',
    '.tjy-status{display:inline-flex;align-items:center;padding:4px 9px;border-radius:99px;font-size:10px;font-style:normal;font-weight:700}',
    '.tjy-command-card .tjy-status-done{background:rgba(106,218,174,.17);color:#b5ecd7}.tjy-command-card .tjy-status-pending{background:rgba(255,255,255,.11);color:#dce9e4}.tjy-command-card .tjy-status-attention{background:rgba(255,193,100,.17);color:#ffd89c}',
    '.tjy-command-copy h2{max-width:740px;margin:0 0 9px;font-size:27px;line-height:1.28;font-weight:750;letter-spacing:-.025em;color:#fff}',
    '.tjy-command-copy p{max-width:750px;margin:0;color:#bbd0c8;font-size:13px;line-height:1.75}',
    '.tjy-command-actions{display:flex;align-items:center;gap:10px;margin-top:22px}',
    '.tjy-command-actions button{height:40px;border-radius:10px;padding:0 15px;font-size:12px;font-weight:700;transition:.2s}',
    '.tjy-command-primary{display:flex;align-items:center;gap:22px;border:0;background:#fff;color:#173e33}.tjy-command-primary svg{width:15px;height:15px}.tjy-command-primary:hover{background:#ecf9f4;transform:translateY(-1px)}',
    '.tjy-command-secondary{border:1px solid rgba(255,255,255,.2);background:rgba(255,255,255,.06);color:#eaf6f1}.tjy-command-secondary:hover{background:rgba(255,255,255,.12)}',
    '.tjy-command-progress{position:relative;z-index:1;display:flex;align-items:center;justify-content:flex-end;gap:18px;padding-left:32px;border-left:1px solid rgba(255,255,255,.12)}',
    '.tjy-progress-ring{width:102px;height:102px;flex:0 0 auto;padding:7px;border-radius:50%;background:conic-gradient(#6ed5ad calc(var(--progress) * 1%),rgba(255,255,255,.12) 0)}',
    '.tjy-progress-ring>div{display:flex;width:100%;height:100%;align-items:center;justify-content:center;flex-direction:column;border-radius:50%;background:#123f32}',
    '.tjy-progress-ring strong{font-size:22px;color:#fff}.tjy-progress-ring span{margin-top:1px;font-size:10px;color:#9dbbb0}',
    '.tjy-progress-detail span,.tjy-progress-detail small{display:block}.tjy-progress-detail span{font-size:12px;color:#d6e6e0}.tjy-progress-detail b{font-size:22px;color:#fff}.tjy-progress-detail small{max-width:125px;margin-top:5px;color:#8fb0a4;font-size:10px;line-height:1.45}',
    '.tjy-metric-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px;margin:16px 0}',
    '.tjy-metric-card{position:relative;overflow:hidden;min-height:132px;padding:18px 19px;border:1px solid var(--line);border-radius:16px;background:#fff;transition:transform .2s,border-color .2s,box-shadow .2s}',
    '.tjy-metric-card:hover{transform:translateY(-2px);border-color:#ccd8d1;box-shadow:0 10px 26px rgba(32,64,50,.06)}',
    '.tjy-metric-top{display:flex;align-items:center;justify-content:space-between;gap:12px;color:var(--muted);font-size:12px;font-weight:650}',
    '.tjy-metric-top i{display:grid;place-items:center;width:31px;height:31px;border-radius:9px}.tjy-metric-top svg{width:16px;height:16px}',
    '.tjy-tone-green .tjy-metric-top i{background:#e8f6f0;color:#17835c}.tjy-tone-blue .tjy-metric-top i{background:#eaf3fb;color:#3979a8}.tjy-tone-amber .tjy-metric-top i{background:#fff3df;color:#b67318}.tjy-tone-red .tjy-metric-top i{background:#ffeded;color:#c75252}',
    '.tjy-metric-value{display:flex;align-items:baseline;gap:5px;margin:8px 0 5px}.tjy-metric-value strong{font-size:28px;line-height:1;font-weight:760;letter-spacing:-.03em}.tjy-metric-value em{font-size:11px;font-style:normal;color:var(--muted)}',
    '.tjy-metric-card small{display:block;overflow:hidden;color:#87928d;font-size:10px;white-space:nowrap;text-overflow:ellipsis}',
    '.tjy-overview-grid{display:grid;grid-template-columns:minmax(0,1.8fr) minmax(320px,.85fr);gap:16px;margin-bottom:16px}',
    '.tjy-panel{border:1px solid var(--line);border-radius:18px;background:#fff}',
    '.tjy-week-panel,.tjy-alert-panel{padding:22px}',
    '.tjy-panel-heading,.tjy-section-heading{display:flex;align-items:center;justify-content:space-between;gap:18px}',
    '.tjy-section-label{display:block;margin-bottom:4px;color:#3a8d6b;font-size:10px;font-weight:750;letter-spacing:.09em}',
    '.tjy-panel-heading h2,.tjy-section-heading h2{margin:0;color:var(--ink);font-size:18px;line-height:1.25;font-weight:730;letter-spacing:-.015em}',
    '.tjy-text-action{display:flex;align-items:center;gap:7px;padding:6px 0;border:0;background:transparent;color:#47705f;font-size:11px;font-weight:650}.tjy-text-action svg{width:14px;height:14px}',
    '.tjy-recipe-empty{display:grid;grid-template-columns:42px 1fr auto;align-items:center;gap:14px;min-height:114px;margin-top:17px;padding:16px;border:1px dashed #cedbd4;border-radius:13px;background:#f8faf9}',
    '.tjy-empty-icon,.tjy-recipe-icon{display:grid;place-items:center;width:42px;height:42px;border-radius:12px;background:var(--green-soft);color:#1b825e}',
    '.tjy-recipe-empty h3,.tjy-recipe-copy h3{margin:0 0 5px;font-size:14px;font-weight:700}.tjy-recipe-empty p,.tjy-recipe-copy p{margin:0;color:var(--muted);font-size:10.5px;line-height:1.55}',
    '.tjy-recipe-empty>button{padding:8px 11px;border:1px solid #c7d6ce;border-radius:8px;background:#fff;color:#245e49;font-size:11px;font-weight:650}',
    '.tjy-recipe-card{display:grid;grid-template-columns:48px 1fr auto;align-items:center;gap:15px;min-height:114px;margin-top:17px;padding:17px;border-radius:14px;background:#f3f8f5}',
    '.tjy-recipe-icon{width:48px;height:48px;background:#dff1e9}.tjy-recipe-icon svg{width:21px;height:21px}',
    '.tjy-recipe-copy>span{display:block;margin-bottom:4px;color:#40806a;font-size:10px;font-weight:700}.tjy-recipe-copy h3{max-width:620px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.tjy-recipe-copy p b{color:#245e49}',
    '.tjy-recipe-actions{display:flex;flex-direction:column;gap:6px}.tjy-recipe-actions button{min-width:74px;padding:7px 9px;border:1px solid #cad8d0;border-radius:8px;background:#fff;color:#315e4e;font-size:10px;font-weight:650}',
    '.tjy-data-strip{display:grid;grid-template-columns:repeat(4,1fr);margin-top:16px;border:1px solid #edf0ee;border-radius:12px}',
    '.tjy-data-point{padding:12px 14px}.tjy-data-point+.tjy-data-point{border-left:1px solid #edf0ee}.tjy-data-point span{display:block;color:#87938d;font-size:10px}.tjy-data-point strong{display:block;margin-top:3px;font-size:17px}.tjy-data-point em{margin-left:3px;color:#87938d;font-size:9px;font-style:normal;font-weight:500}',
    '.tjy-panel-count{display:grid;place-items:center;min-width:27px;height:27px;padding:0 7px;border-radius:9px;background:#f1f4f2;color:#6f7c76;font-size:11px;font-weight:700}',
    '.tjy-alert-list{display:flex;flex-direction:column;gap:8px;margin-top:17px}',
    '.tjy-alert-item{display:grid;grid-template-columns:31px 1fr 15px;align-items:center;gap:10px;width:100%;min-height:57px;padding:9px 10px;border:1px solid #edf0ee;border-radius:11px;background:#fff;text-align:left;transition:.18s}',
    '.tjy-alert-item:hover{border-color:#cfdad4;background:#fbfcfb;transform:translateX(2px)}',
    '.tjy-alert-item>i{display:grid;place-items:center;width:31px;height:31px;border-radius:9px}.tjy-alert-item>i svg{width:15px;height:15px}.tjy-alert-item>svg{width:13px;height:13px;color:#a4ada8}',
    '.tjy-alert-item span strong,.tjy-alert-item span small{display:block}.tjy-alert-item span strong{margin-bottom:2px;color:#26362f;font-size:11px;font-weight:680}.tjy-alert-item span small{display:-webkit-box;overflow:hidden;color:#87918c;font-size:9.5px;line-height:1.4;-webkit-box-orient:vertical;-webkit-line-clamp:1}',
    '.tjy-alert-item.is-danger>i{background:var(--red-soft);color:var(--red)}.tjy-alert-item.is-warning>i{background:var(--amber-soft);color:var(--amber)}.tjy-alert-item.is-info>i{background:var(--blue-soft);color:var(--blue)}.tjy-alert-item.is-success>i{background:var(--green-soft);color:var(--green)}',
    '.tjy-flow-panel{padding:22px;margin-bottom:20px}',
    '.tjy-flow-heading p,.tjy-section-heading p{margin:0;color:#87928d;font-size:10.5px}',
    '.tjy-flow-track{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:0;margin-top:18px;border:1px solid #e8ece9;border-radius:14px;overflow:hidden}',
    '.tjy-flow-step{position:relative;display:grid;grid-template-columns:34px 1fr 13px;align-items:center;gap:9px;min-width:0;min-height:86px;padding:13px 12px;border:0;background:#fff;text-align:left;transition:.18s}',
    '.tjy-flow-step+.tjy-flow-step{border-left:1px solid #e8ece9}.tjy-flow-step:hover{z-index:1;background:#f8faf9;box-shadow:0 0 0 1px #cad7d0}',
    '.tjy-flow-number{display:grid;place-items:center;width:32px;height:32px;border:1px solid #dce3df;border-radius:10px;background:#f6f8f7;color:#738179;font-size:10px;font-weight:750}.tjy-flow-number svg{width:15px;height:15px}',
    '.tjy-flow-step.is-done .tjy-flow-number{border-color:#c8eadb;background:var(--green-soft);color:var(--green)}.tjy-flow-step.is-attention .tjy-flow-number{border-color:#f1d6ad;background:var(--amber-soft);color:var(--amber)}',
    '.tjy-flow-copy{min-width:0}.tjy-flow-copy span,.tjy-flow-copy strong,.tjy-flow-copy small{display:block;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.tjy-flow-copy span{margin-bottom:2px;color:#8b9690;font-size:8.5px}.tjy-flow-copy strong{color:#26362f;font-size:10.5px}.tjy-flow-copy small{margin-top:3px;color:#618172;font-size:8.5px}.tjy-flow-step>svg{width:12px;height:12px;color:#adb5b1}',
    '.tjy-quick-section{padding:4px 1px 0}',
    '.tjy-section-heading{margin-bottom:13px}',
    '.tjy-action-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:11px}',
    '.tjy-quick-action{display:grid;grid-template-columns:38px 1fr 14px;align-items:center;gap:11px;min-width:0;min-height:74px;padding:13px;border:1px solid var(--line);border-radius:14px;background:#fff;text-align:left;transition:.2s}',
    '.tjy-quick-action:hover{transform:translateY(-2px);border-color:#cbd7d0;box-shadow:0 9px 24px rgba(34,67,53,.07)}',
    '.tjy-quick-action>i{display:grid;place-items:center;width:38px;height:38px;border-radius:11px}.tjy-quick-action>i svg{width:18px;height:18px}.tjy-quick-action>svg{width:13px;height:13px;color:#a5afa9}',
    '.tjy-quick-action span{min-width:0}.tjy-quick-action strong,.tjy-quick-action small{display:block;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}.tjy-quick-action strong{margin-bottom:3px;color:#26362f;font-size:11.5px}.tjy-quick-action small{color:#8a948f;font-size:9px}',
    '.tjy-action-green>i{background:#e7f5ee;color:#19875f}.tjy-action-blue>i{background:#eaf3fb;color:#3979a8}.tjy-action-violet>i{background:#f1edfb;color:#795bb2}.tjy-action-amber>i{background:#fff3df;color:#b87318}.tjy-action-cyan>i{background:#e5f5f5;color:#278484}.tjy-action-rose>i{background:#fcecf0;color:#bd5f77}.tjy-action-orange>i{background:#fff0e7;color:#bd6e3f}.tjy-action-red>i{background:#ffeded;color:#c75252}',
    '.tjy-footer-note{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-top:28px;padding-top:17px;border-top:1px solid #e0e6e2;color:#929b96;font-size:9.5px}',
    '.tjy-state-card{min-height:540px;display:flex;align-items:center;justify-content:center;flex-direction:column;padding:40px;color:var(--muted);text-align:center}.tjy-state-icon{display:grid;place-items:center;width:48px;height:48px;margin-bottom:14px;border-radius:14px;background:var(--amber-soft);color:var(--amber)}.tjy-state-card h2{margin:0 0 7px;color:var(--ink);font-size:18px}.tjy-state-card p{margin:0 0 17px;font-size:12px}.tjy-state-card button{padding:9px 14px;border:0;border-radius:9px;background:var(--green-dark);color:#fff;font-size:11px;font-weight:650}',
    '.tjy-is-loading{min-height:620px}.tjy-is-loading>p{text-align:center;color:#89958f;font-size:11px}.tjy-skeleton{min-height:100px;border-radius:15px;background:linear-gradient(90deg,#edf1ee 25%,#f6f8f7 38%,#edf1ee 63%);background-size:400% 100%;animation:tjyShimmer 1.25s infinite}.tjy-skeleton-title{width:310px;min-height:62px;margin-bottom:22px}.tjy-skeleton-hero{min-height:230px}.tjy-loading-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin:16px 0}.tjy-loading-grid .tjy-skeleton{min-height:130px}@keyframes tjyShimmer{0%{background-position:100% 0}100%{background-position:0 0}}',
    '@media(max-width:1150px){.tjy-ops-shell{padding:26px 24px 52px}.tjy-command-card{grid-template-columns:1.35fr .65fr;padding:30px}.tjy-overview-grid{grid-template-columns:minmax(0,1.45fr) minmax(300px,.85fr)}.tjy-action-grid{grid-template-columns:repeat(2,1fr)}.tjy-flow-track{grid-template-columns:repeat(3,1fr)}.tjy-flow-step+.tjy-flow-step{border-left:1px solid #e8ece9}.tjy-flow-step:nth-child(4){border-top:1px solid #e8ece9;border-left:0}.tjy-flow-step:nth-child(5){border-top:1px solid #e8ece9}}',
    '@media(max-width:850px){.tjy-welcome{align-items:flex-start}.tjy-welcome-tools{flex-direction:column;align-items:flex-end}.tjy-command-card{grid-template-columns:1fr;gap:25px}.tjy-command-progress{justify-content:flex-start;padding:22px 0 0;border-top:1px solid rgba(255,255,255,.12);border-left:0}.tjy-metric-grid{grid-template-columns:repeat(2,1fr)}.tjy-overview-grid{grid-template-columns:1fr}.tjy-flow-heading p{display:none}.tjy-data-strip{grid-template-columns:repeat(4,1fr)}}',
    '@media(max-width:600px){.tjy-ops-shell{padding:20px 14px 42px}.tjy-welcome{display:block}.tjy-welcome h1{font-size:24px}.tjy-welcome-tools{margin-top:15px;flex-direction:row;align-items:center;justify-content:space-between}.tjy-refresh-button span{display:none}.tjy-command-card{padding:25px 21px;border-radius:18px}.tjy-command-copy h2{font-size:22px}.tjy-command-actions{align-items:stretch;flex-direction:column}.tjy-command-actions button{justify-content:center}.tjy-command-progress{display:none}.tjy-metric-grid{gap:9px}.tjy-metric-card{min-height:119px;padding:15px}.tjy-metric-value strong{font-size:24px}.tjy-week-panel,.tjy-alert-panel,.tjy-flow-panel{padding:17px}.tjy-recipe-card,.tjy-recipe-empty{grid-template-columns:42px 1fr}.tjy-recipe-actions,.tjy-recipe-empty>button{grid-column:1/-1;flex-direction:row}.tjy-data-strip{grid-template-columns:repeat(2,1fr)}.tjy-data-point:nth-child(3){border-top:1px solid #edf0ee;border-left:0}.tjy-data-point:nth-child(4){border-top:1px solid #edf0ee}.tjy-flow-track{grid-template-columns:1fr}.tjy-flow-step+.tjy-flow-step,.tjy-flow-step:nth-child(4),.tjy-flow-step:nth-child(5){border-top:1px solid #e8ece9;border-left:0}.tjy-action-grid{grid-template-columns:1fr}.tjy-footer-note{align-items:flex-start;flex-direction:column}.tjy-loading-grid{grid-template-columns:repeat(2,1fr)}}',
].join("");
