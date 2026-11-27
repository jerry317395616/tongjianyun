(() => {
	const type = "Tongjianyun Canteen Receiving";
	const esc = value => frappe.utils.escape_html(String(value ?? ""));
	const icon = name => frappe.utils.icon(name, "sm");
	const format = new Intl.NumberFormat("zh-CN", {maximumFractionDigits:9});
	const qty = value => format.format(Number(value || 0));
	const info = frm => frm.doc.__onload?.inspection || {};
	const rows = frm => frm.doc.items || [];
	const title = (frm, row) => info(frm).names?.[row.item_code] || row.item_code;
	const line = (frm, row) => info(frm).by_line?.[row.delivery_item] || {};
	const hasReason = value => Boolean(value?.trim() && value.trim() !== "待现场核对");
	const writable = frm => !frm.doc.docstatus && !frm.is_new() && frm.perm?.[0]?.write &&
		frm.fields_dict.items?.disp_status !== "Read" && !frappe.boot.read_only;
	function issues(frm, row) {
		const live = line(frm,row).issues;
		if (Array.isArray(live)) return live;
		const saved = row.evidence_status;
		return saved && !["已核对","票证齐全，待人工核实"].includes(saved) ? [saved] : [];
	}
	function recorded(row) {
		const accepted = Number(row.accepted_qty || 0), rejected = Number(row.rejected_qty || 0);
		if (accepted < 0 || rejected < 0 || accepted + rejected > Number(row.expected_qty) + 1e-9) return false;
		return Math.abs(accepted - Number(row.expected_qty)) < 1e-9 || hasReason(row.reason);
	}
	function ticket(frm, row) {
		const problems = issues(frm,row);
		if (problems.length) return [problems.join("、"), "warn"];
		return row.evidence_verified ? ["票证已核对","ok"] : ["待核票证","muted"];
	}
	function nextRow(frm, current) {
		const all = rows(frm), index = all.findIndex(r => r.name === current);
		const ordered = index < 0 ? all : all.slice(index+1).concat(all.slice(0,index));
		return ordered.find(r => !recorded(r)) || ordered.find(r =>
			Number(r.accepted_qty) > 0 && !r.evidence_verified && !issues(frm,r).length);
	}
	function fieldTab(frm, field) {
		frm.fields_dict[field]?.tab?.set_active();
	}
	function board(frm) {
		return frm.fields_dict.inspection_board.$wrapper;
	}
	function drawLines(frm) {
		const root = board(frm), state = frm._inspectionView;
		const list = rows(frm).filter(r => {
			if (state.filter === "pending" && recorded(r)) return false;
			if (state.filter === "issues" && !issues(frm,r).length) return false;
			return [title(frm,r),r.item_code,r.lot_number,r.receipt_trace_no,line(frm,r).due]
				.some(v => String(v || "").toLowerCase().includes(state.query));
		});
		root.find("[data-filter]").each((_,el) => el.setAttribute("aria-pressed",String(el.dataset.filter === state.filter)));
		root.find(".tr-results").text(list.length + " 行");
		const content = list.map(r => {
			const [status,tone] = ticket(frm,r);
			const date = line(frm,r).due, ref = r.lot_number || r.receipt_trace_no || "";
			return `<button type="button" class="tr-line" data-row="${esc(r.name)}">
				<span class="tr-food"><strong>${esc(title(frm,r))}</strong><small>${date ? esc(date)+" · " : ""}${r.receipt_trace_no ? "到货追溯号 " : "批号 "}${esc(ref || "待补")}</small></span>
				<span class="tr-numbers"><strong>${qty(r.expected_qty)} ${esc(__(r.uom || ""))}</strong><small>${recorded(r) ? "合格 "+qty(r.accepted_qty)+" · 拒收 "+qty(r.rejected_qty) : "待登记实收"}</small></span>
				<span class="tr-pill tr-${tone}">${esc(status)}</span><span class="tr-chevron" aria-hidden="true">›</span></button>`;
		}).join("");
		root.find(".tr-rows").html(content || '<p class="tr-empty">当前条件下没有明细。</p>');
	}
	function render(frm) {
		const root = board(frm);
		if (!root || !root.length) return;
		root.addClass("tjy-receive-board");
		if (frm._inspectionView?.name !== frm.doc.name) frm._inspectionView = {name:frm.doc.name, query:"", filter:"all"};
		if (frm.is_new() && !rows(frm).length) {
			root.html('<div class="tr-entry-hero"><div class="tr-entry-copy"><h2>扫描随货码开始验收</h2><p>从供应商随货码读取配送单和食材明细。</p><button type="button" class="tr-primary" data-go-list>前往扫码验收</button></div></div>');
			root.find("[data-go-list]").on("click",() => frappe.set_route("List",type));
			return;
		}
		const all = rows(frm), done = all.filter(recorded).length;
		const blocked = all.filter(r => issues(frm,r).length).length;
		const editable = writable(frm), policy = info(frm).policy;
		const state = frm.doc.docstatus === 2 ? "已取消" : frm.doc.docstatus === 1 ? "已提交" : "现场记录";
		const helper = frm.doc.docstatus === 2 ? "此验收单已取消。" : frm.doc.docstatus === 1
			? (frm.doc.purchase_receipt ? "合格数量已生成采购收货单。" : "本单已完成验收，无合格数量入库。")
			: policy?.require_dual_review ? "现场验收员填写实收并保存，再由另一位库存主管复核入库。" : "按实物登记数量并核对票证，复核提交后合格数量入库。";
		const date = frm.doc.arrived_at ? frappe.datetime.str_to_user(frm.doc.arrived_at) : "";
		const act = (key,caption,cls="tr-alternate") => `<button type="button" class="${cls}" data-act="${key}">${caption}</button>`;
		root.html(`<section class="tr-inspect-hero"><div><span class="tr-state">${esc(state)}</span>
			<h2>${esc(frm.doc.supplier || "到货验收")}</h2><p>${esc([frm.doc.delivery,date].filter(Boolean).join(" · "))}</p></div>
			<div class="tr-counter"><span>数量已登记</span><strong>${done}<small> / ${all.length} 行</small></strong>
			<progress max="${all.length || 1}" value="${done}"></progress></div></section>
			<div class="tr-next"><div><strong>${frm.doc.docstatus ? "验收结果" : "现场核对与复核"}</strong><p>${helper}</p></div><div class="tr-actions">
			${frm.doc.docstatus === 1 && frm.doc.purchase_receipt && frappe.model.can_read("Purchase Receipt") ? act("receipt","查看采购收货单") : ""}
			${act("proof","现场凭证"+(policy?.require_photo && !frm.doc.photo ? " · 待传照片" : ""))}
			${editable && all.length ? act(frm.is_dirty() ? "save" : "continue", frm.is_dirty() ? "保存现场记录" : !done ? "开始核对" : done < all.length ? "继续核对" : "查看核对明细","tr-primary") : ""}</div></div>
			<section class="tr-work"><header><h3>食材验收明细</h3><span class="tr-results"></span></header>
			<div class="tr-tools"><div class="tr-filters" role="group" aria-label="验收明细筛选">
			${[["all","全部",all.length],["pending","待填数量",all.length-done],["issues","票证异常",blocked]].map(([k,text,n]) =>
				`<button type="button" data-filter="${k}">${text} <span>${n}</span></button>`).join("")}</div>
			<label class="tr-search">${icon("search")}<input type="search" placeholder="查食材、批号或需求日期" aria-label="查食材、批号或需求日期" value="${esc(frm._inspectionView.query)}"></label></div>
			${blocked && !frm.doc.docstatus ? `<div class="tr-notice"><span>${icon("info")} ${blocked} 行票证待处理，可先登记实收。</span>
			<span>${info(frm).can_open_delivery ? act("delivery","查看配送票证","tr-link") : ""}${act("refresh","刷新票证","tr-link")}</span></div>` : ""}
			<div class="tr-cols" aria-hidden="true"><span>食材 / 批次</span><span>随货 / 实收</span><span>票证</span><span></span></div>
			<div class="tr-rows"></div></section>`);
		drawLines(frm);
		root.off(".inspection").on("input.inspection", ".tr-search input", e => {
			frm._inspectionView.query = e.currentTarget.value.trim().toLowerCase(); drawLines(frm);
		}).on("click.inspection","[data-filter]", e => {
			frm._inspectionView.filter = e.currentTarget.dataset.filter; drawLines(frm);
		}).on("click.inspection","[data-row]", e => {
			const row = rows(frm).find(r => r.name === e.currentTarget.dataset.row);
			if (row) inspect(frm, row);
		}).on("click.inspection","[data-act]", async e => {
			const action = e.currentTarget.dataset.act;
			if (action === "proof") return fieldTab(frm,"photo");
			if (action === "receipt") return frappe.set_route("Form","Purchase Receipt",frm.doc.purchase_receipt);
			if (action === "delivery") return window.open(frappe.utils.get_form_link("Tongjianyun Canteen Delivery",frm.doc.delivery),"_blank","noopener");
			if (action === "save" && writable(frm)) return frm.save();
			if (action === "refresh") {
				if (frm.is_dirty()) return frappe.confirm("保存当前记录并重新读取配送票证？", async () => {await frm.save(); await frm.reload_doc();});
				return frm.reload_doc();
			}
			if (action === "continue" && all.length) inspect(frm, nextRow(frm) || all[0]);
		});
	}

	function inspect(frm, row) {
		const editable = writable(frm), details = line(frm,row);
		const problems = issues(frm,row), expected = Number(row.expected_qty), unit = __(row.uom || "");
		const label = title(frm,row), isMutable = editable ? 0 : 1;
		const input = (fieldname, caption, fieldtype, extra={}) =>
			({fieldname, label:caption, fieldtype, default:row[fieldname], read_only:isMutable, ...extra});
		const facts = [
			[row.receipt_trace_no ? "到货追溯号" : "供应商批号", row.receipt_trace_no || row.lot_number],
			["需求日期",details.due], ["生产日期",details.made], ["有效期至",row.expires_on]
		].filter(([,v]) => v);
		const dialog = new frappe.ui.Dialog({
			title:esc(label), no_submit_on_enter:true,
			fields:[
				{fieldtype:"HTML",fieldname:"batch",options:`<div class="tr-batch"><div><span>随货数量</span><strong>${qty(expected)} ${esc(unit)}</strong></div>
				<dl>${facts.map(([k,v])=>`<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl></div>`},
				...(editable ? [{fieldtype:"Button",fieldname:"use_expected",label:"按随货量填入合格数量",
					click:() => dialog.set_value("accepted_qty",Math.max(0,flt(expected - Number(dialog.get_value("rejected_qty") || 0), 9)))}] : []),
				input("accepted_qty","合格数量（"+unit+"）","Float"),
				{fieldtype:"Column Break"},input("rejected_qty","拒收数量（"+unit+"）","Float"),
				{fieldtype:"Section Break"},
				input("reason","差异或拒收原因","Small Text",{default:hasReason(row.reason) ? row.reason : ""}),
				{fieldtype:"HTML",fieldname:"checks",options:`<p class="tr-evidence ${problems.length ? "tr-warn" : "tr-muted"}">${esc(ticket(frm,row)[0])}</p>`},
				input("evidence_verified","已人工核对该批票证","Check"),
				{fieldtype:"Section Break"},
				input("record_weight","登记现场称重","Check",{default:row.record_weight || Boolean(row.gross_weight || row.tare_weight)}),
				input("gross_weight","毛重（公斤）","Float",{depends_on:"record_weight"}),
				{fieldtype:"Column Break"},input("tare_weight","皮重（公斤）","Float",{depends_on:"record_weight"})
			],
			primary_action_label:editable ? "应用到明细" : "关闭",
			primary_action:() => editable ? apply(false) : dialog.hide(),
			...(editable && rows(frm).length>1 ? {secondary_action_label:"应用并核下一项",secondary_action:()=>apply(true)} : {})
		});
		let applying = false;
		async function apply(advance) {
			if (applying || !writable(frm)) return;
			const values = dialog.get_values();
			if (!values) return;
			const accepted = Number(values.accepted_qty || 0), rejected = Number(values.rejected_qty || 0);
			if (accepted < 0 || rejected < 0 || accepted+rejected > expected+1e-9)
				return frappe.msgprint("合格量与拒收量均须为非负数，合计不能超过随货数量。");
			if ((Math.abs(accepted-expected)>1e-9 || rejected) && !hasReason(values.reason))
				return frappe.msgprint("请填写实际短送或拒收原因。");
			const gross = Number(values.gross_weight || 0), tare = Number(values.tare_weight || 0);
			if (values.record_weight && (gross < 0 || tare < 0 || gross < tare)) return frappe.msgprint("请核对毛重与皮重。");
			applying = true;
			try {
				await frappe.model.set_value(row.doctype,row.name,{
					accepted_qty:accepted,rejected_qty:rejected,reason:values.reason || "", evidence_verified:values.evidence_verified || 0,
					record_weight:values.record_weight || 0,gross_weight:values.record_weight ? gross : 0,tare_weight:values.record_weight ? tare : 0
				});
				dialog.hide();
				render(frm);
				const next = nextRow(frm,row.name);
				if (advance && next) inspect(frm,next);
			} finally { applying = false; }
		}
		dialog.show();
	}
	function refresh(frm) {
		render(frm);
		const policy = info(frm).policy;
		const ownReview = !frm.doc.docstatus && policy?.require_dual_review && frm.doc.inspector === frappe.session.user;
		if (ownReview && !frappe.workflow.has_workflow(frm.doc)) {
			if (!frm.is_dirty() && frm.toolbar.get_action_status() === "Submit") frm.page.clear_primary_action();
			frm.layout.message?.children(".form-message").filter((_,el) =>
				el.textContent.trim() === __("Submit this document to confirm")).remove();
		}
		if (!frm.doc.docstatus && policy) {
			frm.set_df_property("photo","description",policy.require_photo ? "本食堂复核前须上传本次验收的现场照片。" : "可上传到货现场和异常食材的照片。");
			if (policy.require_location) frm.fields_dict.location_section?.collapse(false);
		}
	}
	frappe.ui.form.on(type, {refresh, after_save:render});
})();
