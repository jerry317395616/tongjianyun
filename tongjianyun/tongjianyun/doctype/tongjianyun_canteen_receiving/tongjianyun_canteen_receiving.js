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
		if (Array.isArray(live)) return row.delivery_note_exception ? ["送货单异常：" + row.delivery_note_exception, ...live] : live;
		const saved = row.evidence_status;
		return saved && !["已核对","票证齐全，待人工核实"].includes(saved) ? [saved] : [];
	}
	function recorded(row) {
		const accepted = Number(row.accepted_qty || 0), rejected = Number(row.rejected_qty || 0);
		if (accepted < 0 || rejected < 0 || accepted + rejected > Number(row.expected_qty) + 1e-9) return false;
		return Math.abs(accepted - Number(row.expected_qty)) < 1e-9 || hasReason(row.reason);
	}
	function checkedByNote(frm, row) {
		return !row.delivery_note_exception && Boolean(frm.doc.verified_delivery_note) &&
			line(frm,row).notes_covering_all_rules?.includes(frm.doc.verified_delivery_note);
	}
	function ticket(frm, row) {
		const problems = issues(frm,row);
		if (problems.length) return [problems.join("、"), "warn"];
		if (checkedByNote(frm,row)) return ["送货单已核对","ok"];
		if (row.evidence_verified || (frm.doc.docstatus && row.evidence_status === "已核对")) return ["票证已核对","ok"];
		return [frm.doc.verified_delivery_note ? "待核明细票证" : "待核票证","muted"];
	}
	function nextRow(frm, current) {
		const all = rows(frm), index = all.findIndex(r => r.name === current);
		const ordered = index < 0 ? all : all.slice(index+1).concat(all.slice(0,index));
		return ordered.find(r => !recorded(r)) || ordered.find(r =>
			Number(r.accepted_qty) > 0 && !r.evidence_verified && !checkedByNote(frm,r) && !issues(frm,r).length);
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
			${info(frm).delivery_notes?.length ? `<section class="tr-manifest"><div>${icon("clipboard")} <strong>本次配送送货单</strong>
				<p>${frm.doc.verified_delivery_note ? "已人工核对整批送货单" : "已上传，待人工核对"} · ${all.length} 行配送明细</p></div>
				${act("manifest",editable ? (frm.doc.verified_delivery_note ? "查看或调整核对结果" : "核对整批送货单") : "查看送货单")}</section>` : ""}
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
			if (action === "manifest") return reviewDeliveryNote(frm);
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

	function reviewDeliveryNote(frm) {
		const notes = info(frm).delivery_notes, all = rows(frm), editable = writable(frm);
		if (!notes?.length) return;
		const dialog = new frappe.ui.Dialog({
			title: "核对本次配送送货单", size:"large", no_submit_on_enter:true,
			fields:[{fieldname:"review",fieldtype:"HTML"}]
		});
		const root = dialog.fields_dict.review.$wrapper;
		const start = notes.find(t => t.id === frm.doc.verified_delivery_note) || notes.find(t => !t.expired) || notes[0];
		const exceptions = new Map(all.filter(r => r.delivery_note_exception).map(r => [r.name,r.delivery_note_exception]));
		root.html(`<div class="tr-note-review"><label class="tr-note-source">送货单
			<select class="form-control" data-note>${notes.map(t=>`<option value="${esc(t.id)}">${esc(t.number)}${t.expired ? "（到货时已过期）" : ""}</option>`).join("")}</select></label>
			<a data-attachment target="_blank" rel="noopener noreferrer">查看送货单附件 ↗</a>
			<p>对照附件核对本次配送的 ${all.length} 行。仅标记漏列、批号不符等异常，短送和拒收数量在食材明细登记。</p>
			<div class="tr-note-list" role="region" aria-label="送货单明细" tabindex="0">${all.map(r => `<div class="tr-note-line" data-line="${esc(r.name)}">
				<div><strong>${esc(title(frm,r))}</strong><small>${esc(r.lot_number || r.receipt_trace_no || "待补批号")}</small></div>
				<span>随货 ${qty(r.expected_qty)} ${esc(__(r.uom || ""))}<small>${recorded(r) ? "合格 "+qty(r.accepted_qty)+" · 拒收 "+qty(r.rejected_qty) : "实收待登记"}</small></span>
				<label><input type="checkbox" ${exceptions.has(r.name) ? "checked" : ""} ${editable ? "" : "disabled"}> 异常</label>
				<input type="text" class="form-control" aria-label="${esc(title(frm,r))}异常说明" placeholder="填写漏列或批号不符等原因" ${exceptions.has(r.name) ? "" : "hidden"} ${editable ? "" : "readonly"} value="${esc(exceptions.get(r.name) || "")}">
			</div>`).join("")}</div><div class="tr-note-total" aria-live="polite"></div></div>`);
		const select = root.find("[data-note]").val(start.id);
		function update() {
			const note = notes.find(t => t.id === select.val());
			const link = root.find("[data-attachment]");
			link.removeAttr("href");
			if (note && /^(?:\/(?!\/)|https?:\/\/)/i.test(note.file)) link.attr("href",note.file);
			root.find(".tr-note-total").text(`本次核对 ${all.length-exceptions.size} 行 · 标记异常 ${exceptions.size} 行`);
			dialog.get_primary_btn().prop("disabled",editable && (!note || note.expired));
		}
		select.on("change",update);
		root.on("change","input[type=checkbox]",function(){
			const el = $(this).closest("[data-line]"), key = el.attr("data-line"), input = el.find("input[type=text]");
			if (this.checked) { exceptions.set(key,input.val()); input.prop("hidden",false).trigger("focus"); }
			else { exceptions.delete(key); input.val("").prop("hidden",true); }
			update();
		}).on("input","input[type=text]",function(){
			exceptions.set($(this).closest("[data-line]").attr("data-line"),this.value.trim());
		});
		dialog.set_primary_action(editable ? "确认核对并保存" : "关闭", async () => {
			if (!editable) return dialog.hide();
			if (!writable(frm)) return;
			for (const r of all) {
				if (exceptions.has(r.name) && !exceptions.get(r.name)) {
					root.find("[data-line]").filter((_,el)=>el.dataset.line===r.name).find("input[type=text]").trigger("focus");
					return frappe.msgprint("请填写「"+esc(title(frm,r))+"」的送货单异常说明。");
				}
			}
			dialog.get_primary_btn().prop("disabled",true);
			try {
				for (const r of all) {
					const reason = exceptions.get(r.name) || "";
					if (reason !== (r.delivery_note_exception || "")) await frappe.model.set_value(r.doctype,r.name,"delivery_note_exception",reason);
				}
				await frm.set_value("verified_delivery_note",select.val());
				if (frm.is_dirty()) await frm.save();
				await frm.reload_doc();
				dialog.hide();
			} finally { update(); }
		});
		dialog.show();
		update();
	}

	function inspect(frm, firstRow) {
		const dialog = new frappe.ui.Dialog({
			title:"食材核对", no_submit_on_enter:true,
			fields:[{fieldname:"inspection",fieldtype:"HTML"}]
		});
		dialog.$wrapper.addClass("tjy-inspection-dialog");
		const root = dialog.fields_dict.inspection.$wrapper.addClass("tr-inspection");
		let row, expected, unit, mode, applying = false;
		const field = name => root.find('[name="' + name + '"]');
		const amount = name => Number(field(name).val() || 0);
		const section = name => root.find('[data-part="' + name + '"]');
		function numeric(name, caption, value, suffix) {
			return `<label class="tri-numeric"><span>${caption}</span><span class="tri-input"><input type="number" name="${name}"
				step="any" min="0" inputmode="decimal" value="${esc(value ?? "")}"><span>${esc(suffix)}</span></span></label>`;
		}
		function openRow(current) {
			row = current;
			expected = Number(row.expected_qty);
			unit = __(row.uom || "");
			const editable = writable(frm);
			const full = Math.abs(Number(row.accepted_qty || 0)-expected)<1e-9 && !Number(row.rejected_qty);
			mode = full && !hasReason(row.reason) ? "full" :
				(hasReason(row.reason) || Number(row.rejected_qty) || Number(row.accepted_qty) ? "adjust" : "");
			const details = line(frm,row), problems = issues(frm,row), covered = checkedByNote(frm,row);
			const name = title(frm,row), all = rows(frm), idx = all.findIndex(r => r.name === row.name);
			const image = info(frm).images?.[row.item_code];
			const photo = typeof image === "string" && /^\/(?:private\/files|files|assets)\//.test(image)
				? `<img src="${esc(image)}" alt="">` : "";
			const dates = [["需求日期",details.due],["生产日期",details.made],["有效期至",row.expires_on]];
			const withWeight = Boolean(Number(row.record_weight) || Number(row.gross_weight) || Number(row.tare_weight));
			dialog.set_title(`食材核对 <small class="tri-index">第 ${idx+1} / ${all.length} 项</small>`);
			root.html(`<section class="tri-batch"><div class="tri-identity">
				<div class="tri-photo" aria-hidden="true">${icon("package")}${photo}</div>
				<div class="tri-food"><h3 tabindex="-1">${esc(name)}</h3><p>${row.receipt_trace_no ? "到货追溯号" : "供应商批号"} <b>${esc(row.receipt_trace_no || row.lot_number || "待补")}</b></p></div>
				<div class="tri-expected"><span>随货数量</span><strong>${qty(expected)} <small>${esc(unit)}</small></strong></div></div>
				<dl>${dates.map(([k,v])=>`<div><dt>${k}</dt><dd>${esc(v || "—")}</dd></div>`).join("")}</dl></section>
			<section class="tri-block"><h4>到货结果</h4>
				${editable ? `<div class="tri-choices" role="group" aria-label="到货结果">
				<button type="button" data-mode="full">${icon("check")}<span><strong>足量合格</strong><small>按随货量填入 ${qty(expected)} ${esc(unit)}</small></span></button>
				<button type="button" data-mode="adjust">${icon("pencil-line")}<span><strong>登记差异</strong><small>短送、拒收或调整实收量</small></span></button></div>` :
				`<p class="tri-readresult">${mode ? "合格 "+qty(row.accepted_qty)+" "+esc(unit)+" · 拒收 "+qty(row.rejected_qty)+" "+esc(unit) : "数量待登记"}</p>`}
				<div data-part="variance" class="tri-variance" hidden><div class="tri-pair">
					${numeric("accepted","合格数量",row.accepted_qty,unit)}${numeric("rejected","拒收数量",row.rejected_qty,unit)}</div>
					<div class="tri-balance"><span data-short aria-live="polite"></span>${editable ? '<button type="button" data-fill>按随货量扣除拒收量填入</button>' : ""}</div>
					<label class="tri-reason">差异或拒收原因<textarea name="reason" rows="2" placeholder="例如：短送 0.1 公斤，或包装破损拒收">${esc(hasReason(row.reason) ? row.reason : "")}</textarea></label>
				</div></section>
			<section class="tri-block"><h4>随货票证</h4><div class="tri-ticket ${problems.length ? "tri-missing" : ""}">
				<div>${icon(problems.length ? "info" : "clipboard")}<strong>${esc(problems.length ? problems.join("、") : covered ? "整批送货单已人工核对" : "人工核对")}</strong></div>
				<label ${covered ? "hidden" : ""}><input type="checkbox" name="verified" ${Number(row.evidence_verified) ? "checked" : ""}>已核对该批票证</label>
				${editable && problems.length ? '<p>可先登记实收，补齐票证后再复核入库。</p>' : ""}</div></section>
			<section class="tri-weight"><label class="tri-weigh-toggle">${icon("scale")}<span>登记现场称重</span>
				<input type="checkbox" name="weigh" ${withWeight ? "checked" : ""}></label>
				<div data-part="weights" hidden><div class="tri-pair">${numeric("gross","毛重",row.gross_weight,"公斤")}${numeric("tare","皮重",row.tare_weight,"公斤")}</div>
				<p class="tri-balance" data-net aria-live="polite"></p></div></section>
			<p class="tri-error" role="alert" hidden></p>`);
			root.find(".tri-photo img").one("error",function(){ this.remove(); });
			if (!editable) root.find("input,textarea").prop("disabled",true);
			if (problems.length && !Number(row.evidence_verified)) field("verified").prop("disabled",true);
			const next = editable && nextRow(frm,row.name);
			dialog.set_primary_action(editable ? (next ? "应用并核下一项" : "应用到明细") : "关闭",
				() => editable ? apply(Boolean(next)) : dialog.hide());
			if (next) {
				dialog.set_secondary_action(() => apply(false));
				dialog.set_secondary_action_label("仅应用本项");
			} else dialog.get_secondary_btn().addClass("hide");
			update();
			dialog.$wrapper.find(".modal-body").scrollTop(0);
		}
		function update() {
			root.find("[data-mode]").each((_,el) => el.setAttribute("aria-pressed",String(el.dataset.mode === mode)));
			section("variance").prop("hidden",mode !== "adjust");
			section("weights").prop("hidden",!field("weigh").prop("checked"));
			const short = flt(expected-amount("accepted")-amount("rejected"),9);
			root.find("[data-short]").text(short < 0 ? "超出随货量 "+qty(-short)+" "+unit : "短送 "+qty(short)+" "+unit);
			root.find("[data-net]").text("净重 "+qty(flt(amount("gross")-amount("tare"),9))+" 公斤");
		}
		function invalid(message, target) {
			root.find(".tri-error").text(message).prop("hidden",false);
			target?.trigger("focus");
		}
		async function apply(advance) {
			if (applying || !writable(frm)) return;
			if (!mode) return invalid("请先选择足量合格或登记差异。",root.find("[data-mode=full]"));
			for (const input of root.find('input[type="number"]:visible')) {
				if (!input.reportValidity()) return;
			}
			const accepted = mode === "full" ? expected : amount("accepted");
			const rejected = mode === "full" ? 0 : amount("rejected");
			const reason = mode === "adjust" ? String(field("reason").val() || "").trim() : "";
			if (!Number.isFinite(accepted+rejected) || accepted < 0 || rejected < 0 || flt(accepted+rejected-expected,9) > 0)
				return invalid("合格量与拒收量合计不能超过随货数量。",field("accepted"));
			if ((flt(expected-accepted,9) !== 0 || rejected) && !hasReason(reason))
				return invalid("请填写实际短送或拒收原因。",field("reason"));
			const weigh = field("weigh").prop("checked"), gross = weigh ? amount("gross") : 0, tare = weigh ? amount("tare") : 0;
			if (!Number.isFinite(gross+tare) || tare < 0 || gross < tare)
				return invalid("毛重须大于或等于皮重。",field("gross"));
			applying = true;
			try {
				await frappe.model.set_value(row.doctype,row.name,{
					accepted_qty:accepted, rejected_qty:rejected, reason, evidence_verified:Number(field("verified").prop("checked")),
					record_weight:Number(weigh), gross_weight:gross, tare_weight:tare
				});
				render(frm);
				const next = advance && nextRow(frm,row.name);
				if (next) {
					openRow(next);
					root.find("h3").trigger("focus");
				} else dialog.hide();
			} finally { applying = false; }
		}
		root.on("click","[data-mode]",function() {
			mode = this.dataset.mode;
			root.find(".tri-error").prop("hidden",true);
			update();
			if (mode === "adjust") field("accepted").trigger("focus");
		}).on("click","[data-fill]",() => {
			field("accepted").val(Math.max(0,flt(expected-amount("rejected"),9))).trigger("input");
		}).on("input change","input,textarea",() => {
			root.find(".tri-error").prop("hidden",true);
			update();
		});
		openRow(firstRow);
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
