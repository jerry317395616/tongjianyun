(() => {
	const task = "Tongjianyun Meal Weekly Task";
	const week = "Meal Planning Week";
	const method = "tongjianyun.canteen_ops.task_menus.";

	async function refresh(frm) {
		const $panel = frm.fields_dict.menu_panel.$wrapper.empty();
		const docname = frm.doc.name;
		const token = frm.__tjy_menu_token = Symbol();
		$("<div>", { class: "control-label mb-2" }).text("本周食谱").appendTo($panel);
		const $row = $("<div>", { class: "d-flex flex-wrap align-items-center mb-3", role: "status" }).appendTo($panel);
		const say = text => $("<span>", { class: "text-muted mr-2" }).text(text).appendTo($row);
		const button = (label, click) => $("<button>", { type: "button", class: "btn btn-xs btn-default" })
			.text(label).on("click", click).appendTo($row);
		if (frm.is_new() || frm.is_dirty()) {
			say("保存任务后显示本周食谱");
			return;
		}
		const { message: info } = await frappe.call({ method: method + "menu_context", type: "GET", args: { task: docname } });
		if (frm.__tjy_menu_token !== token || frm.doc.name !== docname || !info) return;
		if (info.state === "linked") {
			$("<strong>", { class: "mr-2" }).text(info.title || info.menu).appendTo($row);
			say(["草稿", "已提交", "已取消"][info.docstatus]);
			button("打开食谱", () => frappe.set_route("Form", week, info.menu));
		} else if (info.state === "empty") {
			say("待编排");
			if (info.can_create) button("新建本周食谱", () => frappe.new_doc(week, info.defaults));
		} else if (info.state === "ambiguous") {
			say("待确认 · 请核对本食堂使用的周食谱");
			if (info.can_confirm && info.options.length) button("确认食谱归属", () => {
				const dialog = new frappe.ui.Dialog({
					title: "确认本周食谱",
					fields: [{ fieldname: "menu", label: "本周食谱", fieldtype: "Select",
						options: [{ label: "", value: "" }, ...info.options], reqd: 1,
						description: "确认后，同一食堂本周所有待办膳食任务都会关联这份食谱。" }],
					primary_action_label: "确认关联",
					async primary_action(values) {
						await frappe.call({ method: method + "confirm_menu", args: { task: docname, meal_week: values.menu } });
						dialog.hide();
						await frm.reload_doc();
					}
				});
				dialog.show();
			});
		} else {
			say({ unavailable: "园所本周已有食谱，与本食堂归属不符", restricted: "已关联 · 当前账号无权查看食谱",
				historical: "此任务没有关联食谱" }[info.state]);
		}
	}
	frappe.ui.form.on(task, { refresh, company: refresh, canteen: refresh, week_start: refresh });
})();
