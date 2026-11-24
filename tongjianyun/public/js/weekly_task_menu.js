(() => {
	const taskType = "Tongjianyun Meal Weekly Task";
	const weekType = "Meal Planning Week";
	const dayType = "Meal Kitchen Day";
	const titles = { "食谱审核": "本周食谱", "准备采购": "本周采购", "逐餐供餐与日结": "供餐日结", "周核销": "厨房周核销" };
	const menuLabels = ["草稿", "已提交", "已取消"];
	const open = (type, name) => frappe.set_route("Form", type, name);

	function button($parent, label, handler) {
		return $("<button>", { type: "button", class: "btn btn-sm btn-default" })
			.text(label).on("click", handler).appendTo($parent);
	}

	function link($parent, type, name, title) {
		const href = frappe.utils.get_form_link(type, name);
		return $("<a>", { href }).text(title || name).appendTo($parent);
	}

	function note($parent, text) {
		return $("<div>", { class: "text-muted small mt-1" }).text(text).appendTo($parent);
	}

	function weekLabel(date) {
		if (!date) return "";
		const [y, m, d] = date.split("-");
		return `${y}年${Number(m)}月${Number(d)}日当周`;
	}

	function showScope(frm, context) {
		const $scope = frm.fields_dict.scope_summary.$wrapper.empty().addClass("text-muted");
		$scope.text(frm.doc.company || "");
		if (context?.canteen_title) {
			$scope.append(" · ");
			link($scope, "Tongjianyun Canteen", frm.doc.canteen, context.canteen_title);
		}
		if (frm.doc.week_start) $scope.append(" · " + weekLabel(frm.doc.week_start));
		const $id = frm.fields_dict.task_id.$wrapper.empty();
		$("<div>", { class: "control-label" }).text("任务编号").appendTo($id);
		$("<div>", { class: "text-muted" }).text(frm.doc.name).appendTo($id);
		const $field = frm.fields_dict.term_project.$wrapper;
		$field.find(".tjy-task-term").remove();
		if (context?.term_title) {
			const $title = $("<div>", { class: "tjy-task-term small mb-1" }).prependTo($field.find(".control-input-wrapper"));
			link($title, "Tongjianyun Meal Term Project", frm.doc.term_project, context.term_title);
		}
	}

	function confirmMenu(frm, menu) {
		const dialog = new frappe.ui.Dialog({
			title: "确认本周食谱",
			fields: [{ fieldname: "menu", label: "本周食谱", fieldtype: "Select",
				options: [{ label: "", value: "" }, ...menu.options], reqd: 1,
				description: "同一食堂本周的待办任务将同时关联这份食谱。" }],
			primary_action_label: "确认关联",
			async primary_action(values) {
				if (frm.is_dirty()) await frm.save();
				await frappe.call({ method: "tongjianyun.canteen_ops.task_menus.confirm_menu",
					args: { task: frm.doc.name, meal_week: values.menu } });
				dialog.hide();
				await frm.reload_doc();
			}
		});
		dialog.show();
	}

	function showDays($panel, service) {
		if (service.restricted) {
			note($panel, "当前账号无法查看学期供餐安排。");
			return;
		}
		const days = service.days;
		if (!days.length) { note($panel, "本周没有计划供餐日。"); return; }
		const $list = $("<ul>", { class: "list-unstyled mt-2 mb-0", "aria-label": "每日供餐记录" }).appendTo($panel);
		for (const day of days) {
			const $row = $("<li>", { class: "d-flex justify-content-between align-items-center border-top py-2" }).appendTo($list);
			const date = frappe.datetime.str_to_user(day.date);
			if (day.record) link($row, dayType, day.record, date);
			else $("<span>").text(date).appendTo($row);
			$("<span>", { class: "text-muted small" }).text(day.status).appendTo($row);
		}
	}

	function weekSection(menu, section) {
		frappe.tjy_week_task_destination = { name: menu.menu, section };
		return open(weekType, menu.menu);
	}

	function render(frm, $panel, data) {
		const kind = frm.doc.task_kind;
		const menu = data.menu;
		if (frm.doc.generated_by_term && !frm.doc.docstatus && !frm.is_dirty() && ["食谱审核","准备采购"].includes(kind)) {
			const complete = kind==="食谱审核" ? (data.external ? data.published : menu.docstatus===1)
				: ["申请已提交","申请草稿","已关联采购申请","无需采购"].includes(data.procurement?.status);
			frm.page.set_indicator(complete?"已办理":"待办理",complete?"green":"orange");
			frm.page.clear_primary_action();
		}
		$("<h5>", { class: "mb-2" }).text(titles[kind] || "任务办理").appendTo($panel);
		const $bar = $("<div>", { class: "d-flex align-items-center flex-wrap justify-content-between" }).appendTo($panel);
		const $status = $("<div>", { class: "mr-2 my-1" }).appendTo($bar);
		const $actions = $("<div>", { class: "my-1" }).appendTo($bar);
		if (data.external) {
			$status.text(kind==="食谱审核" ? (data.published?"园外菜单已审核":"待审核园外菜单") : `已交接 ${data.accepted} / ${data.total} 餐`);
			if(data.publication) button($actions,"打开供餐菜单",()=>open("Tongjianyun Meal Publication",data.publication));
			else if(!data.published && data.can_publish) button($actions,"建立供餐菜单",()=>frappe.new_doc("Tongjianyun Meal Publication",
				{company:frm.doc.company,canteen:frm.doc.canteen,week_start:frm.doc.week_start}));
			return;
		}
		if (menu.state !== "linked") {
			const labels = { empty: "待编排", ambiguous: "待确认食谱归属", unavailable: "园所本周已有其他食堂的食谱",
				restricted: "当前账号无权查看本周食谱", historical: "这项任务没有关联食谱" };
			$status.text(labels[menu.state]);
			if (menu.state === "empty" && menu.can_create) {
				button($actions, "新建本周食谱", () => frappe.new_doc(weekType, menu.defaults));
			} else if (menu.state === "ambiguous" && menu.can_confirm && menu.options.length) {
				button($actions, "确认食谱归属", () => confirmMenu(frm, menu));
			}
		} else {
			const approved = menu.docstatus === 1;
			if (kind === "食谱审核") {
				$("<strong>").text(menu.title || menu.menu).appendTo($status);
				$("<span>", { class: "small text-muted ml-2" }).text(menuLabels[menu.docstatus]).appendTo($status);
				button($actions, "打开食谱", () => open(weekType, menu.menu));
				if (menu.docstatus === 0 && !frm.doc.docstatus) note($panel, "周食谱提交后可完成审核。");
			} else {
				const purchase = data.procurement;
				let status = menu.docstatus === 2 ? "关联食谱已取消" : "待食谱审核";
				if (approved && purchase) status = purchase.status;
				if (approved && kind === "周核销") status = data.reconciled_at ? "已核销" : "待核销";
				if (approved && data.service) status = "供餐安排";
				if (data.service?.days?.length && !data.service.days.some(day => day.status === "无查看权限")) {
					status = `已日结 ${data.service.days.filter(day => day.status === "已日结").length} / ${data.service.days.length} 天`;
				}
				$("<strong>").text(status).appendTo($status);
				const $source = $("<div>", { class: "small text-muted mt-1" }).appendTo($status);
				link($source, weekType, menu.menu, menu.title);
				$source.append(" · " + menuLabels[menu.docstatus]);
				if (approved && kind === "准备采购") {
					if (purchase.request) button($actions, "打开采购申请", () => open("Material Request", purchase.request));
					else button($actions, "查看采购需求", () => weekSection(menu, "procurement"));
				} else if (approved && kind === "周核销") {
					if (data.reconciled_at) note($status, "核销时间　" + frappe.datetime.str_to_user(data.reconciled_at));
					button($actions, data.reconciled_at ? "查看核销记录" : "查看周核销", () => weekSection(menu, "kitchen"));
				}
			}
		}
		if (data.service) {
			if (menu.state !== "linked" && data.service.days?.length) note($panel, `计划供餐 ${data.service.days.length} 天`);
			showDays($panel, data.service);
		}
	}

	async function refresh(frm) {
		const $panel = frm.fields_dict.menu_panel.$wrapper.empty();
		const docname = frm.doc.name;
		const token = frm.__tjy_menu_token = Symbol();
		showScope(frm);
		if (frm.is_new()) return;
		if (frm.is_dirty()) { note($panel, "保存任务后更新办理信息。"); return; }
		note($panel, "正在读取办理信息…");
		try {
			const { message } = await frappe.call({ method: "tongjianyun.canteen_ops.weekly_task_form.get_context",
				type: "GET", args: { task: docname } });
			if (frm.__tjy_menu_token !== token || frm.doc.name !== docname) return;
			showScope(frm, message);
			render(frm, $panel.empty(), message);
		} catch {
			if (frm.__tjy_menu_token !== token || frm.doc.name !== docname) return;
			note($panel.empty(), "办理信息读取失败。");
			button($panel, "重试", () => refresh(frm));
		}
	}
	frappe.ui.form.on(taskType, { setup(frm) {
		frm.set_query("canteen", () => ({ filters: { company: frm.doc.company, disabled: 0 } }));
		frm.set_query("term_project", () => ({ filters: { company: frm.doc.company, canteen: frm.doc.canteen, docstatus: 1 } }));
	}, refresh, company: refresh, canteen: refresh, week_start: refresh,
		term_project: refresh, task_kind: refresh });
})();
