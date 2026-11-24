(() => {
	const pendingField = "custom_tjy_meal_portions";

	async function openPortions(frm) {
		const dishes = [...new Set(frm.doc.dishes.map((row) => row.bom_no).filter(Boolean))];
		const editor = window.tjyMealPortions;
		const source = { week_name: frm.doc.meal_week, meal_date: frm.doc.meal_date, meal_type: frm.doc.meal_type };
		const pending = JSON.parse(frm.doc[pendingField] || "{}");
		let request = 0;
		let $details;
		const dialog = new frappe.ui.Dialog({
			title: "本餐食材带量",
			size: "large",
			no_submit_on_enter: true,
			fields: [
				{ fieldname: "recipe", fieldtype: "Select", label: "菜品配方", options: dishes,
					default: dishes[0], onchange: refresh },
				{ fieldname: "portions", fieldtype: "HTML" },
			],
			primary_action_label: "应用到变更申请",
			async primary_action() {
				await frm.set_value(pendingField, JSON.stringify(pending));
				dialog.hide();
			},
		});
		$details = dialog.fields_dict.portions.$wrapper;
		dialog.show();
		await refresh();

		async function refresh() {
			if (!$details) return;
			const sequence = ++request;
			const bom_name = dialog.get_value("recipe") || dishes[0];
			$details.text("正在读取带量…");
			try {
				const data = await editor.load({ ...source, bom_name });
				if (sequence !== request) return;
				editor.render($details, data, pending[bom_name], () => Number(frm.doc.target_headcount),
					(changes) => { pending[bom_name] = changes; });
			} catch {
				if (sequence === request) $details.text("带量读取失败，请重新选择配方。");
			}
		}
	}

	frappe.ui.form.on("Meal Plan Adjustment", {
		refresh(frm) {
			if (frm.doc.docstatus || frm.is_new() || !frm.perm?.[0]?.write || !frm.fields_dict[pendingField]) return;
			frm.add_custom_button("调整本餐带量", async () => {
				if (frm.doc.service_suspended || !frm.doc.dishes?.some((row) => row.bom_no)) {
					return frappe.msgprint("请选择正常供餐的菜品后调整带量。");
				}
				await frappe.require(window.tjyMealPortions.stylesheet);
				await openPortions(frm);
			});
		},
	});
})();
