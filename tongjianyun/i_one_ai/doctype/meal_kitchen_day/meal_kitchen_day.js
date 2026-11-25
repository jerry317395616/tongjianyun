(() => {
	const esc = (value) => frappe.utils.escape_html(String(value ?? ""));
	const canOperate = () => ["System Manager", "Stock Manager", "Stock User", "膳食业务经办员"].some((role) => frappe.user.has_role(role));
	const number = (value) => {
		if (value === null || value === undefined || value === "") return "—";
		const result = Number(value);
		return Number.isFinite(result) ? result.toLocaleString("zh-CN", { maximumFractionDigits: 9 }) : String(value);
	};
	const closingQty = (row) => row.carry_out_qty ?? row.balance_qty;
	const allowed = (row, action) => Array.isArray(row.allowed_actions)
		? row.allowed_actions.includes(action) && (action !== "领用" || row.can_issue !== false)
		: action !== "领用" || row.can_issue !== false;

	function saved(frm) {
		if (frm.is_new() || frm.is_dirty()) frappe.throw(__("请先保存实际供餐记录，再执行库存操作。"));
	}

	async function call(frm, button, method, args, callback) {
		if (frm.__meal_kitchen_busy) return;
		try {
			saved(frm);
			frm.__meal_kitchen_busy = true;
			button?.prop("disabled", true);
			const response = await frappe.call({ method, args, freeze: true, freeze_message: __("正在核对厨房执行记录…") });
			if (response.exc) throw new Error(__("操作失败，请查看服务器提示。"));
			await callback?.(response.message);
		} catch (error) {
			if (!error?._server_messages && !error?.responseJSON?._server_messages) {
				frappe.msgprint({ title: __("操作未完成"), indicator: "red", message: esc(error?.message || "请求失败，请检查连接和权限后重试。") });
			}
		} finally {
			frm.__meal_kitchen_busy = false;
			button?.prop("disabled", false);
		}
	}

	function renderLedger(frm, ledger) {
		const wrapper = frm.fields_dict.ledger_html?.$wrapper;
		if (!wrapper) return;
		const rows = Array.isArray(ledger?.rows) ? ledger.rows : [];
		const entries = Array.isArray(ledger?.stock_entries) ? ledger.stock_entries : [];
		const blockers = Array.isArray(ledger?.blockers) ? ledger.blockers : [];
		const historical = frm.doc.docstatus === 1;
		const cells = rows.map((row) => `<tr><td>${esc(row.item_name || row.item_code)}${Number(row.planned_qty) === 0 && Number(row.opening_qty) > 0
			? `<div class="text-muted small">${esc("今日无计划，来自期初留存")}</div>` : ""}</td><td>${esc(row.stock_uom)}</td>${[
			row.planned_qty, row.opening_qty, row.issued_qty, row.consumed_qty, row.returned_qty, row.loss_qty, closingQty(row),
		].map((value) => `<td class="text-right">${esc(number(value))}</td>`).join("")}</tr>`).join("");
		const links = entries.map((entry) => {
			const status = { 0: "草稿，未计入余额", 1: "已提交", 2: "已取消" }[Number(entry.docstatus)] || "待核对";
			return `<li><a href="/desk/stock-entry/${encodeURIComponent(entry.name)}">${esc(entry.name)}</a> · ${esc(entry.action)} · ${esc(entry.posting_date)} · ${esc(status)}</li>`;
		}).join("");
		const carryMessage = ledger?.carry_required
			? ledger?.carry_confirmation_current
				? "本日正结存已按当前流水逐项实盘确认。"
				: "本日有食材余料留厨，请逐项输入真实清点数量并确认；库存、人数或说明改变后须重新清点。"
			: "本日没有正结存，无需额外余料确认；五餐实际人数和库存流水仍须核对。";
		const opening = ledger?.opening_day?.day_name;
		wrapper.html(`<p class="text-muted">下列数量均为食材库存单位。期初留存＋本日领用－耗用－退料－损耗＝期末留存；只计已提交流水。食材留在厨房不另造移库或入库。</p>
			${historical ? `<p class="text-muted">${esc("这是当日结存记录，后续日期可能已继续使用，不能据此认定当前厨房可用量。")}</p>` : ""}
			${opening ? `<p>${esc("期初来源日结：")}<a href="/desk/meal-kitchen-day/${encodeURIComponent(opening)}">${esc(opening)}</a></p>` : ""}
			${blockers.length ? `<div class="alert alert-warning"><ul style="margin-bottom:0">${blockers.map((value) => `<li>${esc(value)}</li>`).join("")}</ul></div>` : ""}
			${ledger?.has_drafts ? '<p class="text-warning">存在未处理的库存单草稿，请先核对再日结。</p>' : ""}
			<div style="overflow-x:auto"><table class="table table-bordered table-condensed"><thead><tr><th>食材</th><th>单位</th><th>本日计划</th><th>期初留存</th><th>本日领用</th><th>本日耗用</th><th>本日退料</th><th>本日损耗</th><th>期末留存${historical ? "（当日记录）" : ""}</th></tr></thead>
			<tbody>${cells || '<tr><td colspan="9">暂无计划或期初留存食材。</td></tr>'}</tbody></table></div>
			<p class="${ledger?.carry_required && !ledger?.carry_confirmation_current ? "text-warning" : "text-muted"}">${esc(carryMessage)}</p>
			<p>${ledger?.can_close ? "本日实际人数、库存操作与留存已核对，可交由另一位授权审核人提交日结。" : "请完成实际人数、库存草稿和余料清点核对后提交日结。"}</p>
			<strong>关联原生库存单</strong><ul>${links || "<li>尚无关联库存单。</li>"}</ul>`);
		frm.__meal_kitchen_ledger = ledger;
	}

	function openAction(frm, action, ledger, button) {
		if (frm.__meal_kitchen_dialog_open) return;
		const rows = (Array.isArray(ledger?.rows) ? ledger.rows : []).filter((row) => allowed(row, action));
		if (!rows.length) return frappe.msgprint(__("本日没有可操作食材。"));
		frm.__meal_kitchen_dialog_open = true;
		const data = rows.map((row) => ({ item_code: row.item_code, item_name: row.item_name,
			stock_uom: row.stock_uom, balance_qty: closingQty(row), qty: 0 }));
		const dialog = new frappe.ui.Dialog({
			title: __(`创建${action}库存单草稿`), size: "extra-large",
			fields: [
				{ fieldname: "notice", fieldtype: "HTML", options: `<p>${esc("请填写本次实际操作量，未填写或零数量的食材不会加入单据。所有数量均为该食材库存单位；生成后须在原生库存单中审核提交。")} ${esc(action === "领用" ? "仅列出本日允许领用的计划食材，从原料仓调拨到厨房仓。" : "系统按已核实的领用来源分配，包括允许使用的期初余料；不能重复退料、耗用或损耗。")}</p>` },
				{ fieldname: "items", fieldtype: "Table", label: __("本次操作食材"), in_place_edit: true, cannot_add_rows: true, cannot_delete_rows: true, data,
					fields: [
						{ fieldname: "item_code", fieldtype: "Link", label: __("食材"), options: "Item", read_only: 1, in_list_view: 1 },
						{ fieldname: "item_name", fieldtype: "Data", label: __("名称"), read_only: 1, in_list_view: 1 },
						{ fieldname: "stock_uom", fieldtype: "Data", label: __("库存单位"), read_only: 1, in_list_view: 1 },
						{ fieldname: "balance_qty", fieldtype: "Float", label: __("当前可用留存"), read_only: 1, in_list_view: 1, precision: 9 },
						{ fieldname: "qty", fieldtype: "Float", label: __("本次操作量"), in_list_view: 1, non_negative: 1, precision: 6 },
					] },
				{ fieldname: "reason", fieldtype: "Small Text", label: __("操作说明"), reqd: action === "损耗" ? 1 : 0 },
			],
			onhide() { frm.__meal_kitchen_dialog_open = false; },
			primary_action_label: __("生成库存单草稿"),
			primary_action(values) {
				if (frm.__meal_kitchen_busy) return;
				const items = (values.items || []).filter((row) => Number(row.qty) > 0).map((row) => ({ item_code: row.item_code, qty: row.qty }));
				if (!items.length) return frappe.msgprint(__("请至少填写一项正数操作量。"));
				dialog.get_primary_btn().prop("disabled", true);
				return call(frm, button, "tongjianyun.meal_kitchen.create_kitchen_stock_entry", {
					day_name: frm.doc.name, action, items, reason: values.reason || "",
				}, async (result) => {
					if (!result?.stock_entry) throw new Error(__("未返回库存单编号，请刷新流水核对。"));
					dialog.hide();
					await frm.reload_doc();
					frappe.set_route("Form", "Stock Entry", result.stock_entry);
				}).finally(() => dialog.get_primary_btn().prop("disabled", false));
			},
		});
		dialog.show();
	}

	function invalidateCarryView(frm) {
		frm.__meal_kitchen_ledger = null;
		frm.fields_dict.ledger_html?.$wrapper.html(`<p class="text-warning">${esc("本日记录已修改。请保存后刷新流水；有余料留厨时须按当前记录重新清点确认。")}</p>`);
	}

	function openCarryCount(frm, ledger, button) {
		if (frm.__meal_kitchen_dialog_open) return;
		if (ledger?.has_drafts) return frappe.msgprint(__("请先处理库存单草稿，再清点厨房余料。"));
		if (!ledger?.carry_required) return frappe.msgprint(__("本日没有正结存，无需额外余料确认。"));
		const rows = (Array.isArray(ledger.rows) ? ledger.rows : []).filter((row) => Number(closingQty(row)) > 0);
		if (!rows.length) return frappe.msgprint(__("余料明细不完整，请刷新后重试。"));
		frm.__meal_kitchen_dialog_open = true;
		const dialog = new frappe.ui.Dialog({
			title: __("逐项实盘厨房食材余料"), size: "extra-large",
			fields: [
				{ fieldname: "notice", fieldtype: "HTML", options: `<p>${esc("请现场清点后逐项输入实际数量，系统不会自动填入实盘量。数量使用表中的库存单位；与本日结存不一致时，请先核对并按真实业务更正。此操作不创建库存移动。")}</p>` },
				{ fieldname: "physical_counts", fieldtype: "Table", label: __("实际清点"), cannot_add_rows: true, cannot_delete_rows: true, in_place_edit: true,
					data: rows.map((row) => ({ item_code: row.item_code, item_name: row.item_name, stock_uom: row.stock_uom,
						closing_qty: closingQty(row), physical_qty: "" })), fields: [
						{ fieldname: "item_code", fieldtype: "Link", options: "Item", label: __("食材"), read_only: 1, in_list_view: 1 },
						{ fieldname: "item_name", fieldtype: "Data", label: __("名称"), read_only: 1, in_list_view: 1 },
						{ fieldname: "stock_uom", fieldtype: "Data", label: __("库存单位"), read_only: 1, in_list_view: 1 },
						{ fieldname: "closing_qty", fieldtype: "Float", label: __("本日账面结存"), read_only: 1, in_list_view: 1, precision: 9 },
						{ fieldname: "physical_qty", fieldtype: "Data", label: __("实际清点数量"), reqd: 1, in_list_view: 1 },
					] },
				{ fieldname: "notes", fieldtype: "Small Text", label: __("食材留厨说明"), default: frm.doc.carry_notes || "", reqd: 1 },
			],
			onhide() { frm.__meal_kitchen_dialog_open = false; },
			primary_action_label: __("确认真实清点数量"),
			primary_action(values) {
				if (frm.__meal_kitchen_busy) return;
				const counts = values.physical_counts || [];
				if (counts.length !== rows.length || counts.some((row) => !/^(?:\d+(?:\.\d*)?|\.\d+)$/.test(String(row.physical_qty ?? "").trim())
					|| !Number.isFinite(Number(row.physical_qty)))) return frappe.msgprint(__("请逐项输入非负的实际清点数量，不能留空。"));
				dialog.get_primary_btn().prop("disabled", true);
				return call(frm, button, "tongjianyun.meal_kitchen.confirm_kitchen_carry", { day_name: frm.doc.name,
					physical_counts: counts.map((row) => ({ item_code: row.item_code, qty: String(row.physical_qty).trim() })), notes: values.notes }, async (result) => {
					if (!result?.carry_confirmed) throw new Error(__("实盘尚未确认，请刷新流水核对。"));
					dialog.hide();
					await frm.reload_doc();
					const fresh = await frappe.call({ method: "tongjianyun.meal_kitchen.get_kitchen_ledger", args: { day_name: frm.doc.name } });
					if (fresh.exc || !fresh.message) throw new Error(__("请重新刷新库存流水核对确认状态。"));
					renderLedger(frm, fresh.message);
				}).finally(() => dialog.get_primary_btn().prop("disabled", false));
			},
		});
		dialog.show();
	}

	async function checkCarryBeforeSubmit(frm) {
		const response = await frappe.call({ method: "tongjianyun.meal_kitchen.get_kitchen_ledger", args: { day_name: frm.doc.name } });
		if (response.exc || !response.message) frappe.throw(__("请先成功刷新库存流水，再提交日结。"));
		renderLedger(frm, response.message);
		if (response.message.carry_required && !response.message.carry_confirmation_current) frappe.throw(__("本日正余料尚未按当前流水逐项实盘确认，请先清点厨房余料。"));
	}

	frappe.ui.form.on("Meal Kitchen Day", {
		setup(frm) {
			frm.set_query("kitchen_warehouse", () => ({ filters: { company: frm.doc.company, is_group: 0, name: ["!=", frm.doc.source_warehouse] } }));
		},
		refresh(frm) {
			for (const name of ["meals", "items"]) {
				const grid = frm.fields_dict[name]?.grid;
				if (grid) { grid.cannot_add_rows = true; grid.cannot_delete_rows = true; }
			}
			frm.__meal_kitchen_ledger = null;
			frm.set_intro(__("逐餐确认实际供餐人数，按真实数量登记领用、耗用、退料或损耗。余料可留在厨房；有正结存时须逐项实盘确认，再由另一位授权人员审核日结。"), "blue");
			frm.fields_dict.ledger_html?.$wrapper.html(`<p class="text-muted">${esc("点击“刷新库存流水”查看期初留存、本日操作和期末留存。已日结的期末数是当日记录，不代表以后日期仍可用。")}</p>`);
			if (frm.is_new()) return;
			frm.add_custom_button(__("周食谱计划"), () => frappe.set_route("Form", "Meal Planning Week", frm.doc.meal_week));
			const refresh = frm.add_custom_button(__("刷新库存流水"), () => call(frm, refresh, "tongjianyun.meal_kitchen.get_kitchen_ledger", { day_name: frm.doc.name }, (ledger) => renderLedger(frm, ledger)));
			if (frm.doc.docstatus !== 0 || !canOperate()) return;
			const carry = frm.add_custom_button(__("清点厨房余料"), () => call(frm, carry, "tongjianyun.meal_kitchen.get_kitchen_ledger", { day_name: frm.doc.name }, (ledger) => {
				renderLedger(frm, ledger);
				openCarryCount(frm, ledger, carry);
			}));
			for (const action of ["领用", "退料", "耗用", "损耗"]) {
				const button = frm.add_custom_button(__(`${action}草稿`), () => call(frm, button, "tongjianyun.meal_kitchen.get_kitchen_ledger", { day_name: frm.doc.name }, (ledger) => {
					renderLedger(frm, ledger);
					openAction(frm, action, ledger, button);
				}), __("库存操作"));
			}
		},
		before_submit(frm) {
			if ((frm.doc.meals || []).length !== 5 || frm.doc.meals.some((row) => !row.actual_confirmed)) {
				frappe.throw(__("请逐一确认五个餐次的实际供餐人数，零人停供也须明确确认。"));
			}
			if (frm.doc.meals.some((row) => (Number(row.actual_headcount) === 0 || Number(row.actual_headcount) !== Number(row.planned_headcount)) && !String(row.reason || "").trim())) {
				frappe.throw(__("实际人数与计划不同，或实际停供时，请填写该餐原因。"));
			}
			return checkCarryBeforeSubmit(frm);
		},
		carry_notes(frm) { invalidateCarryView(frm); },
	});

	frappe.ui.form.on("Meal Kitchen Meal", {
		actual_headcount(frm, cdt, cdn) {
			frappe.model.set_value(cdt, cdn, "actual_confirmed", 0);
			invalidateCarryView(frm);
		},
		actual_confirmed(frm) { invalidateCarryView(frm); },
		reason(frm) { invalidateCarryView(frm); },
	});
})();
