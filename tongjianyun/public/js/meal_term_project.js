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

	const weeklyTask = "Tongjianyun Meal Weekly Task";
	const proofs = ["本周周食谱已审核提交。", "已生成采购申请，或库存核对结果显示无需采购。",
		"本周每个供餐日均已完成厨房日结。", "本周厨房已完成周核销。"];
	const pageSize = 6;

	function button($parent, label, handler, style = "btn-default") {
		return $("<button>", { type: "button", class: `btn btn-xs ${style} mr-2` })
			.text(label).on("click", handler).appendTo($parent);
	}

	function openDays(row) {
		if (row.kitchen_days?.length === 1) return openForm(dayType, row.kitchen_days[0]);
		if (!row.kitchen_days?.length) return null;
		return () => {
			frappe.route_options = { name: ["in", row.kitchen_days] };
			frappe.set_route("List", dayType);
		};
	}

	function drawWeeks(frm, $panel, weeks, draft, page = 0) {
		$panel.empty();
		const first = page * pageSize;
		const pageRows = weeks.slice(first, first + pageSize);
		if (!pageRows.length) {
			$panel.text("所选日期内没有供餐周。");
			return;
		}
		const completed = weeks.filter(row => row.steps.every(step => step.complete)).length;
		$("<p>", { class: "text-muted mb-2" }).text(draft ? "预计截止日" : `已完成 ${completed} / ${weeks.length} 周`).appendTo($panel);
		const $table = $("<table>", { class: "table table-sm", "aria-label": "每周膳食任务" })
			.appendTo($("<div>", { class: "table-responsive" }).appendTo($panel));
		const $head = $("<tr>").appendTo($("<thead>").appendTo($table));
		labels.forEach(label => $("<th>", { scope: "col", class: "text-nowrap" }).text(label).appendTo($head));
		const $body = $("<tbody>").appendTo($table);
		const $detail = $("<div>", { class: "mt-3", role: "status" });
		pageRows.forEach((row, i) => {
			const $line = $("<tr>").appendTo($body);
			const title = `第 ${first + i + 1} 周`;
			const $week = $("<th>", { scope: "row", class: "text-nowrap" }).text(title).appendTo($line);
			$("<div>", { class: "text-muted small" }).text(row.first.slice(5) + " 至 " + row.last.slice(5)).appendTo($week);
			row.steps.forEach((step, index) => {
				const $cell = $("<td>", { class: "align-middle text-nowrap" }).appendTo($line);
				const label = draft ? step.due.slice(5) : step.status;
				const $btn = button($cell, label, () => {
					$detail.empty();
					$("<strong>").text(title + " · " + step.kind).appendTo($detail);
					$("<div>", { class: "my-1" }).text(`责任人　${step.assigned_to || frm.doc.responsible_user || "待选择"}　　截止　${step.due}`).appendTo($detail);
					$("<p>", { class: "text-muted mb-2" }).text(proofs[index]).appendTo($detail);
					if (step.task) button($detail, "打开每周任务", openForm(weeklyTask, step.task));
					if (row.week) button($detail, "打开周食谱", openForm(weekType, row.week));
					if (index === 1 && row.request) button($detail, "打开采购申请", openForm("Material Request", row.request));
					if (index === 2 && openDays(row)) button($detail, "查看日结", openDays(row));
				}, step.complete ? "btn-success" : "btn-default");
				$btn.attr("aria-label", title + " " + step.kind + " " + label);
			});
		});
		if (weeks.length > pageSize) {
			const $pager = $("<div>", { class: "d-flex align-items-center" }).appendTo($panel);
			$("<span>", { class: "text-muted mr-auto" }).text(`第 ${first + 1}–${first + pageRows.length} 周，共 ${weeks.length} 周`).appendTo($pager);
			button($pager, "上一页", () => drawWeeks(frm, $panel, weeks, draft, page - 1)).prop("disabled", !page);
			button($pager, "下一页", () => drawWeeks(frm, $panel, weeks, draft, page + 1)).prop("disabled", first + pageRows.length >= weeks.length);
		}
		$detail.appendTo($panel);
	}

	async function refresh(frm) {
		const $container = frm.fields_dict.week_progress?.$wrapper;
		const $summary = frm.fields_dict.task_summary?.$wrapper;
		if (!$container?.length || !$summary?.length) return;
		const $panel = $("<div>").appendTo($container.empty());
		const $bar = $("<div>", { class: "d-flex align-items-center flex-wrap my-2" }).appendTo($summary.empty());
		const message = text => { $bar.text(text); $panel.text(text); };
		const doc = frm.doc;
		const draft = doc.docstatus === 0;
		if (draft && !(doc.company && doc.from_date && doc.to_date)) {
			message("选择园所和起止日期后可预览每周任务。");
			return;
		}
		if (draft && doc.from_date > doc.to_date) {
			message("结束日期须晚于或等于起始日期。");
			return;
		}
		message("正在读取每周任务…");
		try {
			const data = draft ? (await frappe.call({ method: "tongjianyun.canteen_ops.term_schedule.preview", type: "GET",
				args: { company: doc.company, from_date: doc.from_date, to_date: doc.to_date, holiday_list: doc.service_holiday_list || null } })).message :
				await call("progress", frm);
			if (frm.doc !== doc || !$panel.parent().length) return;
			const count = draft ? data.weeks.reduce((n, w) => n + w.steps.length, 0) : data.task_count;
			$bar.empty();
			$("<span>", { class: "mr-3" }).text(`${data.weeks.length} 个供餐周 · ${draft ? "预计生成" : "每周任务"} ${count} 项`).appendTo($bar);
			button($bar, "查看每周安排", () => frm.layout.select_tab("week_progress_section"), "btn-link");
			drawWeeks(frm, $panel, data.weeks, draft);
			if (data.project) frm.add_custom_button("打开管理项目", openForm("Project", data.project));
		} catch {
			if (frm.doc !== doc || !$panel.parent().length) return;
			message("读取每周任务失败。");
			button($panel, "重试", () => refresh(frm));
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
		company: refresh,
		on_submit(frm) {
			frm.layout.select_tab("week_progress_section");
		},
		from_date: refresh,
		to_date: refresh,
		service_holiday_list: refresh,
		refresh(frm) {
			const state = frm.doc.name + "/" + frm.doc.docstatus;
			if (frm.doc.docstatus === 1 && frm.__term_view !== state && window.location.hash !== "#term_details") {
				frm.layout.select_tab("week_progress_section");
			}
			frm.__term_view = state;
			if (frm.doc.docstatus === 0 && frm.perm?.[0]?.submit && !frappe.model.has_workflow(doctype)) {
				if (frm.is_new() || frm.is_dirty()) {
					frm.add_custom_button("提交并生成任务", async () => {
						if (frm.is_new() || frm.is_dirty()) await frm.save();
						if (!frm.is_new() && !frm.is_dirty() && frm.doc.docstatus === 0) return frm.savesubmit();
					});
				} else if (frm.toolbar.get_action_status() === "Submit") {
					frm.page.set_primary_action("提交并生成任务", () => frm.savesubmit(), "check");
				}
			}
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
