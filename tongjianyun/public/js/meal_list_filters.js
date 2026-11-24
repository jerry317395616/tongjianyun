// Shortcuts mirror the native List View filter so saved views, pagination and permissions still apply.
(() => {
	const fieldByPage = {
		"供应商配送批次":"progress", "每周膳食任务":"task_kind", "食品留样":"meal_type",
		"陪餐登记与评价":"meal_type", "到园成品交接":"result", "班级进餐反馈":"meal_type",
		"特殊餐交接":"meal_type", "食品安全检查":"period", "监管整改":"progress",
		"家长膳食意见":"category", "食堂资质与场所档案":"service_mode", "食堂证照与健康证":"subject_kind",
		"从业人员培训记录":"result", "地方采购与财务流程":"procurement_mode", "食堂岗位配置":"day_scope",
		"标准食材库":"disabled", "标准菜品库":"disabled",
	};
	function choicesFor(list, title) {
		const field = fieldByPage[title];
		if (field === "disabled") {
			return {field, label:"启用状态", choices:[["0","启用"], ["1","停用"]]};
		}
		const df = field && list.meta.fields.find(f => f.fieldname === field);
		if (df?.fieldtype === "Select" && !df.hidden && frappe.perm.has_perm(list.doctype, df.permlevel || 0)) {
			const values = (df.options || "").split("\n").map(v => v.trim()).filter(Boolean);
			if (values.length > 1 && values.length <= 7) {
				return {field, label:df.label, choices:values.map(v => [v,v])};
			}
		}
		if (list.meta.is_submittable) {
			return {field:"docstatus", label:"单据状态", choices:[["0","草稿"],["1","已提交"],["2","已取消"]]};
		}
	}
	function currentChoice(list, config) {
		const filters = list.filter_area.get();
		const matching = filters.filter(f => f[1] === config.field);
		if (!matching.length) return "";
		const [type,,operator,value,hidden] = matching[0];
		if (matching.length === 1 && type === list.doctype && operator === "=" && !hidden &&
			config.choices.some(([v]) => v === String(value))) return String(value);
		// An advanced condition may belong to a saved view. Leave its native controls visible.
		return null;
	}
	async function setChoice(list, config, value) {
		const selected = currentChoice(list, config);
		if (selected === null || value === selected) return;
		const area = list.filter_area;
		if (selected !== "") await area.remove(config.field);
		if (value !== "") await area.add([[list.doctype, config.field, "=", value]], false);
		list.start = 0;
		await list.refresh();
	}
	function button(text, cls) {
		const b = document.createElement("button");
		b.type = "button";
		b.className = cls;
		b.textContent = text;
		return b;
	}
	function remove(bar) {
		if (!bar) return;
		bar.parentElement?.classList.remove("tjy-filters-closed");
		bar.remove();
	}
	function render(list, title) {
		const main = list.page.main?.[0];
		const form = main?.querySelector(":scope > .list-page-form");
		if (!form || !list.filter_area) return;
		let bar = main.querySelector(":scope > .tjy-quick-views");
		const config = choicesFor(list, title);
		const current = config && currentChoice(list, config);
		if (!config || current === null) { remove(bar); return; }
		const others = list.filter_area.get().filter(f => !f[4] && f[1] !== config.field).length;
		const route = JSON.stringify(frappe.get_route());
		const signature = JSON.stringify([route, title, config, current, others]);
		if (bar?.dataset.signature === signature) return;
		if (!bar) {
			bar = document.createElement("div");
			bar.className = "tjy-quick-views";
			form.before(bar);
			main.classList.add("tjy-filters-closed");
		}
		bar.dataset.route = route;
		bar.dataset.signature = signature;
		const choices = document.createElement("div");
		choices.className = "tjy-view-choices";
		choices.setAttribute("role", "group");
		choices.setAttribute("aria-label", "按"+config.label+"筛选");
		for (const [value,label] of [["","全部"], ...config.choices]) {
			const b = button(label, "tjy-view-choice");
			b.value = value;
			b.setAttribute("aria-pressed", String(value === current));
			b.onclick = async () => {
				if (bar.dataset.busy) return;
				bar.dataset.busy = "1";
				try { await setChoice(list, config, value); }
				finally { delete bar.dataset.busy; }
			};
			choices.append(b);
		}
		const toggle = button("", "tjy-filter-toggle");
		const caption = "筛选与排序" + (others ? " · "+others : "");
		toggle.setAttribute("aria-label", caption);
		toggle.title = caption;
		const text = document.createElement("span");
		text.className = "tjy-filter-text";
		text.textContent = caption;
		const icon = document.createElement("span");
		icon.className = "tjy-filter-icon";
		icon.setAttribute("aria-hidden", "true");
		icon.innerHTML = frappe.utils.icon("filter","sm");
		toggle.append(icon, text);
		if (!form.id) form.id = "tjy-filters-" + frappe.scrub(list.doctype);
		toggle.setAttribute("aria-controls", form.id);
		toggle.setAttribute("aria-expanded", String(!main.classList.contains("tjy-filters-closed")));
		toggle.onclick = () => {
			const closed = main.classList.toggle("tjy-filters-closed");
			toggle.setAttribute("aria-expanded", String(!closed));
		};
		bar.replaceChildren(choices, toggle);
	}
	function scope(active) {
		const route = JSON.stringify(frappe.get_route());
		for (const bar of document.querySelectorAll(".tjy-quick-views")) {
			if (!active || bar.dataset.route !== route) remove(bar);
		}
	}
	frappe.tjyMealFilters = {render, scope, choicesFor, currentChoice, setChoice};
})();
