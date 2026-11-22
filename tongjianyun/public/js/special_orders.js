(() => {
	const menu = "采购操作";
	const useField = "custom_tjy_meal_purchase_use";
	const planField = "custom_tjy_purchase_nutrition_plan";
	const roles = ["System Manager", "Purchase Manager", "膳食业务经办员"];
	const canPurchase = () => roles.some((role) => frappe.user.has_role(role));
	const call = async (method, args, write = false) => {
		const response = await frappe.call({
			method: `tongjianyun.special_orders.${method}`, args, type: write ? "POST" : "GET", freeze: write,
		});
		return response.message;
	};

	function notice($parent, content) {
		return $("<p>", { class: "text-muted mb-2" }).text(content).appendTo($parent);
	}

	function table($parent, headers) {
		const $scroll = $("<div>", { class: "table-responsive", style: "max-height: 55vh; overflow: auto" }).appendTo($parent);
		const $table = $("<table>", { class: "table table-bordered table-sm" }).appendTo($scroll);
		const $head = $("<tr>").appendTo($("<thead>").appendTo($table));
		headers.forEach((column) => $("<th>", { scope: "col" }).text(column).appendTo($head));
		return $("<tbody>").appendTo($table);
	}

	function openOrder(args, rows) {
		const payable = rows.filter((row) => Number(row.remaining) > 0);
		if (!payable.length) {
			frappe.msgprint("当前没有可生成订单的申请明细。");
			return;
		}
		const groups = new Map();
		for (const row of payable) {
			const key = row[planField] ? `${row[useField]} · ${row[planField]}` : row[useField];
			if (!groups.has(key)) groups.set(key, []);
			groups.get(key).push(row);
		}
		let selection = new Set();
		const dialog = new frappe.ui.Dialog({
			title: "分用途生成采购订单",
			size: "extra-large",
			fields: [
				{ fieldname: "group", label: "采购用途", fieldtype: "Select", options: [...groups.keys()],
					default: groups.keys().next().value, reqd: 1, onchange: refreshLines },
				{ fieldname: "supplier", label: "供应商", fieldtype: "Link", options: "Supplier", reqd: 1,
					get_query: () => ({ filters: { disabled: 0 } }) },
				{ fieldname: "lines", fieldtype: "HTML" },
			],
			primary_action_label: "生成订单草稿",
			async primary_action(values) {
				if (!selection.size) return frappe.msgprint("请选择本次下单的明细。");
				const result = await call("create_order", {
					...args, supplier: values.supplier, purpose: groups.get(values.group)[0][useField],
					selected: [...selection],
				}, true);
				dialog.hide();
				frappe.set_route("Form", "Purchase Order", result.purchase_order);
			},
		});
		function refreshLines() {
			if (!dialog.fields_dict.lines) return;
			const $content = dialog.fields_dict.lines.$wrapper.empty();
			const rows = groups.get(dialog.get_value("group")) || [];
			selection = new Set(rows.map((row) => row.name));
			const $body = table($content, ["本次下单", "食材", "供餐日期", "申请量", "剩余可采购", "采购单位"]);
			for (const row of rows) {
				const $line = $("<tr>").appendTo($body);
				$("<input>", { type: "checkbox", "aria-label": row.item_name || row.item_code }).prop("checked", true)
					.on("change", (event) => event.target.checked ? selection.add(row.name) : selection.delete(row.name))
					.appendTo($("<td>").appendTo($line));
				[row.item_name || row.item_code, row.schedule_date, row.qty, row.remaining, row.uom]
					.forEach((value) => $("<td>").text(value).appendTo($line));
			}
		}
		dialog.show();
		refreshLines();
	}

	async function openPreview(frm, args) {
		if (frm.is_dirty()) return frappe.msgprint("请先保存当前表单。");
		const data = await call("preview", args);
		if (!data.active) return frappe.msgprint("本次没有待办理的专项采购明细。");
		const dialog = new frappe.ui.Dialog({
			title: "专项拆单预览", size: "extra-large", fields: [{ fieldname: "content", fieldtype: "HTML" }],
		});
		const $content = dialog.fields_dict.content.$wrapper;
		notice($content, "先核对专项和普通的专用覆盖量，再按剩余需求分摊可共用的覆盖量。合计采购量沿用原申请。");
		const editable = !data.saved && (data.request_status === 0 || data.request_status == null);
		const $body = table($content, ["供餐日期", "餐次", "食材", "专项需求", "普通需求", "合计覆盖", "库存单位",
			"专项专用覆盖", "普通专用覆盖",
			"合计采购量", "专项采购量", "普通采购量", "采购单位", "核对依据"]);
		const decisions = [];
		for (const row of data.rows) {
			const $line = $("<tr>").appendTo($body);
			[row.meal_date, row.meal_type, row.item_name || row.item_code, row.special_required, row.ordinary_required,
				row.covered, row.stock_uom, row.purchase_qty].forEach((value) => $("<td>").text(value).appendTo($line));
			const $total = $line.children().last();
			const $specialCoverage = $("<td>").insertBefore($total);
			const $ordinaryCoverage = $("<td>").insertBefore($total);
			const $special = $("<td>").appendTo($line);
			const $ordinary = $("<td>").text(row.ordinary_purchase ?? row.suggested_ordinary).appendTo($line);
			$("<td>").text(row.purchase_uom).appendTo($line);
			const $reason = $("<td>").appendTo($line);
			if (editable && row.review_required) {
				const $qty = $("<input>", { type: "number", class: "form-control input-xs", min: 0, max: row.purchase_qty,
					step: row.step, "aria-label": `${row.item_name}专项采购量` }).val(row.suggested_special).appendTo($special);
				const $note = $("<input>", { type: "text", class: "form-control input-xs",
					placeholder: "库存分配或取整依据", "aria-label": `${row.item_name}核对依据` }).appendTo($reason);
				const precision = row.step.split(".")[1]?.length ?? 0;
				const updateOrdinary = () => $ordinary.text((Number(row.purchase_qty) - Number($qty.val())).toFixed(precision));
				const coverageInput = ($cell, name) => $("<input>", {
					type: "number", class: "form-control input-xs", min: 0, max: row.covered, step: "any",
					"aria-label": `${row.item_name}${name}`,
				}).val(0).appendTo($cell);
				const $sc = coverageInput($specialCoverage, "专项专用覆盖");
				const $oc = coverageInput($ordinaryCoverage, "普通专用覆盖");
				function propose() {
					const special = Number(row.special_required) - Number($sc.val());
					const ordinary = Number(row.ordinary_required) - Number($oc.val());
					if (special < 0 || ordinary < 0 || special + ordinary <= 0) return;
					$qty.val((Number(row.purchase_qty) * special / (special + ordinary)).toFixed(precision));
					updateOrdinary();
				}
				$sc.add($oc).on("input", propose);
				$qty.on("input", updateOrdinary);
				decisions.push([row.key, $qty, $note, $sc, $oc]);
			} else {
				$special.text(row.special_purchase ?? row.suggested_special);
				$specialCoverage.text(row.special_covered ?? "—");
				$ordinaryCoverage.text(row.ordinary_covered ?? "—");
				$reason.text(row.reason || "—");
			}
		}
		if (editable) {
			dialog.set_primary_action("保存拆分申请", async () => {
				const values = Object.fromEntries(decisions.map(([key, qty, note, special, ordinary]) => [key, {
					special_purchase: qty.val(), reason: note.val(), special_covered: special.val(), ordinary_covered: ordinary.val(),
				}]));
				const result = await call("apply_split", { ...args, preview_hash: data.proof, decisions: values }, true);
				dialog.hide();
				frappe.set_route("Form", "Material Request", result.material_request);
			});
		} else if (data.saved && data.request_status === 1) {
			dialog.set_primary_action("生成采购订单草稿", async () => {
				const source = { week_name: args.week_name, material_request: data.request };
				const rows = await call("order_options", source);
				dialog.hide();
				openOrder(source, rows);
			});
		} else if (data.request_status === 1) {
			notice($content, "该申请已提交。请按原采购流程处理已有申请及后续订单。");
		}
		dialog.show();
	}

	for (const doctype of ["Meal Planning Week", "Meal Plan Adjustment"]) {
		frappe.ui.form.on(doctype, {
			async refresh(frm) {
				if (frm.doc.docstatus !== 1 || !canPurchase()) return;
				const name = frm.doc.name;
				const adjustment = doctype === "Meal Plan Adjustment";
				if (adjustment && !frm.doc.material_request) return;
				const args = adjustment
					? { week_name: frm.doc.meal_week, material_request: frm.doc.material_request }
					: { week_name: name };
				const { message: active } = await frappe.call({
					method: "tongjianyun.special_ingredients.availability",
					args: { doctype, name }, type: "GET",
				});
				if (frm.doc.name !== name || !active) return;
				frm.add_custom_button("专项拆单预览", () => openPreview(frm, args).catch(() => {}), menu);
			},
		});
	}
})();
