(() => {
	const label = "专项食材预览";
	const api = "tongjianyun.special_ingredients.";
	const endpoint = (frm, method, extra = {}) => frappe.call({
		method: api + method,
		args: { doctype: frm.doctype, name: frm.doc.name, ...extra },
		type: method === "confirm_count" ? "POST" : "GET",
		freeze: method === "confirm_count",
	});

	function text($parent, message, className = "text-muted mb-2") {
		return $("<div>", { class: className }).text(message).appendTo($parent);
	}

	function confirmCount(frm, review, reload) {
		const dialog = new frappe.ui.Dialog({
			title: `核对专项人数 · ${review.date} ${review.meal_type}`,
			fields: [
				{ fieldname: "count", label: "确认专项计划人数", fieldtype: "Int", reqd: 1,
					description: `可确认范围 ${review.minimum}–${review.maximum} 人` },
				{ fieldname: "reason", label: "核对依据", fieldtype: "Small Text", reqd: 1,
					description: "填写班级或人数核对依据。" },
			],
			primary_action_label: "保存核对",
			async primary_action(values) {
				await endpoint(frm, "confirm_count", {
					date: review.date, meal_type: review.meal_type, count: String(values.count), reason: values.reason,
					proof: review.proof,
				});
				dialog.hide();
				await reload();
			},
		});
		dialog.show();
	}

	function render($body, data, frm, reload) {
		$body.empty();
		if (!data.active) {
			text($body, "本次供餐暂未启用营养改善计划。");
			return;
		}
		text($body, data.approved ? "已审核的专项归属依据" : "按周食谱的计划供餐人数计算");
		for (const item of data.blockers || []) text($body, item, "text-danger mb-2");
		for (const review of data.reviews || []) {
			const $row = $("<div>", { class: "d-flex align-items-center mb-2" }).appendTo($body);
			$("<span>", { class: "mr-2" }).text(`${review.date} ${review.meal_type} · 专项人数待核对`).appendTo($row);
			if (frm.perm?.[0]?.write) {
				$("<button>", { type: "button", class: "btn btn-xs btn-default" }).text("核对人数")
					.on("click", () => confirmCount(frm, review, reload)).appendTo($row);
			}
		}
		if (data.adjustment_draft) {
			text($body, "单餐变更审核时按新配方和确认人数计算专项用量。");
			return;
		}
		if (!data.rows.length) {
			text($body, "暂无食材需求明细。");
			return;
		}
		text($body, "专项与普通需求按库存单位显示。合计拟采购量沿用本餐原生采购计算结果。");
		const headers = ["供餐日期", "餐次", "食材", "计划人数", "专项人数", "专项需求量", "普通需求量", "库存单位",
			"合计拟采购量", "采购单位", "归属", "核对依据"];
		const $scroll = $("<div>", { class: "table-responsive", style: "max-height: 55vh; overflow: auto" }).appendTo($body);
		const $table = $("<table>", { class: "table table-bordered table-sm" }).appendTo($scroll);
		const $head = $("<tr>").appendTo($("<thead>").appendTo($table));
		for (const heading of headers) $("<th>", { scope: "col" }).text(heading).appendTo($head);
		const $rows = $("<tbody>").appendTo($table);
		for (const row of data.rows) {
			const $row = $("<tr>").appendTo($rows);
			const values = [row.meal_date, row.meal_type, row.item_name || row.item_code, row.planned_people, row.eligible_people,
				row.special_qty, row.ordinary_qty, row.stock_uom, row.purchase_qty, row.purchase_uom,
				row.special_status, row.reason];
			for (const value of values) $("<td>").text(value ?? "—").appendTo($row);
		}
	}

	function open(frm) {
		if (frm.is_dirty()) {
			frappe.msgprint("请先保存当前表单。");
			return;
		}
		const name = frm.doc.name;
		const dialog = new frappe.ui.Dialog({
			title: label, size: "extra-large", fields: [{ fieldname: "content", fieldtype: "HTML" }],
		});
		const $body = dialog.fields_dict.content.$wrapper;
		async function reload() {
			if (frm.doc.name !== name) return;
			text($body.empty(), "正在读取专项归属…");
			try {
				const { message } = await endpoint(frm, "preview");
				if (frm.doc.name === name) render($body, message, frm, reload);
			} catch {
				text($body.empty(), "专项食材预览读取失败，请先核对供餐和采购资料。");
			}
		}
		dialog.show();
		reload();
	}

	for (const doctype of ["Meal Planning Week", "Meal Plan Adjustment"]) {
		frappe.ui.form.on(doctype, {
			async refresh(frm) {
				if (frm.is_new() || frm.doc.docstatus === 2 || (doctype === "Meal Planning Week" && !frm.doc.meals?.length)) return;
				const name = frm.doc.name;
				const { message } = await endpoint(frm, "availability");
				if (message && frm.doc.name === name) frm.add_custom_button(label, () => open(frm));
			},
		});
	}
})();
