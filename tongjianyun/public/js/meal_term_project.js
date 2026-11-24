(() => {
	const doctype = "Tongjianyun Meal Term Project";
	const weekType = "Meal Planning Week";
	const dayType = "Meal Kitchen Day";
	const labels = ["供餐周", "食谱审核", "准备采购", "逐餐供餐与日结", "周核销"];

	async function call(method, frm, type = "GET") {
		const response = await frappe.call({
			method: `tongjianyun.canteen_ops.term_projects.${method}`,
			args: { term_project: frm.doc.name }, type, freeze: type === "POST",
		});
		if (response.exc || !response.message) throw new Error("学期项目操作失败。");
		return response.message;
	}

	function openForm(doctype, name) {
		return () => frappe.set_route("Form", doctype, name);
	}

	function status($cell, label, state, action) {
		const css = `indicator-pill ${state ? "green" : "gray"}`;
		if (action) {
			$("<button>", { type: "button", class: "btn btn-link btn-xs p-0", "aria-label": label })
				.on("click", action).appendTo($cell).append($("<span>", { class: css }).text(label));
		} else {
			$("<span>", { class: css }).text(label).appendTo($cell);
		}
	}

	function openDays(row) {
		if (row.kitchen_days.length === 1) return openForm(dayType, row.kitchen_days[0]);
		if (!row.kitchen_days.length) return row.week ? openForm(weekType, row.week) : null;
		return () => {
			frappe.route_options = { name: ["in", row.kitchen_days] };
			frappe.set_route("List", dayType);
		};
	}

	function render($panel, data) {
		$panel.empty();
		const completed = data.weeks.filter((row) => row.steps.every((step) => step.complete)).length;
		$("<p>", { class: "text-muted mb-3", role: "status" })
			.text(`已完成 ${completed} / ${data.weeks.length} 周`).appendTo($panel);
		const $table = $("<table>", { class: "table table-sm", "aria-label": "学期膳食按周进度" })
			.appendTo($("<div>", { class: "table-responsive" }).appendTo($panel));
		const $head = $("<tr>").appendTo($("<thead>").appendTo($table));
		for (const label of labels) $("<th>", { scope: "col", class: "text-nowrap" }).text(label).appendTo($head);
		const $body = $("<tbody>").appendTo($table);
		for (const row of data.weeks) {
			const $line = $("<tr>").appendTo($body);
			$("<th>", { scope: "row", class: "text-nowrap" }).text(row.monday).appendTo($line);
			const week = row.week ? openForm(weekType, row.week) : null;
			const actions = [week, row.request ? openForm("Material Request", row.request) : week, openDays(row), week];
			row.steps.forEach((step, index) => {
				status($("<td>", { class: "text-nowrap" }).appendTo($line), step.status, step.complete, actions[index]);
			});
		}
	}

	async function refresh(frm) {
		const $container = frm.fields_dict.week_progress?.$wrapper;
		if (frm.is_new() || !$container?.length) return;
		const name = frm.doc.name;
		const $panel = $("<div>").appendTo($container.empty());
		$("<p>", { class: "text-muted", role: "status" }).text("正在读取每周进度…").appendTo($panel);
		try {
			const data = await call("progress", frm);
			if (frm.doc.name !== name || !$panel.parent().length) return;
			render($panel, data);
			if (data.project) frm.add_custom_button("打开管理项目", openForm("Project", data.project));
		} catch {
			if (frm.doc.name !== name || !$panel.parent().length) return;
			$("<p>", { class: "text-muted", role: "status" }).text("进度读取失败。").appendTo($panel.empty());
			$("<button>", { type: "button", class: "btn btn-default btn-xs" }).text("重试")
				.on("click", () => refresh(frm)).appendTo($panel);
		}
	}

	async function updateProject(frm, method, message) {
		if (frm.is_dirty()) return frappe.msgprint("请先保存表单修改。");
		await call(method, frm, "POST");
		frappe.show_alert(message);
		await frm.reload_doc();
	}

	frappe.ui.form.on(doctype, {
		setup(frm) {
			frm.set_query("management_project", () => ({
				filters: { company: frm.doc.company, status: ["!=", "Cancelled"] },
			}));
		},
		async management_project(frm) {
			if (!frm.is_new() || !frm.doc.management_project) return;
			const { name, management_project: project } = frm.doc;
			const { message } = await frappe.db.get_value("Project", project, [
				"project_name", "expected_start_date", "expected_end_date",
			]);
			if (!message || frm.doc.name !== name || frm.doc.management_project !== project) return;
			const defaults = {};
			if (!frm.doc.project_title && message.project_name) defaults.project_title = message.project_name;
			if (!frm.doc.from_date && message.expected_start_date) defaults.from_date = message.expected_start_date;
			if (!frm.doc.to_date && message.expected_end_date) defaults.to_date = message.expected_end_date;
			await frm.set_value(defaults);
		},
		refresh(frm) {
			if (frm.doc.docstatus === 1 && frm.perm?.[0]?.write) {
				if (frm.doc.management_project) {
					frm.add_custom_button("同步管理项目任务", () => updateProject(frm, "sync_management_tasks", "管理项目任务已同步"));
				} else if (frappe.boot.user.can_create?.includes("Project") || frappe.session.user === "Administrator") {
					frm.add_custom_button("生成并关联管理项目", () => updateProject(frm, "create_project", "管理项目已关联"));
				}
			}
			return refresh(frm);
		},
	});
})();
