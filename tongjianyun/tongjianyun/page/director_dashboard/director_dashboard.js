frappe.pages["director-dashboard"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: "园长驾驶舱",
        single_column: true,
    });
    wrapper.director_dashboard = new DirectorDashboardPage(page);
};

frappe.pages["director-dashboard"].on_page_show = function (wrapper) {
    const controller = wrapper.director_dashboard;
    if (controller && controller.loadedOnce) {
        controller.load({ silent: true });
    }
};

class DirectorDashboardPage {
    constructor(page) {
        this.page = page;
        this.main = $('<div class="tjy-director-shell"></div>').appendTo(page.main);
        this.data = {};
        this.loadedOnce = false;
        this.installStyles();
        this.load();
    }

    async load({ silent = false } = {}) {
        if (!silent) {
            this.main.html(this.loadingView());
        }
        try {
            const response = await frappe.call({
                method: "tongjianyun.director_dashboard.get_dashboard",
            });
            this.data = response.message || {};
            this.loadedOnce = true;
            this.render();
        } catch (error) {
            this.main.html(this.errorView(error));
            this.bindRetry();
        }
    }

    render() {
        const d = this.data || {};
        const metrics = d.metrics || {};
        const attendance = d.attendance || {};
        const nutrition = d.nutrition || {};
        const finance = d.finance || {};

        this.main.html([
            this.hero(d),
            this.sceneNav(d.scenes || []),
            '<section class="director-section director-metrics">',
            this.metricCard(metrics.students, "👥"),
            this.metricCard(metrics.attendance, "◷"),
            this.metricCard(metrics.meals, "🥣"),
            this.metricCard(metrics.warnings, "🔔"),
            "</section>",
            '<section class="director-two-column">',
            this.focusCard(d.focus || []),
            this.taskCard(d.tasks || []),
            "</section>",
            this.classSection(attendance.classes || []),
            '<section class="director-business-grid">',
            (d.business_cards || []).map((card) => this.businessCard(card)).join(""),
            "</section>",
            '<section class="director-bottom-grid">',
            this.nutritionCard(nutrition),
            this.financeCard(finance),
            this.trendCard(d.trend || []),
            "</section>",
            this.footer(d),
        ].join(""));

        this.bindEvents();
    }

    hero(d) {
        const warningCount = Number(d.warning_count || 0);
        const stateClass = warningCount ? "is-attention" : "is-good";
        return [
            '<section class="director-hero">',
            '  <div class="director-hero-copy">',
            '    <div class="director-brand-line"><span class="director-brand-mark">童</span><span>童健云 · 园长驾驶舱</span></div>',
            '    <h1>早上好，' + escapeHtml(d.operator_name || "园长") + "！</h1>",
            '    <p>今天是 ' + escapeHtml(d.date_label || "") + "，" + escapeHtml(d.headline || "正在汇总园所运行情况") + "。</p>",
            '    <div class="director-health ' + stateClass + '"><span class="director-health-dot"></span>' +
                    (warningCount ? "请优先处理异常与待办" : "园所关键业务运行正常") + "</div>",
            "  </div>",
            '  <div class="director-hero-scene" aria-hidden="true">',
            '    <div class="director-sun"></div>',
            '    <div class="director-cloud c1"></div><div class="director-cloud c2"></div>',
            '    <div class="director-school">🏫</div>',
            '    <div class="director-kids">🧒 👧 🧒</div>',
            "  </div>",
            '  <button class="director-refresh" type="button" data-action="refresh">↻ 刷新</button>',
            "</section>",
        ].join("");
    }

    sceneNav(items) {
        return [
            '<nav class="director-scene-nav" aria-label="园长业务场景">',
            items.map((item, index) => [
                '<button type="button" class="director-scene-item ' + (index === 0 ? "is-active" : "") + '" ',
                'data-route="' + routeAttr(item.route) + '">',
                '<span class="director-scene-icon">' + escapeHtml(item.icon || "•") + "</span>",
                '<span>' + escapeHtml(item.label || "") + "</span>",
                "</button>",
            ].join("")).join(""),
            "</nav>",
        ].join("");
    }

    metricCard(metric, icon) {
        metric = metric || {};
        const tone = metric.tone || "blue";
        let value = metric.value;
        if (metric.label === "出勤率") {
            value = formatNumber(value, 1);
        } else {
            value = formatNumber(value, 0);
        }
        const total = metric.total ? " / " + formatNumber(metric.total, 0) : "";
        return [
            '<article class="director-metric is-' + escapeHtml(tone) + '">',
            '  <div class="director-metric-top"><span class="director-metric-icon">' + icon + "</span><span>" + escapeHtml(metric.label || "") + "</span></div>",
            '  <div class="director-metric-value">' + value + total + '<small>' + escapeHtml(metric.suffix || "") + "</small></div>",
            '  <div class="director-metric-hint">' + escapeHtml(metric.hint || "暂无数据") + "</div>",
            "</article>",
        ].join("");
    }

    focusCard(items) {
        return [
            '<article class="director-panel">',
            '  <div class="director-panel-title"><div><span class="director-title-icon is-blue">▣</span><strong>今日工作重点</strong></div><span class="director-panel-sub">按业务闭环推进</span></div>',
            '  <div class="director-focus-list">',
            items.map((item) => [
                '<button type="button" class="director-focus-row" data-route="' + routeAttr(item.route) + '">',
                '  <span class="director-focus-state is-' + escapeHtml(item.status || "pending") + '">' + this.statusIcon(item.status) + "</span>",
                '  <span class="director-focus-label">' + escapeHtml(item.label || "") + "</span>",
                '  <span class="director-focus-badge is-' + escapeHtml(item.status || "pending") + '">' + escapeHtml(item.status_label || "") + "</span>",
                "</button>",
            ].join("")).join(""),
            "  </div>",
            "</article>",
        ].join("");
    }

    taskCard(items) {
        return [
            '<article class="director-panel">',
            '  <div class="director-panel-title"><div><span class="director-title-icon is-red">!</span><strong>园长待办事项</strong><span class="director-count-badge">' + items.filter((x) => x.priority !== "normal").length + '</span></div><span class="director-panel-sub">异常优先</span></div>',
            '  <div class="director-task-list">',
            items.map((item) => [
                '<div class="director-task is-' + escapeHtml(item.priority || "normal") + '">',
                '  <span class="director-task-level">' + this.priorityIcon(item.priority) + "</span>",
                '  <div class="director-task-copy"><strong>' + escapeHtml(item.title || "") + '</strong><p>' + escapeHtml(item.description || "") + "</p></div>",
                item.route ? '<button type="button" class="director-task-action" data-route="' + routeAttr(item.route) + '">' + escapeHtml(item.action || "查看") + "</button>" : "",
                "</div>",
            ].join("")).join(""),
            "  </div>",
            "</article>",
        ].join("");
    }

    classSection(classes) {
        if (!classes.length) {
            return [
                '<section class="director-panel director-class-section">',
                '  <div class="director-panel-title"><div><span class="director-title-icon is-green">班</span><strong>班级运行情况</strong></div><span class="director-panel-sub">等待今日就餐确认数据</span></div>',
                '  <div class="director-empty">今日暂无班级聚合数据，确认就餐人数后将在这里展示各班出勤与就餐情况。</div>',
                "</section>",
            ].join("");
        }
        return [
            '<section class="director-panel director-class-section">',
            '  <div class="director-panel-title"><div><span class="director-title-icon is-green">班</span><strong>班级运行情况</strong></div><button type="button" class="director-link-btn" data-route="' + routeAttr(["List", "Student Attendance"]) + '">查看全部 →</button></div>',
            '  <div class="director-class-table">',
            '    <div class="director-class-head"><span>班级</span><span>在册</span><span>到园</span><span>就餐</span><span>出勤率</span><span>状态</span></div>',
            classes.map((row) => [
                '<button type="button" class="director-class-row" data-route="' + routeAttr(["List", "Student Attendance"]) + '">',
                '  <span class="director-class-name">' + escapeHtml(row.class_name || "") + "</span>",
                "  <span>" + formatNumber(row.enrolled, 0) + "</span>",
                "  <span>" + formatNumber(row.present, 0) + "</span>",
                "  <span>" + formatNumber(row.lunch, 0) + "</span>",
                '  <span class="' + (row.status === "danger" ? "text-danger" : row.status === "warning" ? "text-warning" : "") + '">' + formatNumber(row.rate, 1) + "%</span>",
                '  <span><em class="director-status-pill is-' + escapeHtml(row.status || "normal") + '">' + this.classStatus(row.status) + "</em></span>",
                "</button>",
            ].join("")).join(""),
            "  </div>",
            "</section>",
        ].join("");
    }

    businessCard(card) {
        return [
            '<button type="button" class="director-business-card is-' + escapeHtml(card.tone || "blue") + '" data-route="' + routeAttr(card.route) + '">',
            '  <span class="director-business-icon">' + escapeHtml(card.icon || "") + "</span>",
            '  <span class="director-business-copy"><strong>' + escapeHtml(card.title || "") + "</strong><small>" + escapeHtml(card.description || "") + "</small></span>",
            '  <span class="director-business-arrow">→</span>',
            "</button>",
        ].join("");
    }

    nutritionCard(data) {
        const total = Number(data.total || 0);
        const suitable = Number(data.suitable || 0);
        const percent = total ? Math.round((suitable / total) * 100) : 0;
        const attention = data.attention || [];
        return [
            '<article class="director-insight-card">',
            '  <div class="director-insight-title"><strong>本周营养概况</strong><button type="button" data-route="' + routeAttr(["weekly-recipe-nutrition-sheet"]) + '">查看详情 →</button></div>',
            data.available ? [
                '  <div class="director-nutrition-body">',
                '    <div class="director-ring" style="--ring:' + percent + '"><span><strong>' + suitable + " / " + total + "</strong><small>指标适宜</small></span></div>",
                '    <div class="director-nutrition-list">',
                attention.length ? attention.map((item) => '<div><span class="dot is-warning"></span><span>' + escapeHtml(item.label) + "：" + escapeHtml(item.status) + "</span><strong>" + formatNumber(item.percent, 0) + "%</strong></div>").join("") : '<div><span class="dot is-good"></span><span>主要营养指标处于参考范围</span></div>',
                "    </div>",
                "  </div>",
                '  <p class="director-insight-note">' + escapeHtml(data.conclusion || "") + "</p>",
            ].join("") : '<div class="director-empty compact">暂无可用营养分析，请先完善并保存本周食谱。</div>',
            "</article>",
        ].join("");
    }

    financeCard(data) {
        const budget = data.budget_percent == null ? data.budget_label || "未配置预算" : formatNumber(data.budget_percent, 0) + "%";
        return [
            '<article class="director-insight-card">',
            '  <div class="director-insight-title"><strong>本月餐费 / 采购成本</strong><button type="button" data-route="' + routeAttr(["List", "Purchase Invoice"]) + '">查看详情 →</button></div>',
            '  <div class="director-finance-main"><span class="money">¥ ' + formatMoney(data.spend) + '</span><small>' + escapeHtml(data.month_label || "") + " · " + escapeHtml(data.source || "采购数据") + "</small></div>",
            '  <div class="director-finance-grid">',
            '    <div><span>人均采购成本</span><strong>¥ ' + formatMoney(data.per_capita) + "</strong></div>",
            '    <div><span>预算执行</span><strong>' + escapeHtml(budget) + "</strong></div>",
            '    <div><span>结算单据</span><strong>' + formatNumber(data.document_count, 0) + " 份</strong></div>",
            "  </div>",
            "</article>",
        ].join("");
    }

    trendCard(points) {
        const valid = points.filter((point) => point.rate != null);
        const maxLunch = Math.max(1, ...points.map((point) => Number(point.lunch || 0)));
        return [
            '<article class="director-insight-card">',
            '  <div class="director-insight-title"><strong>近 7 日趋势</strong><button type="button" data-route="' + routeAttr(["List", "Tongjianyun Daily Meal Confirmation"]) + '">查看数据 →</button></div>',
            '  <div class="director-trend">',
            points.map((point) => {
                const rate = point.rate == null ? 0 : Math.max(0, Math.min(100, Number(point.rate)));
                const lunch = point.lunch == null ? 0 : Number(point.lunch);
                return [
                    '<div class="director-trend-col" title="' + escapeAttr(point.label + " 出勤率 " + (point.rate == null ? "暂无" : point.rate + "%") + " / 就餐 " + (point.lunch == null ? "暂无" : point.lunch)) + '">',
                    '  <div class="director-trend-bars">',
                    '    <span class="rate-bar" style="height:' + rate + '%"></span>',
                    '    <span class="meal-bar" style="height:' + Math.round((lunch / maxLunch) * 100) + '%"></span>',
                    "  </div>",
                    '  <small>' + escapeHtml(point.label || "") + "</small>",
                    "</div>",
                ].join("");
            }).join(""),
            "  </div>",
            '  <div class="director-trend-legend"><span><i class="legend-rate"></i>出勤率</span><span><i class="legend-meal"></i>就餐人数</span><strong>' + (valid.length ? "最新 " + formatNumber(valid[valid.length - 1].rate, 1) + "%" : "暂无趋势数据") + "</strong></div>",
            "</article>",
        ].join("");
    }

    footer(d) {
        return '<div class="director-footer">数据更新时间：' + escapeHtml(d.generated_at || "") + " · 驾驶舱仅展示业务聚合数据，不展示幼儿个人敏感信息</div>";
    }

    statusIcon(status) {
        if (status === "done") return "✓";
        if (status === "attention") return "!";
        return "•";
    }

    priorityIcon(priority) {
        if (priority === "urgent") return "!";
        if (priority === "important") return "•";
        return "✓";
    }

    classStatus(status) {
        if (status === "danger") return "异常";
        if (status === "warning") return "关注";
        return "正常";
    }

    bindEvents() {
        this.main.find('[data-action="refresh"]').on("click", () => this.load());
        this.main.find("[data-route]").on("click", (event) => {
            const route = parseRoute($(event.currentTarget).attr("data-route"));
            if (!route || !route.length) {
                this.main.find(".director-scene-item").removeClass("is-active");
                $(event.currentTarget).addClass("is-active");
                this.main.get(0)?.scrollIntoView({ behavior: "smooth", block: "start" });
                return;
            }
            frappe.set_route(...route);
        });
    }

    bindRetry() {
        this.main.find('[data-action="retry"]').on("click", () => this.load());
    }

    loadingView() {
        return [
            '<div class="director-loading">',
            '  <div class="director-loading-mark">童</div>',
            "  <strong>正在汇总园所经营数据...</strong>",
            "  <p>考勤、膳食、采购和营养数据正在加载</p>",
            "</div>",
        ].join("");
    }

    errorView(error) {
        const message = error?.message || error?.exc || "请稍后重试";
        return [
            '<div class="director-error">',
            "  <h3>驾驶舱加载失败</h3>",
            "  <p>" + escapeHtml(message) + "</p>",
            '  <button type="button" data-action="retry">重新加载</button>',
            "</div>",
        ].join("");
    }

    installStyles() {
        $("#tjy-director-styles").remove();
        $("<style>", { id: "tjy-director-styles", text: DIRECTOR_STYLES }).appendTo(document.head);
    }
}

function formatNumber(value, digits = 0) {
    const number = Number(value);
    if (!Number.isFinite(number)) return digits ? "0.0" : "0";
    return number.toLocaleString("zh-CN", {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
    });
}

function formatMoney(value) {
    const number = Number(value);
    if (!Number.isFinite(number)) return "0";
    return number.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function routeAttr(route) {
    if (!route) return "";
    return escapeAttr(JSON.stringify(route));
}

function parseRoute(value) {
    if (!value) return null;
    try {
        return JSON.parse(value);
    } catch (_error) {
        return null;
    }
}

function escapeHtml(value) {
    if (value == null) return "";
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function escapeAttr(value) {
    return escapeHtml(value).replace(/\n/g, " ");
}

const DIRECTOR_STYLES = [
    ':root{--tjy-ink:#16352b;--tjy-muted:#73817b;--tjy-line:#dfe9e3;--tjy-bg:#f4faf7;--tjy-green:#16835d;--tjy-blue:#3979a8;--tjy-orange:#d98516;--tjy-red:#d94b55;--tjy-purple:#7a5cc5}',
    '.page-container[data-page-route="director-dashboard"] .page-body{background:linear-gradient(180deg,#f7fcfa 0,#f3f8f6 100%)}',
    '.page-container[data-page-route="director-dashboard"] .layout-main-section{background:transparent}',
    '.tjy-director-shell{max-width:1280px;margin:0 auto;padding:18px 26px 42px;color:var(--tjy-ink);font-family:"Inter","PingFang SC","Microsoft YaHei",sans-serif}',
    '.director-hero{position:relative;display:grid;grid-template-columns:minmax(0,1.35fr) minmax(260px,.65fr);min-height:188px;overflow:hidden;border:1px solid #dcebe3;border-radius:22px;background:linear-gradient(115deg,#fff 0%,#f6fcf9 56%,#eaf8f0 100%);box-shadow:0 10px 34px rgba(31,91,68,.07);margin-bottom:14px}',
    '.director-hero-copy{padding:26px 30px;z-index:2}.director-brand-line{display:flex;align-items:center;gap:9px;font-size:13px;font-weight:700;color:#42715e;margin-bottom:14px}.director-brand-mark{display:grid;place-items:center;width:28px;height:28px;border-radius:9px;background:#16a36f;color:#fff;box-shadow:0 5px 12px rgba(22,163,111,.22)}',
    '.director-hero h1{margin:0 0 7px;font-size:28px;line-height:1.25;font-weight:780;color:#17372c}.director-hero p{margin:0;color:#687b73;font-size:14px}',
    '.director-health{display:inline-flex;align-items:center;gap:7px;margin-top:18px;padding:7px 11px;border-radius:999px;font-size:12px;font-weight:650}.director-health.is-good{background:#e9f8f0;color:#19714f}.director-health.is-attention{background:#fff4e2;color:#a76708}.director-health-dot{width:7px;height:7px;border-radius:50%;background:currentColor;box-shadow:0 0 0 4px rgba(22,131,93,.08)}',
    '.director-hero-scene{position:relative;min-height:188px;background:linear-gradient(180deg,#eaf8ff 0%,#f4fff7 62%,#dff2df 63%,#cfe9cf 100%);overflow:hidden}.director-sun{position:absolute;right:42px;top:23px;width:44px;height:44px;border-radius:50%;background:#ffd86c;box-shadow:0 0 0 10px rgba(255,216,108,.16)}.director-cloud{position:absolute;width:58px;height:17px;background:#fff;border-radius:20px;opacity:.88}.director-cloud:before,.director-cloud:after{content:"";position:absolute;background:#fff;border-radius:50%}.director-cloud:before{width:23px;height:23px;left:10px;top:-11px}.director-cloud:after{width:29px;height:29px;right:8px;top:-15px}.director-cloud.c1{left:24px;top:34px}.director-cloud.c2{right:72px;top:75px;transform:scale(.75)}.director-school{position:absolute;left:50%;bottom:25px;transform:translateX(-50%);font-size:72px;filter:drop-shadow(0 7px 5px rgba(56,102,75,.15))}.director-kids{position:absolute;left:50%;bottom:5px;transform:translateX(-50%);font-size:27px;white-space:nowrap}',
    '.director-refresh{position:absolute;right:14px;top:12px;z-index:4;border:1px solid #d4e5dc;background:rgba(255,255,255,.92);color:#35715b;border-radius:9px;padding:7px 11px;font-size:12px;font-weight:650;cursor:pointer}.director-refresh:hover{background:#fff;border-color:#9dccb8}',
    '.director-scene-nav{display:grid;grid-template-columns:repeat(6,1fr);background:#fff;border:1px solid var(--tjy-line);border-radius:15px;padding:5px;margin-bottom:14px;box-shadow:0 5px 20px rgba(31,91,68,.04)}.director-scene-item{display:flex;justify-content:center;align-items:center;gap:7px;border:0;background:transparent;color:#65766f;border-radius:10px;padding:10px 6px;font-size:13px;font-weight:650;cursor:pointer}.director-scene-item:hover{background:#f3f8f6;color:#235b45}.director-scene-item.is-active{background:#eef8f3;color:#0d7e55}.director-scene-icon{font-size:14px}',
    '.director-section{margin-bottom:14px}.director-metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.director-metric{position:relative;background:#fff;border:1px solid var(--tjy-line);border-radius:16px;padding:15px 16px;overflow:hidden;box-shadow:0 5px 18px rgba(31,91,68,.035)}.director-metric:after{content:"";position:absolute;right:-18px;bottom:-22px;width:74px;height:74px;border-radius:50%;background:currentColor;opacity:.055}.director-metric.is-green{color:var(--tjy-green)}.director-metric.is-blue{color:var(--tjy-blue)}.director-metric.is-orange{color:var(--tjy-orange)}.director-metric.is-red{color:var(--tjy-red)}.director-metric-top{display:flex;align-items:center;gap:8px;color:#6a7b74;font-size:12px;font-weight:650}.director-metric-icon{display:grid;place-items:center;width:26px;height:26px;border-radius:8px;background:currentColor;color:#fff;font-size:13px}.director-metric-value{margin:8px 0 5px;color:#18372c;font-size:26px;font-weight:800;letter-spacing:-.6px}.director-metric-value small{margin-left:4px;color:#61746c;font-size:11px;font-weight:600}.director-metric-hint{font-size:11px;color:#829089}',
    '.director-two-column{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px}.director-panel,.director-insight-card{background:#fff;border:1px solid var(--tjy-line);border-radius:17px;box-shadow:0 5px 18px rgba(31,91,68,.035)}.director-panel{padding:16px}.director-panel-title,.director-insight-title{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.director-panel-title>div,.director-insight-title{font-size:14px}.director-title-icon{display:inline-grid;place-items:center;width:24px;height:24px;border-radius:7px;margin-right:8px;font-size:11px;color:#fff}.director-title-icon.is-blue{background:#4384b3}.director-title-icon.is-red{background:#dd5360}.director-title-icon.is-green{background:#25966d}.director-panel-sub{color:#98a39e;font-size:11px}.director-count-badge{display:inline-grid;place-items:center;min-width:19px;height:19px;margin-left:6px;border-radius:999px;background:#e7515c;color:#fff;font-size:10px}',
    '.director-focus-list{display:grid;gap:4px}.director-focus-row{display:grid;grid-template-columns:24px 1fr auto;align-items:center;gap:9px;width:100%;border:0;background:transparent;border-radius:10px;padding:7px 6px;text-align:left;cursor:pointer}.director-focus-row:hover{background:#f6faf8}.director-focus-state{display:grid;place-items:center;width:20px;height:20px;border-radius:50%;font-size:11px;font-weight:800}.director-focus-state.is-done{background:#e4f6ed;color:#16835d}.director-focus-state.is-attention{background:#fff0dc;color:#c7770c}.director-focus-state.is-pending{background:#eef2f0;color:#8c9a94}.director-focus-label{font-size:12px;color:#314b41}.director-focus-badge{padding:3px 7px;border-radius:999px;font-size:10px;font-style:normal}.director-focus-badge.is-done{background:#e8f7ef;color:#16835d}.director-focus-badge.is-attention{background:#fff3df;color:#b66c08}.director-focus-badge.is-pending{background:#f0f3f2;color:#7c8984}',
    '.director-task-list{display:grid;gap:7px}.director-task{display:grid;grid-template-columns:28px 1fr auto;align-items:center;gap:8px;border-radius:11px;padding:8px 9px;background:#fafcfb}.director-task.is-urgent{background:#fff3f3}.director-task.is-important{background:#fff9ee}.director-task.is-normal{background:#f1faf5}.director-task-level{display:grid;place-items:center;width:25px;height:25px;border-radius:50%;background:#eef3f1;color:#74847d;font-weight:800}.director-task.is-urgent .director-task-level{background:#e8555f;color:#fff}.director-task.is-important .director-task-level{background:#f0a326;color:#fff}.director-task.is-normal .director-task-level{background:#21a274;color:#fff}.director-task-copy strong{display:block;font-size:12px;color:#274339;margin-bottom:2px}.director-task-copy p{margin:0;color:#85918c;font-size:10.5px;line-height:1.45}.director-task-action,.director-link-btn,.director-insight-title button{border:0;background:transparent;color:#3380b3;font-size:10.5px;font-weight:650;cursor:pointer;white-space:nowrap}',
    '.director-class-section{margin-bottom:14px}.director-class-table{overflow:hidden;border:1px solid #edf2ef;border-radius:11px}.director-class-head,.director-class-row{display:grid;grid-template-columns:1.4fr repeat(5,.7fr);align-items:center;gap:7px;padding:8px 11px}.director-class-head{background:#f7faf8;color:#84918c;font-size:10.5px;font-weight:650}.director-class-row{width:100%;border:0;border-top:1px solid #edf2ef;background:#fff;color:#496058;font-size:11px;text-align:left;cursor:pointer}.director-class-row:hover{background:#fbfdfc}.director-class-row span:not(:first-child){text-align:center}.director-class-name{font-weight:650;color:#274339}.director-status-pill{display:inline-block;padding:2px 7px;border-radius:999px;font-style:normal;font-size:9.5px}.director-status-pill.is-normal{background:#e8f7ef;color:#16835d}.director-status-pill.is-warning{background:#fff3de;color:#bd720c}.director-status-pill.is-danger{background:#ffe9eb;color:#d34752}.text-danger{color:#d34752!important;font-weight:700}.text-warning{color:#c7790b!important;font-weight:700}.director-empty{padding:22px;text-align:center;color:#9aa49f;font-size:11px}.director-empty.compact{padding:28px 10px}',
    '.director-business-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}.director-business-card{display:grid;grid-template-columns:42px 1fr auto;align-items:center;gap:10px;min-height:82px;border:1px solid var(--tjy-line);border-radius:16px;background:#fff;padding:13px 14px;text-align:left;cursor:pointer;transition:transform .16s,border-color .16s,box-shadow .16s}.director-business-card:hover{transform:translateY(-2px);box-shadow:0 9px 24px rgba(31,91,68,.08)}.director-business-card.is-green:hover{border-color:#9dd5bf}.director-business-card.is-orange:hover{border-color:#f0c47f}.director-business-card.is-blue:hover{border-color:#a9cce4}.director-business-card.is-purple:hover{border-color:#c9b9eb}.director-business-icon{display:grid;place-items:center;width:42px;height:42px;border-radius:12px;background:#f0f7f4;font-size:21px}.director-business-card.is-orange .director-business-icon{background:#fff5e7}.director-business-card.is-blue .director-business-icon{background:#edf6fc}.director-business-card.is-purple .director-business-icon{background:#f4effd}.director-business-copy strong{display:block;color:#274339;font-size:13px}.director-business-copy small{display:block;margin-top:4px;color:#89958f;font-size:10.5px;line-height:1.35}.director-business-arrow{color:#99a8a1;font-size:16px}',
    '.director-bottom-grid{display:grid;grid-template-columns:1.08fr .92fr 1.15fr;gap:14px}.director-insight-card{padding:15px;min-width:0}.director-insight-title{font-size:13px;margin-bottom:12px}.director-nutrition-body{display:grid;grid-template-columns:105px 1fr;align-items:center;gap:13px}.director-ring{--ring:0;position:relative;width:96px;height:96px;border-radius:50%;background:conic-gradient(#22a978 calc(var(--ring)*1%),#e9f0ec 0);display:grid;place-items:center}.director-ring:before{content:"";position:absolute;inset:9px;background:#fff;border-radius:50%}.director-ring span{position:relative;z-index:2;text-align:center}.director-ring strong{display:block;font-size:16px;color:#244b3c}.director-ring small{font-size:9px;color:#87938d}.director-nutrition-list{display:grid;gap:6px}.director-nutrition-list>div{display:grid;grid-template-columns:8px 1fr auto;align-items:center;gap:6px;color:#60736a;font-size:10.5px}.director-nutrition-list strong{font-size:10px;color:#93610e}.dot{width:6px;height:6px;border-radius:50%;background:#97a59f}.dot.is-warning{background:#f0a326}.dot.is-good{background:#22a978}.director-insight-note{margin:10px 0 0;padding-top:9px;border-top:1px dashed #e3ebe7;color:#8a9690;font-size:9.5px;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}',
    '.director-finance-main{padding:6px 0 11px}.director-finance-main .money{display:block;color:#213c32;font-size:25px;font-weight:800;letter-spacing:-.4px}.director-finance-main small{display:block;margin-top:2px;color:#909c96;font-size:9.5px}.director-finance-grid{display:grid;grid-template-columns:1fr;gap:6px}.director-finance-grid>div{display:flex;justify-content:space-between;align-items:center;padding:7px 8px;background:#f8faf9;border-radius:8px;color:#7c8983;font-size:10px}.director-finance-grid strong{color:#3a554b;font-size:10.5px}',
    '.director-trend{height:128px;display:grid;grid-template-columns:repeat(7,1fr);gap:5px;align-items:end;padding-top:6px}.director-trend-col{height:100%;display:grid;grid-template-rows:1fr 16px;gap:4px}.director-trend-bars{display:flex;align-items:end;justify-content:center;gap:2px;height:100%;border-bottom:1px solid #edf1ef}.director-trend-bars span{display:block;width:7px;min-height:2px;border-radius:3px 3px 1px 1px}.rate-bar{background:#4b99cb}.meal-bar{background:#8bd4b7}.director-trend-col small{text-align:center;color:#9aa49f;font-size:8px}.director-trend-legend{display:flex;align-items:center;gap:10px;margin-top:5px;color:#8a9690;font-size:9px}.director-trend-legend span{display:flex;align-items:center;gap:4px}.director-trend-legend i{width:7px;height:7px;border-radius:2px}.legend-rate{background:#4b99cb}.legend-meal{background:#8bd4b7}.director-trend-legend strong{margin-left:auto;color:#4d665c;font-size:9.5px}',
    '.director-footer{text-align:center;padding:16px 6px 0;color:#9aa59f;font-size:9.5px}.director-loading,.director-error{display:grid;place-items:center;min-height:360px;text-align:center;color:#72827b}.director-loading-mark{display:grid;place-items:center;width:52px;height:52px;border-radius:16px;background:#1b9a6c;color:#fff;font-size:22px;font-weight:800;box-shadow:0 9px 24px rgba(27,154,108,.2);margin-bottom:12px}.director-loading strong{font-size:14px}.director-loading p{margin-top:5px;color:#9aa59f;font-size:11px}.director-error h3{color:#d44b56;margin:0 0 6px}.director-error p{max-width:540px;font-size:11px}.director-error button{border:0;border-radius:8px;background:#2f8b68;color:#fff;padding:8px 14px;font-size:11px;cursor:pointer}',
    '@media(max-width:1000px){.director-hero{grid-template-columns:1fr 300px}.director-scene-nav{grid-template-columns:repeat(3,1fr);gap:4px}.director-metrics{grid-template-columns:repeat(2,1fr)}.director-business-grid{grid-template-columns:repeat(2,1fr)}.director-bottom-grid{grid-template-columns:1fr 1fr}.director-bottom-grid .director-insight-card:last-child{grid-column:1/-1}}',
    '@media(max-width:720px){.tjy-director-shell{padding:12px 10px 30px}.director-hero{grid-template-columns:1fr;min-height:0}.director-hero-copy{padding:20px}.director-hero-scene{display:none}.director-hero h1{font-size:23px}.director-scene-nav{grid-template-columns:repeat(2,1fr)}.director-metrics,.director-two-column,.director-business-grid,.director-bottom-grid{grid-template-columns:1fr}.director-bottom-grid .director-insight-card:last-child{grid-column:auto}.director-class-table{overflow-x:auto}.director-class-head,.director-class-row{min-width:620px}.director-refresh{right:9px;top:9px}.director-nutrition-body{grid-template-columns:95px 1fr}}',
].join("");
