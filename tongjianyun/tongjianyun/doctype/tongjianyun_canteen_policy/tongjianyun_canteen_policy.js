(() => {
	const policy = "Tongjianyun Canteen Policy";
	const canteenType = "Tongjianyun Canteen";
	const suggestedNames = new WeakMap();
	const tickets = ["送货单", "产品合格证明", "检疫证明"];
	const sectionIcons = {
		scope_section: "building", evidence_section: "clipboard-list", purchase_section: "shopping-cart",
		safety_section: "shield-check", reminder_section: "calendar", finance_section: "wallet",
		attachment_section: "paperclip",
	};

	function renderHeader(frm) {
		const main = frm.page.main;
		main.addClass("tjy-policy-form");
		let header = main.children(".tjy-policy-header");
		if (!header.length) {
			header = $('<section class="tjy-policy-header" aria-label="规则用途"><span class="tjy-policy-state"></span><h2>食堂采购与结算规则</h2><p>采购申请交给谁、收货查哪些票证、多久和供应商对账，都在这里设置。</p></section>').prependTo(main);
		}
		const today = frappe.datetime.get_today();
		const doc = frm.doc;
		let state = "草稿 · 提交后按有效期执行";
		if (doc.docstatus === 2) state = "已取消";
		if (doc.docstatus === 1) {
			state = today < doc.from_date ? "待生效" : today > doc.to_date ? "已到期" : "执行中";
			state += " · " + doc.from_date + " 至 " + doc.to_date;
		}
		header.find(".tjy-policy-state").text(state);
		for (const [key, icon] of Object.entries(sectionIcons)) {
			const head = $(frm.fields_dict[key]?.wrapper).children(".section-head");
			if (head.length && !head.children(".tjy-policy-section-icon").length) {
				$('<span class="tjy-policy-section-icon" aria-hidden="true">').html(frappe.utils.icon(icon, "sm")).prependTo(head);
			}
		}
	}

	function renderTickets(frm) {
		const grid = frm.fields_dict.evidence_rules.grid;
		const canEdit = frm.doc.docstatus === 0 && grid.is_editable() && !grid.cannot_add_rows;
		frm.toggle_display("evidence_shortcuts", canEdit);
		const wrap = frm.fields_dict.evidence_shortcuts.$wrapper.empty();
		if (!canEdit) return;
		const actions = $('<div class="tjy-policy-tickets" role="group" aria-label="添加常用票证">').appendTo(wrap);
		for (const ticket of tickets) {
			const present = (frm.doc.evidence_rules || []).some(r => !r.item_group && r.evidence_type === ticket);
			$('<button type="button">').text((present ? "✓ " : "＋ ") + ticket).prop("disabled", present)
				.appendTo(actions).on("click", () => {
					frm.add_child("evidence_rules", {evidence_type: ticket});
					frm.refresh_field("evidence_rules");
					frm.dirty();
					renderTickets(frm);
				});
		}
	}

	function suggestName(frm) {
		if (!frm.is_new() || frm.doc.amended_from || !frm.doc.from_date) return;
		if (frm.doc.policy_name && frm.doc.policy_name !== suggestedNames.get(frm.doc)) return;
		const suggestion = frm.doc.from_date + " 起食堂采购规则";
		suggestedNames.set(frm.doc, suggestion);
		if (frm.doc.policy_name !== suggestion) return frm.set_value("policy_name", suggestion);
	}

	async function suggestCanteen(frm) {
		const doc = frm.doc;
		const company = doc.company;
		if (!company || doc.canteen || !frappe.model.can_read(canteenType)) return;
		const rows = await frappe.db.get_list(canteenType, {filters: {company, disabled: 0}, fields: ["name"], limit: 2});
		if (rows.length === 1 && frm.doc === doc && doc.company === company && !doc.canteen && doc.docstatus === 0) {
			await frm.set_value("canteen", rows[0].name);
		}
	}

	frappe.ui.form.on(policy, {
		setup(frm) {
			frm.set_query("cost_center", () => ({filters: {company: frm.doc.company, is_group: 0, disabled: 0}}));
			for (const field of ["purchase_assignee", "finance_reviewer"]) {
				frm.set_query(field, () => ({filters: {enabled: 1, user_type: "System User"}}));
			}
		},
		async onload(frm) {
			frm.__policyCompany = frm.doc.company;
			if (!frm.is_new()) return;
			await suggestName(frm);
			const company = frappe.defaults.get_user_default("Company");
			if (!frm.doc.company && company) await frm.set_value("company", company);
			else await suggestCanteen(frm);
		},
		async company(frm) {
			if (frm.__policyCompany && frm.__policyCompany !== frm.doc.company) {
				await frm.set_value({canteen: null, cost_center: null});
			}
			frm.__policyCompany = frm.doc.company;
			await suggestCanteen(frm);
		},
		from_date: suggestName,
		validate(frm) {
			if (!frm.doc.evidence_rules?.length) frappe.throw("请在「基本设置」中至少添加一种收货票证。");
		},
		refresh(frm) {
			renderHeader(frm);
			renderTickets(frm);
		},
	});
	frappe.ui.form.on("Tongjianyun Canteen Evidence Rule", {
		evidence_rules_add: renderTickets, evidence_rules_remove: renderTickets,
		evidence_type: renderTickets, item_group: renderTickets,
	});
})();
