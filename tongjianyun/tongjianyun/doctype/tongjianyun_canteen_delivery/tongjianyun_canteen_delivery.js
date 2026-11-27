(() => {
	const delivery = "Tongjianyun Canteen Delivery";
	const steps = ["待接单", "已接单", "备货", "分拣", "配送", "到货"];
	const instructions = {
		待接单: ["等待供应商接单", "核对预计到货日和食材数量，可以供货后确认接单。", "确认接单"],
		已接单: ["准备备货", "按本批订单安排货源，开始备货时登记进度。", "登记备货"],
		备货: ["正在备货", "核对实际发货数量，备齐后进入分拣。", "登记分拣"],
		分拣: ["核对批号与日期", "逐项核对食材批号、生产日期和有效期，装车后开始配送。", "开始配送"],
		配送: ["正在配送", "可打印随货二维码交给食堂，送达现场后报告到货。", "报告到货"],
		到货: ["已报告到货", "食堂可扫随货码核对实物与票证，在验收结果中查看实收数量。"],
		拒接: ["供应商已拒接", "园方采购经办人可根据拒接原因，回到订单重新安排配送。"],
	};
	const escape = value => frappe.utils.escape_html(String(value ?? ""));
	const icon = (name) => frappe.utils.icon(name, "sm");
	const incomplete = row => !(row.receipt_trace_no || row.lot_number || "").trim() || !row.manufactured_on || !row.expires_on;
	const busy = new WeakSet();

	async function quickEntry(frm) {
		if (frm.is_dirty()) await frm.save();
		if (frm.is_dirty()) return;
		if (window.cur_frm === frm) frappe.tjyDeliveryLots.open(frm);
	}

	async function advance(frm, target, note) {
		if (busy.has(frm)) return;
		busy.add(frm);
		const name = frm.doc.name;
		try {
			if (frm.is_dirty()) await frm.save();
			if (frm.is_dirty() || frm.doc.name !== name) return;
			await frappe.call({method: "tongjianyun.canteen_ops.purchasing.advance_delivery",
				args: {name, target, note}, freeze: true});
			if (frm.doc.name === name) await frm.reload_doc();
		} finally {
			busy.delete(frm);
		}
	}

	function action(title, handler, primary = false) {
		return $("<button type='button'>").addClass(primary ? "tjy-del-primary" : "tjy-del-secondary")
			.text(title).on("click", handler);
	}

	function render(frm) {
		const doc = frm.doc;
		const main = frm.page.main.addClass("tjy-delivery-form");
		let panel = main.children(".tjy-del-panel");
		if (!panel.length) panel = $("<section class='tjy-del-panel' aria-label='配送批次概览'>").prependTo(main);
		const isNew = frm.is_new();
		const cancelled = doc.docstatus === 2;
		const state = doc.progress || steps[0];
		const info = cancelled ? ["配送批次已取消", "可在批次信息中查阅来源订单与配送记录。"]
			: isNew ? ["按采购订单安排配送", "园方从已提交并下发的采购订单建立批次，系统会带入供应商、食材和待配送数量。"]
			: instructions[state] || ["配送进度", "请核对本批次的配送记录。"];
		const items = doc.items || [];
		const missing = items.filter(incomplete);
		const order = doc.purchase_order;
		const step = isNew || cancelled ? -1 : steps.indexOf(state);
		const orderText = escape(order || "尚未关联");
		const source = order && frappe.model.can_read("Purchase Order")
			? `<a href="${escape(frappe.tjyMealDesk.purchaseOrderLink(order))}">${orderText}</a>` : orderText;
		panel.html(`<header class="tjy-del-hero">
			<div class="tjy-del-kicker"><span aria-hidden="true" class="tjy-del-symbol">${icon("truck")}</span><span>供应商配送批次</span></div>
			<h2>${escape(doc.supplier || "新建配送批次")}</h2>
			<p>园方按订单建批，供应商登记实际发货，食堂凭随货码验收。</p>
			<dl><div><dt>来源订单</dt><dd>${source}</dd></div>
			<div><dt>预计到货</dt><dd>${escape(doc.expected_on || "待填写")}</dd></div>
			<div><dt>食材明细</dt><dd>${items.length} 行</dd></div></dl>
		</header>
		<div class="tjy-del-process">
			<div class="tjy-del-next"><div><h3>${escape(info[0])}</h3>
			<p>${escape(state === "拒接" && doc.progress_note ? "拒接原因：" + doc.progress_note : info[1])}</p></div>
			<div class="tjy-del-actions"></div></div>
			${step < 0 ? "" : `<ol aria-label="配送进度">${steps.map((s, i) =>
				`<li class="${i < step ? "done" : ""}" ${i === step ? 'aria-current="step"' : ""}><span class="tjy-del-dot">${i < step ? "✓" : ""}</span>${s}</li>`
			).join("")}</ol>`}
		</div>`);
		const buttons = panel.find(".tjy-del-actions");
		const perm = frm.perm?.[0] || {};
		if (isNew && frappe.model.can_read("Purchase Order")) {
			buttons.append(action("选择采购订单", () => frappe.set_route(frappe.tjyMealDesk.purchaseOrderLink()), true));
		} else if (!cancelled && !isNew && step >= 0) {
			const target = steps[step + 1];
			if (perm.write && ["待接单", "已接单"].includes(state)) {
				buttons.append(action("拒接", () => frappe.prompt(
					{fieldname: "note", label: "拒接原因", fieldtype: "Small Text", reqd: 1},
					({note}) => advance(frm, "拒接", note), "登记拒接", "确认拒接")));
			}
			if (state === "分拣" && missing.length && perm.write) {
				buttons.append(action("快速补录（" + missing.length + " 行待补）", () => quickEntry(frm), true));
			} else if (target && perm.write && (target !== "配送" || perm.submit)) {
				buttons.append(action(info[2], () => advance(frm, target), true));
			} else if (state === "到货" && doc.docstatus === 1) {
				buttons.append(action("查看验收结果", () => frm.trigger("delivery_acceptance_result"), true));
			}
		}

		const grid = frm.fields_dict.items.grid;
		grid.wrapper.find(".tjy-del-grid-entry").remove();
		if (!isNew && doc.docstatus === 0 && perm.write && step >= 0 && step <= 3 && items.length) {
			action("快速补录", () => quickEntry(frm)).addClass("tjy-del-grid-entry btn btn-xs btn-default")
				.prependTo(grid.wrapper);
		}

		// Clean saved drafts progress via the delivery actions. Dirty forms retain native Save.
		if (!isNew && doc.docstatus === 0 && !frm.is_dirty() && !frappe.workflow.has_workflow(doc)) {
			if (frm.toolbar.get_action_status() === "Submit") frm.page.clear_primary_action();
			frm.layout.message?.children(".form-message").filter((_, el) =>
				el.textContent.trim() === __("Submit this document to confirm")).remove();
		}
	}

	frappe.ui.form.on(delivery, {
		refresh(frm) {
			for (const key of ["company", "canteen", "supplier", "purchase_order"]) {
				frm.toggle_enable(key, frm.is_new());
			}
			render(frm);
		},
		supplier: render, expected_on: render, purchase_order: render,
	});
	frappe.ui.form.on("Tongjianyun Canteen Delivery Item", {
		items_add: render, items_remove: render,
		lot_number: render, manufactured_on: render, expires_on: render,
	});
})();
