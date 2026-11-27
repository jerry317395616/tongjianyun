(() => {
	const esc = value => frappe.utils.escape_html(String(value ?? ""));
	const icon = name => frappe.utils.icon(name, "sm");
	const hasRole = (...roles) => roles.some(role => frappe.user.has_role(role));
	const buyer = () => hasRole("System Manager", "Purchase Manager", "膳食业务经办员");
	const reviewer = () => hasRole("System Manager", "Purchase Manager");
	const deliveryType = "Tongjianyun Canteen Delivery";
	const reviewType = "Tongjianyun Canteen Price Review";
	const quoteApi = "tongjianyun.meal_order_quotation.";
	const buyApi = "tongjianyun.meal_purchasing.";
	const formatQty = value => Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 9 });
	const fmtDate = value => value ? value.slice(5).replace(/^(\d\d)-(\d\d)$/, (_, m, d) => Number(m) + "月" + Number(d) + "日") : "—";
	const datesOf = rows => [...new Set(rows.map(r => r.schedule_date).filter(Boolean))].sort();
	const period = dates => dates.length > 1 ? fmtDate(dates[0]) + " – " + fmtDate(dates.at(-1)) : fmtDate(dates[0]);
	const link = (dt, name, label) => `<a href="${esc(frappe.utils.get_form_link(dt, name))}">${esc(label)}</a>`;
	const btn = (key, label, primary = false) => `<button type="button" data-po-action="${key}" class="mpo-btn${primary ? " mpo-primary" : ""}">${esc(label)}</button>`;
	function snapshot(doc) {
		try { return JSON.parse(doc.custom_meal_quote_snapshot || "{}") || {}; } catch { return {}; }
	}
	function groups(rows) {
		const result = new Map();
		for (const row of rows) {
			const key = JSON.stringify([row.item_code, row.uom]);
			if (!result.has(key)) result.set(key, []);
			result.get(key).push(row);
		}
		return [...result.values()];
	}
	function dishCell(row) {
		const src = /^\/(?!\/)|^https?:\/\//i.test(row.image || "") ? row.image : "";
		return `<span class="mpo-item">${src ? `<img alt="" loading="lazy" src="${esc(src)}">` : `<i>${icon("package")}</i>`}<b>${esc(row.item_name || row.item_code)}</b></span>`;
	}
	function price(rows, currency) {
		if (rows.some(r => !r.supplier_quotation || !Number(r.rate))) return "—";
		const rates = rows.map(r => Number(r.rate));
		const fmt = value => esc(format_currency(value, currency));
		const lo = Math.min(...rates), hi = Math.max(...rates);
		return lo === hi ? fmt(lo) : fmt(lo) + " – " + fmt(hi);
	}
	function renderTable(view) {
		const { doc, panel, byDate } = view;
		const rows = doc.items || [];
		const body = [];
		const tableRow = (items, date) => {
			const first = items[0];
			const amount = items.every(r => r.supplier_quotation) ? esc(format_currency(items.reduce((sum, r) => sum + Number(r.amount || 0), 0), doc.currency)) : "—";
			return `<tr><td>${dishCell(first)}</td><td class="mpo-number">${formatQty(items.reduce((n, r) => n + Number(r.qty), 0))}</td><td>${esc(first.uom)}</td><td class="mpo-number">${price(items, doc.currency)}</td><td class="mpo-number">${amount}</td><td>${esc(date)}</td></tr>`;
		};
		if (byDate) {
			const days = new Map();
			for (const row of rows) {
				const day = row.schedule_date || "";
				if (!days.has(day)) days.set(day, []);
				days.get(day).push(row);
			}
			for (const day of [...days.keys()].sort()) {
				body.push(`<tr class="mpo-day"><th colspan="6">${fmtDate(day)} <small>${days.get(day).length} 条明细</small></th></tr>`);
				for (const row of days.get(day)) body.push(tableRow([row], fmtDate(day)));
			}
		} else {
			for (const items of groups(rows)) body.push(tableRow(items, period(datesOf(items))));
		}
		panel.find(".mpo-tabs button").each((_, el) => el.setAttribute("aria-pressed", String((el.dataset.poAction === "days") === byDate)));
		panel.find("tbody").html(body.join("") || '<tr><td colspan="6">暂无采购明细</td></tr>');
		panel.find(".mpo-qty").text(byDate ? "需求数量" : "采购总量");
	}
	function actionState(view) {
		const { doc, invitation } = view;
		if (doc.docstatus === 2) return ["已取消"];
		if (doc.docstatus === 1) {
			const state = view.delivery;
			if (state?.pending) return ["配送批次已建立", "openDelivery", "打开配送批次"];
			if (state?.can_create) return ["待安排配送", "delivery", "建立配送批次"];
			if (state?.dispatch_request) return ["待下发采购申请", "dispatch", "查看采购申请"];
			return [__(doc.status || "Submitted")];
		}
		if (snapshot(doc).confirmed) return ["报价已确认", "submit", "提交订单"];
		if (doc.items?.length && doc.items.every(r => r.supplier_quotation)) return ["待审核", "review", "确认本单报价"];
		if (invitation?.outdated) return ["询价待更新", "progress", "核对询价单"];
		if (invitation?.quotes?.some(q => q.docstatus === 1)) return ["已收到报价", "apply", "应用供应商报价"];
		if (invitation?.name) return [invitation.quotes?.length ? "报价草稿待提交" : invitation.submitted ? "等待供应商报价" : "询价草稿", "progress", "查看报价进度"];
		return ["待报价", "invite", "邀请供应商报价"];
	}
	function renderHeader(frm, view) {
		const [state, key, label] = actionState(view);
		view.panel.find(".mpo-state").text(state);
		if (view.doc.docstatus === 0 && !snapshot(view.doc).confirmed) {
			if (frm.page.btn_primary?.attr("data-label") === __("Submit")) frm.page.clear_primary_action();
			frm.layout.message?.children(".form-message").filter((_, el) =>
				el.textContent.trim() === __("Submit this document to confirm")).remove();
		}
		const permitted = view.doc.docstatus === 1 || buyer() && frm.perm?.[0]?.write && (key !== "invite" || frappe.model.can_create("Request for Quotation"))
			&& (key !== "review" || (reviewer() && view.doc.owner !== frappe.session.user))
			&& (key !== "submit" || (reviewer() && frm.perm?.[0]?.submit));
		view.panel.find(".mpo-next").html(key && permitted ? btn(key, label, true) : "");
	}
	function dialog(title, fields, label, primary) {
		const d = new frappe.ui.Dialog({ title, fields, primary_action_label: label, primary_action: primary });
		d.$wrapper.addClass("mpo-drawer");
		d.show();
		return d;
	}
	function showInvite(frm, view) {
		const doc = view.doc, entries = groups(doc.items);
		const html = `<div class="mpo-invite"><div class="mpo-vendor"><small>报价供应商</small><strong>${esc(doc.supplier_name || doc.supplier)}</strong></div><h4>报价清单 <small>${entries.length} 项</small></h4><div class="mpo-invite-lines">${entries.map(items => `<div>${dishCell(items[0])}<span>${formatQty(items.reduce((s,r) => s + Number(r.qty), 0))} ${esc(items[0].uom)}</span></div>`).join("")}</div><p>生成询价草稿后，核对供应商联系人并提交询价单。供应商可登录门户填写单价。</p></div>`;
		const d = dialog("邀请供应商报价", [{ fieldtype:"HTML", fieldname:"summary", options:html }], "生成询价草稿", async () => {
			if (frm.is_dirty()) return frappe.msgprint("请先保存订单字段。");
			d.get_primary_btn().prop("disabled", true);
			try {
				const { message } = await frappe.call({ method:quoteApi+"prepare", args:{ order:doc.name }, freeze:true });
				if (message) {
					d.hide();
					frappe.set_route("Form", "Request for Quotation", message);
				}
			} finally { d.get_primary_btn().prop("disabled", false); }
		});
	}
	function showProgress(frm, view) {
		const info = view.invitation;
		const quotes = (info.quotes || []).map(q => `<p>${link("Supplier Quotation", q.name, q.name)} · ${q.docstatus === 1 ? "已提交" : "草稿，待补全有效期并提交"}</p>`).join("");
		const html = `<div class="mpo-invite"><div class="mpo-vendor"><small>供应商</small><strong>${esc(view.doc.supplier_name || view.doc.supplier)}</strong></div><h4>询价单</h4><p>${link("Request for Quotation", info.name, info.name)} · ${info.submitted ? "已提交" : "草稿"}</p>
			<h4>供应商报价</h4>${quotes || `<p>${info.outdated ? "本单的供应商或采购明细与询价单有差异，请打开原询价单核对后重新邀请。" : info.submitted ? "等待供应商登录门户填写单价。" : "打开询价单，核对联系人并提交后即可邀请报价。"}</p>`}
			${info.portal_url ? '<button type="button" class="mpo-btn mpo-copy">复制供应商报价链接</button>' : ""}</div>`;
		const d = dialog("查看报价进度", [{fieldtype:"HTML", fieldname:"summary", options:html}], "打开询价单", () => {
			d.hide(); frappe.set_route("Form", "Request for Quotation", info.name);
		});
		d.$wrapper.find(".mpo-copy").on("click", () => frappe.utils.copy_to_clipboard(info.portal_url));
		const submitted = info.quotes?.find(q => q.docstatus === 1);
		if (submitted) {
			d.set_secondary_action(() => { d.hide(); applyQuote(frm, submitted.name); });
			d.set_secondary_action_label("应用供应商报价");
		}
	}
	async function update(frm, method, args) {
		if (frm.__meal_quote_busy) return;
		if (frm.is_dirty()) return frappe.msgprint("请先保存订单字段。");
		frm.__meal_quote_busy = true;
		try {
			await frappe.call({ method:buyApi+method, args:{ po_name:frm.doc.name, ...args }, freeze:true });
			await frm.reload_doc();
		} finally { frm.__meal_quote_busy = false; }
	}
	function applyQuote(frm, initial) {
		frappe.prompt([{fieldname:"quote", fieldtype:"Link", options:"Supplier Quotation", label:"有效供应商报价", reqd:1,
			default:initial, description:"报价晚于草稿日期时，将按当天日期下单。", get_query:() => ({filters:{
				docstatus:1, company:frm.doc.company, supplier:frm.doc.supplier, currency:frm.doc.currency, valid_till:[">=",frappe.datetime.get_today()]
			}})}], values => update(frm,"apply_supplier_quotation",{ quotation_name:values.quote }), "应用本单供应商报价", "应用报价");
	}
	function review(frm) {
		if (frm.doc.owner === frappe.session.user) return frappe.msgprint("请由另一位采购审核人确认本单报价。");
		frappe.confirm("已核对本单食材、采购单位、单价和配送日期？", () => update(frm, "confirm_purchase_order_quote", {}));
	}
	function render(frm) {
		const doc = frm.doc, previous = frm.__mealOrderView;
		previous?.panel.remove();
		frm.layout.page.removeClass("mpo-fields-folded");
		frm.__mealOrderView = null;
		if (frm.doctype_layout?.name !== frappe.tjyMealDesk.purchaseOrderLayout || !doc.custom_meal_week || frm.is_new()) return;
		frm.page.set_breadcrumbs([
			{label: frappe.tjyMealDesk.purchaseOrderLayout, href: frappe.tjyMealDesk.purchaseOrderLink()},
			{label: doc.name},
		]);
		frappe.require("/assets/tongjianyun/css/meal_purchase_order.css?v=1.css");
		const same = previous?.doc.name === doc.name;
		const view = { doc, byDate:same && previous.byDate, fields:same && previous.fields, invitation:null };
		const panel = view.panel = $('<section class="mpo" aria-label="膳食采购订单"></section>').insertBefore(frm.layout.page);
		frm.__mealOrderView = view;
		const rows = doc.items || [];
		panel.html(`<header class="mpo-head"><div><div class="mpo-title"><h2>膳食采购订单</h2><span class="mpo-state"></span></div><small>${esc(doc.name)}</small></div><div class="mpo-next"></div></header>
		<div class="mpo-banner"><div><span>${icon("building")} 供应商</span><strong>${esc(doc.supplier_name || doc.supplier)}</strong></div><div><span>${icon("calendar")} 配送周期</span><strong>${period(datesOf(rows))}</strong></div><div><span>${icon("book-open")} 来源周食谱</span>${link("Meal Planning Week",doc.custom_meal_week,doc.custom_meal_week)}</div><p><b>${new Set(rows.map(r=>r.item_code)).size}</b> 种食材 <i></i> <b>${rows.length}</b> 条配送明细</p></div>
		<div class="mpo-controls"><div class="mpo-tabs" role="group" aria-label="明细查看方式">${btn("items","按食材汇总")}${btn("days","按配送日期")}</div>${btn("fields","订单字段")}</div>
		<div class="mpo-scroll"><table><thead><tr><th>食材名称</th><th class="mpo-number mpo-qty">采购总量</th><th>单位</th><th class="mpo-number">报价单价</th><th class="mpo-number">金额</th><th>需求日期</th></tr></thead><tbody></tbody></table></div>
		<footer><span>${esc(doc.company)}</span><span class="mpo-deliveries"></span></footer>`);
		const syncFields = () => {
			frm.layout.page.toggleClass("mpo-fields-folded", !view.fields);
			panel.find('[data-po-action="fields"]').attr("aria-expanded", String(!!view.fields)).text(view.fields ? "收起订单字段" : "订单字段");
		};
		syncFields();
		panel.on("click", "[data-po-action]", function () {
			switch (this.dataset.poAction) {
				case "days": case "items": view.byDate = this.dataset.poAction === "days"; renderTable(view); break;
				case "fields": view.fields = !view.fields; syncFields(); if (view.fields) frm.layout.page[0].scrollIntoView({block:"start"}); break;
				case "invite": showInvite(frm, view); break;
				case "progress": showProgress(frm, view); break;
				case "apply": applyQuote(frm, view.invitation.quotes.find(q => q.docstatus === 1)?.name); break;
				case "openDelivery": frappe.set_route("Form", deliveryType, view.delivery.pending); break;
				case "dispatch": frappe.set_route("Form", "Material Request", view.delivery.dispatch_request); break;
				case "delivery":
					frappe.call({ method:"tongjianyun.canteen_ops.purchasing.create_delivery", args:{purchase_order:doc.name},
						btn:$(this), freeze:true }).then(({ message }) => frappe.set_route("Form", deliveryType, message));
					break;
				case "review": review(frm); break;
				case "submit": frm.savesubmit(); break;
			}
		});
		renderTable(view);
		renderHeader(frm, view);
		if (doc.docstatus === 1) {
			frappe.call({ method:"tongjianyun.canteen_ops.ui.order_delivery_status", type:"GET", args:{purchase_order:doc.name} })
				.then(({ message }) => {
					if (frm.__mealOrderView !== view) return;
					view.delivery = message;
					panel.find(".mpo-deliveries").html(message.batches.map(b => link(deliveryType, b.name, b.name + " · " + b.progress)).join("　"));
					renderHeader(frm, view);
				});
		}
		if (doc.docstatus === 0 && frappe.model.can_create(reviewType)) {
			frappe.call({ method:"tongjianyun.canteen_ops.ui.order_site", type:"GET", args:{purchase_order:doc.name} })
				.then(({ message: canteen }) => {
					if (!canteen || frm.__mealOrderView !== view) return;
					frm.add_custom_button("采购价格复核", () => frappe.new_doc(reviewType,
						{ company:doc.company, canteen, purchase_order:doc.name }), "采购操作");
				});
		}
		if (doc.docstatus === 0 && buyer()) {
			frm.add_custom_button("应用供应商报价", () => applyQuote(frm), "采购操作");
			if (reviewer() && doc.owner !== frappe.session.user && doc.items?.every(r => r.supplier_quotation))
				frm.add_custom_button("确认本单报价", () => review(frm), "采购操作");
			frappe.call({ method:quoteApi+"status", type:"GET", args:{order:doc.name} }).then(({message}) => {
				if (frm.__mealOrderView !== view) return;
				view.invitation = message || {};
				renderHeader(frm, view);
			});
		}
	}
	frappe.ui.form.on("Purchase Order", {
		refresh: render,
		before_submit(frm) {
			if (frm.doctype_layout?.name === frappe.tjyMealDesk.purchaseOrderLayout && frm.doc.custom_meal_week && snapshot(frm.doc).confirmed !== true)
				frappe.throw(__("请先应用供应商报价，并由另一位授权采购审核人确认本单报价。"));
		},
	});
})();
