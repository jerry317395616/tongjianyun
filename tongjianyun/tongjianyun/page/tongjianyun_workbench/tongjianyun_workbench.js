frappe.pages["tongjianyun-workbench"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "业务工作台",
        single_column: true,
    });
    new TongjianyunWorkflowWorkbench(page);
};

class TongjianyunWorkflowWorkbench {
    constructor(page) {
        this.page = page;
        this.main = $('<div class="tjy-workflow-app"></div>').appendTo(page.main);
        this.installStyles();
        this.page.set_primary_action("编制食谱", () => this.openRoute("Page", "tongjianyun-recipe-workbench"));
        this.page.add_menu_item("刷新工作台", () => this.load());
        this.load();
    }

    async load() {
        this.main.html(this.loadingView());
        try {
            const response = await frappe.call({ method: "tongjianyun.workbench.get_overview" });
            this.state = response.message || {};
            this.render();
        } catch (error) {
            this.main.html(`
                <div class="tjy-state-card">
                    <h2>工作台暂时无法加载</h2>
                    <p>${escapeHtml(error?.message || "请稍后刷新页面")}</p>
                    <button class="btn btn-primary" data-retry>重新加载</button>
                </div>
            `);
            this.main.find("[data-retry]").on("click", () => this.load());
        }
    }

    render() {
        const next = this.state.next_step || {};
        const metrics = this.state.metrics || [];
        const steps = this.state.steps || [];
        const doneCount = steps.filter((step) => step.status === "done").length;
        this.main.html(`
            <section class="tjy-dashboard">
                <header class="tjy-hero">
                    <div>
                        <div class="tjy-eyebrow">${escapeHtml(this.state.date_label || "今日")}</div>
                        <h1>童健云业务工作台</h1>
                        <p>从园务主数据、考勤就餐到健康膳食和食安追溯，按顺序完成每日闭环。</p>
                    </div>
                    <div class="tjy-progress-summary">
                        <strong>${doneCount}/${steps.length}</strong>
                        <span>环节已完成</span>
                    </div>
                </header>

                <section class="tjy-next-card ${next.status === "attention" ? "is-attention" : ""}">
                    <div class="tjy-next-marker">下一步</div>
                    <div class="tjy-next-copy">
                        <span class="tjy-status tjy-status-${escapeHtml(next.status || "pending")}">${escapeHtml(next.status_label || "待处理")}</span>
                        <h2>${escapeHtml(next.title || "开始本次业务流程")}</h2>
                        <p>${escapeHtml(next.description || "")}</p>
                    </div>
                    <button class="tjy-primary-action" data-route-type="${escapeHtml(next.route_type || "")}" data-route="${escapeHtml(next.route || "")}">
                        ${escapeHtml(next.action_label || "开始处理")}
                        <span>→</span>
                    </button>
                </section>

                <section class="tjy-metrics">
                    ${metrics.map((item) => `
                        <article class="tjy-metric-card">
                            <span>${escapeHtml(item.label)}</span>
                            <div><strong>${Number(item.value || 0).toLocaleString()}</strong><em>${escapeHtml(item.suffix || "")}</em></div>
                            <small>${escapeHtml(item.hint || "")}</small>
                        </article>
                    `).join("")}
                </section>

                <section class="tjy-process-section">
                    <div class="tjy-section-heading">
                        <div><span>业务流程</span><h2>从幼儿入园到每日供餐，一步一步完成</h2></div>
                        <p>Education 维护幼儿和班级，童健云承接健康、膳食与食安业务。</p>
                    </div>
                    <div class="tjy-step-list">
                        ${steps.map((step, index) => this.renderStep(step, index, steps.length)).join("")}
                    </div>
                </section>

                <section class="tjy-support-grid">
                    <button data-route-type="DocType" data-route="Tongjianyun Food Supplier">
                        <span class="tjy-support-icon">供</span>
                        <span><strong>供应商档案</strong><small>${Number(this.state.supporting?.supplier_count || 0)} 家供应商</small></span>
                        <em>→</em>
                    </button>
                    <button data-route-type="DocType" data-route="Tongjianyun Food Sample">
                        <span class="tjy-support-icon">样</span>
                        <span><strong>留样记录</strong><small>${Number(this.state.supporting?.sample_count || 0)} 条记录</small></span>
                        <em>→</em>
                    </button>
                    <button data-route-type="Page" data-route="tongjianyun-recipe-workbench">
                        <span class="tjy-support-icon">谱</span>
                        <span><strong>历史食谱</strong><small>查看、导入和维护食谱</small></span>
                        <em>→</em>
                    </button>
                </section>
            </section>
        `);
        this.main.find("[data-route]").on("click", (event) => {
            const target = $(event.currentTarget);
            this.openRoute(target.attr("data-route-type"), target.attr("data-route"));
        });
    }

    renderStep(step, index, length) {
        const icon = step.status === "done" ? "✓" : step.status === "attention" ? "!" : step.number;
        return `
            <article class="tjy-step tjy-step-${escapeHtml(step.status)}">
                <div class="tjy-step-rail">
                    <span>${escapeHtml(icon)}</span>
                    ${index < length - 1 ? '<i></i>' : ""}
                </div>
                <div class="tjy-step-copy">
                    <div><h3>${escapeHtml(step.title)}</h3><span class="tjy-status tjy-status-${escapeHtml(step.status)}">${escapeHtml(step.status_label)}</span></div>
                    <p>${escapeHtml(step.description)}</p>
                </div>
                <button data-route-type="${escapeHtml(step.route_type)}" data-route="${escapeHtml(step.route)}">${escapeHtml(step.action_label)}<span>→</span></button>
            </article>
        `;
    }

    openRoute(routeType, route) {
        if (!route) return;
        if (routeType === "Page") {
            frappe.set_route(route);
            return;
        }
        frappe.set_route("List", route, "List");
    }

    loadingView() {
        return `
            <div class="tjy-loading">
                <span></span><span></span><span></span>
                <p>正在整理今日业务流程...</p>
            </div>
        `;
    }

    installStyles() {
        if (document.getElementById("tjy-workflow-styles")) return;
        $("<style>", { id: "tjy-workflow-styles", text: WORKBENCH_STYLES }).appendTo(document.head);
    }
}

function escapeHtml(value) {
    return $("<div>").text(value == null ? "" : String(value)).html();
}

const WORKBENCH_STYLES = `
.page-container[data-page-route="tongjianyun-workbench"] .layout-main-section { max-width: none; padding: 0; }
.page-container[data-page-route="tongjianyun-workbench"] .page-body { background: #fff; }
.tjy-workflow-app { --ink:#171717; --muted:#6b6b6b; --line:#e8e8e5; --soft:#f7f7f5; --green:#18a86b; --green-soft:#eaf8f1; --amber:#c66c09; --amber-soft:#fff5e7; color:var(--ink); font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif; }
.tjy-dashboard { max-width:1280px; margin:0 auto; padding:34px 42px 64px; }
.tjy-hero { display:flex; justify-content:space-between; align-items:flex-start; gap:32px; margin-bottom:28px; }
.tjy-eyebrow { color:var(--muted); font-size:13px; font-weight:600; letter-spacing:.04em; margin-bottom:9px; }
.tjy-hero h1 { margin:0 0 10px; font-size:30px; line-height:1.2; letter-spacing:-.03em; }
.tjy-hero p { margin:0; color:var(--muted); font-size:15px; }
.tjy-progress-summary { min-width:118px; border-left:1px solid var(--line); padding-left:24px; }
.tjy-progress-summary strong { display:block; font-size:27px; }
.tjy-progress-summary span { color:var(--muted); font-size:12px; }
.tjy-next-card { display:grid; grid-template-columns:auto 1fr auto; align-items:center; gap:22px; padding:22px 24px; border:1px solid #cfe9dc; background:linear-gradient(100deg,#f1fbf6,#fff); border-radius:16px; }
.tjy-next-card.is-attention { border-color:#f0d8b6; background:linear-gradient(100deg,#fff8ed,#fff); }
.tjy-next-marker { align-self:stretch; display:flex; align-items:center; padding-right:22px; border-right:1px solid rgba(0,0,0,.08); color:var(--green); font-size:13px; font-weight:700; }
.tjy-next-copy h2 { margin:7px 0 4px; font-size:20px; }.tjy-next-copy p { margin:0; color:var(--muted); font-size:13px; }
.tjy-primary-action { border:0; border-radius:10px; background:#171717; color:#fff; padding:12px 17px; font-weight:600; display:flex; gap:18px; align-items:center; }
.tjy-metrics { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin:22px 0 36px; }
.tjy-metric-card { min-width:0; border:1px solid var(--line); border-radius:14px; padding:18px; background:#fff; }
.tjy-metric-card>span,.tjy-metric-card small { display:block; color:var(--muted); font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.tjy-metric-card div { margin:9px 0 6px; }.tjy-metric-card strong { font-size:26px; }.tjy-metric-card em { margin-left:5px; font-size:12px; font-style:normal; color:var(--muted); }
.tjy-process-section { border-top:1px solid var(--line); padding-top:29px; }
.tjy-section-heading { display:flex; justify-content:space-between; align-items:end; gap:20px; margin-bottom:18px; }
.tjy-section-heading span { font-size:12px; font-weight:700; color:var(--green); }.tjy-section-heading h2 { font-size:21px; margin:5px 0 0; }.tjy-section-heading p { margin:0; color:var(--muted); font-size:12px; }
.tjy-step-list { border:1px solid var(--line); border-radius:16px; overflow:hidden; }
.tjy-step { display:grid; grid-template-columns:46px 1fr auto; gap:10px; min-height:92px; padding:18px 20px 0; background:#fff; }
.tjy-step+.tjy-step { border-top:1px solid var(--line); }.tjy-step-rail { position:relative; display:flex; justify-content:center; }
.tjy-step-rail span { z-index:1; display:grid; place-items:center; width:30px; height:30px; border-radius:50%; border:1px solid #d7d7d4; background:#fff; font-size:11px; font-weight:700; color:var(--muted); }
.tjy-step-rail i { position:absolute; top:30px; bottom:-19px; width:1px; background:var(--line); }
.tjy-step-done .tjy-step-rail span { background:var(--green); color:#fff; border-color:var(--green); }.tjy-step-attention .tjy-step-rail span { background:var(--amber-soft); color:var(--amber); border-color:#f1d2a7; }
.tjy-step-copy>div { display:flex; align-items:center; gap:10px; }.tjy-step-copy h3 { margin:2px 0 7px; font-size:16px; }.tjy-step-copy p { margin:0 0 17px; color:var(--muted); font-size:12px; }
.tjy-step>button { align-self:start; border:1px solid var(--line); border-radius:9px; background:#fff; padding:8px 11px; font-size:12px; display:flex; align-items:center; gap:14px; }
.tjy-status { display:inline-flex; border-radius:99px; padding:3px 8px; font-size:10px; font-weight:600; }.tjy-status-done { color:#168358; background:var(--green-soft); }.tjy-status-pending { color:#666; background:#f0f0ee; }.tjy-status-attention { color:var(--amber); background:var(--amber-soft); }
.tjy-support-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:18px; }
.tjy-support-grid button { display:grid; grid-template-columns:36px 1fr auto; align-items:center; gap:12px; text-align:left; border:1px solid var(--line); border-radius:12px; background:#fff; padding:14px; }.tjy-support-grid strong,.tjy-support-grid small { display:block; }.tjy-support-grid small { color:var(--muted); font-size:11px; margin-top:2px; }.tjy-support-grid em { font-style:normal; color:var(--muted); }
.tjy-support-icon { display:grid; place-items:center; width:34px; height:34px; border-radius:9px; background:var(--soft); font-size:12px; font-weight:700; }
.tjy-loading,.tjy-state-card { min-height:420px; display:flex; align-items:center; justify-content:center; flex-direction:column; color:var(--muted); }.tjy-loading span { display:inline-block; width:7px; height:7px; background:#bbb; border-radius:50%; margin:2px; animation:tjyPulse 1s infinite alternate; }.tjy-loading span:nth-child(2){animation-delay:.15s}.tjy-loading span:nth-child(3){animation-delay:.3s}@keyframes tjyPulse{to{opacity:.25;transform:translateY(-3px)}}
@media(max-width:900px){.tjy-dashboard{padding:24px 18px}.tjy-metrics{grid-template-columns:repeat(2,1fr)}.tjy-next-card{grid-template-columns:1fr}.tjy-next-marker{border-right:0;border-bottom:1px solid rgba(0,0,0,.08);padding:0 0 12px}.tjy-support-grid{grid-template-columns:1fr}.tjy-section-heading p{display:none}}
`;
