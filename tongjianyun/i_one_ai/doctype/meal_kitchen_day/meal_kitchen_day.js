(() => {
	const type = "Meal Kitchen Day";
	const slots = ["早餐", "早点", "午餐", "午点", "晚餐"];
	const mealIcons = ["sunrise", "apple", "sun", "coffee", "moon"];
	const steps = [
		["prep", "shopping-basket", "领用备料"],
		["meals", "utensils", "逐餐供餐"],
		["ledger", "scale", "余料盘点"],
		["close", "clipboard-check", "日结复核"],
	];
	const actions = ["领用", "耗用", "退料", "损耗"];
	const esc = (value) => frappe.utils.escape_html(String(value ?? ""));
	const icon = (name) => frappe.utils.icon(name, "sm");
	const fmt = (value) => Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 9 });
	const balance = (r) => r.carry_out_qty ?? r.balance_qty;
	const rpc = async (method, args, freeze = false) =>
		(await frappe.call({ method: "tongjianyun.meal_kitchen." + method, args, freeze })).message;
	const btn = (act, label, primary = false, disabled = false) =>
		`<button type="button" data-act="${esc(act)}" class="ky-btn ${primary ? "ky-primary" : ""}" ${disabled ? "disabled" : ""}>${esc(label)}</button>`;
	const input = (map, code, unit, value, label) =>
		`<label class="ky-qty"><input type="number" inputmode="decimal" min="0" step="any" aria-label="${esc(label)}" data-map="${map}" data-code="${esc(code)}" value="${esc(value ?? "")}" placeholder="请输入"><span>${esc(__(unit))}</span></label>`;
	const photo = (url) => typeof url === "string" && /^\/(?:files|private\/files|assets)\//.test(url);
	const stockLink = (entry) => {
		if (entry.action === "耗用") {
			const label = esc(entry.name) + " · " + (entry.docstatus === 1 ? "已耗用" : "待库存主管审核");
			return entry.consumption_lines
				? `<button type="button" class="ky-entry" data-act="consumption:${esc(entry.name)}">耗用 · ${label}</button>`
				: `<span class="ky-entry">耗用 · ${label}</span>`;
		}
		return `<a class="ky-entry" href="/desk/stock-entry/${encodeURIComponent(entry.name)}">${esc(entry.action)} · ${esc(entry.name)}<small>${esc(entry.posting_date)} · ${["草稿", "已提交", "已取消"][entry.docstatus] || ""}</small></a>`;
	};
	function writable(frm) {
		return frm.doc.docstatus === 0 && !frm.is_new() && frm.perm?.[0]?.write && !frappe.boot.read_only;
	}
	function mealStatus(row, menu) {
		if (row.actual_confirmed) return Number(row.actual_headcount) ? "已确认" : "已确认停供";
		return menu?.suspended ? "待确认停供" : "待确认";
	}

	class KitchenDay {
		constructor(frm) {
			this.frm = frm;
			this.name = frm.doc.name;
			this.root = frm.fields_dict.ledger_html.$wrapper;
			this.view = frm.doc.docstatus ? "close" : "prep";
			this.meal = slots[0];
			this.stockEdits = new Map(actions.map((action) => [action, new Map()]));
			this.counts = new Map();
			this.mealEdits = new Map();
			this.query = "";
			this.lossReason = "";
			this.sequence = 0;
			this.root
				.off(".kday")
				.on("click.kday", "[data-act]", (e) => this.activate(e.currentTarget))
				.on("input.kday", "input,textarea", (e) => this.changed(e.currentTarget))
				.on("submit.kday", "form", (e) => e.preventDefault());
		}
		async load() {
			const token = ++this.sequence;
			if (this.ledger) this.draw();
			else this.root.html('<div class="ky-placeholder" role="status">正在读取当日供餐计划和库存流水…</div>');
			try {
				const ledger = await rpc("get_kitchen_ledger", { day_name: this.name, include_menu: 1 });
				if (token !== this.sequence || this.frm.doc.name !== this.name) return;
				if (ledger?.day_name !== this.name) throw new Error("未读取到本日流水。");
				if (this.ledger && this.ledger.basis_hash !== ledger.basis_hash) {
					this.counts.clear();
					this.carryNotes = undefined;
				}
				this.ledger = ledger;
				this.draw();
			} catch (e) {
				if (token !== this.sequence || this.frm.doc.name !== this.name) return;
				this.ledger = null;
				this.root.html(
					`<div class="ky-placeholder">暂时无法读取本日流水。 ${btn("refresh", "重新读取")}</div>`,
				);
			}
		}
		changed(el) {
			const s = el.dataset;
			if (s.map === "qty") this.quantities.set(s.code, el.value);
			if (s.map === "count") this.counts.set(s.code, el.value);
			if (s.key === "carry") this.carryNotes = el.value;
			if (s.key === "loss") this.lossReason = el.value;
			if (s.key === "query") {
				this.query = el.value;
				const term = this.query.trim().toLowerCase();
				this.root.find("[data-search]").each((_, r) => {
					r.hidden = !r.dataset.search.includes(term);
				});
				this.root
					.find(".ky-no-match")
					.prop("hidden", !term || this.root.find("[data-search]:not([hidden])").length > 0);
			}
			if (s.key === "actual" || s.key === "reason") {
				const row = this.mealRow();
				this.editFor(row)[s.key] = el.value;
				this.updateDifference(row);
			}
		}
		mealRow() {
			return (this.frm.doc.meals || []).find((r) => r.meal_type === this.meal);
		}
		editFor(row) {
			const source = JSON.stringify([row.actual_confirmed, row.actual_headcount, row.reason]);
			if (this.mealEdits.get(row.name)?.source !== source)
				this.mealEdits.set(row.name, {
					source,
					actual:
						row.actual_confirmed || Number(row.actual_headcount) > 0 ? String(row.actual_headcount || 0) : "",
					reason: row.reason || "",
				});
			return this.mealEdits.get(row.name);
		}
		get stockAction() {
			return this.view === "prep" ? "领用" : this.action;
		}
		get quantities() {
			return this.stockEdits.get(this.stockAction);
		}
		quantityFor(row) {
			if (this.quantities.has(row.item_code)) return this.quantities.get(row.item_code);
			if (this.stockAction === "耗用") return row.suggested_consumption_qty;
			return this.stockAction === "领用" ? row.suggested_issue_qty : "";
		}
		draw() {
			const frm = this.frm,
				d = frm.doc;
			if (!this.ledger || d.name !== this.name) return;
			this.root.addClass("ky-root");
			const editable = writable(frm);
			const stage =
				d.docstatus === 1
					? "已日结"
					: d.docstatus === 2
						? "已取消"
						: this.ledger.can_close
							? "待日结复核"
							: this.ledger.carry_required && !this.ledger.carry_confirmation_current
								? "待盘点"
								: "执行中";
			const weekday = frappe.datetime
				.str_to_obj(d.meal_date)
				.toLocaleDateString("zh-CN", { weekday: "short" });
			this.root
				.html(`<section class="ky-app"><header class="ky-heading"><div><h2>厨房每日执行</h2><p>${esc(d.company)}<i></i>${esc(d.meal_date)} · ${esc(weekday)}</p></div>
				<span class="ky-tag">${esc(stage)}</span></header>
				<nav class="ky-steps" aria-label="当日操作">${steps.map(([v, i, l]) => `<button type="button" data-act="view:${v}" aria-current="${this.view === v ? "step" : "false"}">${icon(i)}<b>${l}</b></button>`).join("")}</nav>
				${this.view === "prep" ? this.prep(editable && frappe.model.can_create("Stock Entry")) : this.view === "meals" ? this.service(editable) : this.view === "ledger" ? this.stock(editable) : this.review(editable)}</section>`);
			if (this.view === "meals" && this.mealRow()) this.updateDifference(this.mealRow());
			this.root.find("[data-key=query]").each((_, el) => this.changed(el));
			this.root.find("img").one("error", function () {
				this.remove();
			});
		}
		prep(editable) {
			const frm = this.frm,
				l = this.ledger,
				meals = frm.doc.meals || [];
			const issues = l.stock_entries.filter((r) => r.action === "领用");
			const pending = issues.filter((r) => r.docstatus === 0);
			const submitted = issues.filter((r) => r.docstatus === 1);
			const rows = l.rows.filter((r) => r.can_issue && r.allowed_actions.includes("领用"));
			const form = !pending.length && (!submitted.length || editable)
				? `<h4>领用明细</h4>${editable && rows.length ? '<p class="ky-help">本次数量默认按计划量扣除上日结余和今日已领量，可按实际领用修改。</p>' : ""}
					${this.qtyTable(rows, editable, true)}${editable && rows.length ? `<footer>${btn("draft", "生成领用单，待审核", true)}</footer>` : ""}`
				: "";
			return `<div class="ky-prep"><section class="ky-card"><header class="ky-hero"><h3>今日领用备料</h3><p>${esc(frm.doc.source_warehouse)} → ${esc(frm.doc.kitchen_warehouse)}</p></header>
				<div class="ky-card-body">${[...pending, ...submitted].map((entry) => this.issueCard(entry)).join("")}
				${submitted.length && form ? `<details class="ky-extra-issue"><summary>追加领用</summary>${form}</details>` : form}
				</div></section>
				<section class="ky-card ky-card-body"><h3>今日供餐</h3>${slots
					.map((s, i) => {
						const r = meals.find((x) => x.meal_type === s);
						if (!r) return "";
						const m = l.menus?.[s];
						return `<button type="button" class="ky-slot" data-act="meal:${s}"><span class="ky-icon">${icon(mealIcons[i])}</span><span><b>${s}</b><small>${m?.suspended ? "计划停供" : "计划 " + fmt(r.planned_headcount) + " 人"}</small></span><em class="ky-pill ${r.actual_confirmed ? "ok" : m?.suspended ? "muted" : "pending"}">${mealStatus(r, m)}</em></button>`;
					})
					.join("")}<footer>${btn("view:ledger", "查看库存流水")}</footer></section></div>`;
		}
		issueCard(entry) {
			const done = entry.docstatus === 1;
			const rows = this.ledger.rows.filter((row) => Number(entry.issue_quantities?.[row.item_code]) > 0);
			return `<section class="ky-issue-card"><header class="ky-between"><h4>${done ? "领用结果" : "领用单"}</h4>
				<span class="ky-pill ${done ? "ok" : "pending"}">${done ? "已领用" : "待库存主管审核"}</span></header>
				<a href="/desk/stock-entry/${encodeURIComponent(entry.name)}">${esc(entry.name)}</a>
				${done ? `<p class="ky-issue-meta">实际领用日期 ${esc(entry.posting_date)} · 供餐日期 ${esc(this.frm.doc.meal_date)}</p>` : ""}
				${rows.length ? `<ul class="ky-issue-lines">${rows.map((r) => `<li><span>${esc(r.item_name || r.item_code)}</span><b>${fmt(entry.issue_quantities[r.item_code])} ${esc(__(r.stock_uom))}</b></li>`).join("")}</ul>` : ""}
				${done && entry.approved_by ? `<p class="ky-help">审核人 ${esc(entry.approved_by)} · ${esc(frappe.datetime.str_to_user(entry.approved_at))}</p>` : ""}
				<footer>${done ? btn("view:meals", "去逐餐供餐", true) : btn("refresh", "刷新状态")}
				${entry.issue_quantities ? btn("issue:" + entry.name, entry.can_review ? "审核领用" : "查看领用明细", entry.can_review) : ""}</footer></section>`;
		}
		issueDetails(entry, canApprove) {
			const rows = this.ledger.rows.filter((r) => r.can_issue || r.item_code in entry.issue_quantities);
			return `<div class="ky-issue-route"><div><small>领出仓库</small><b>${esc(entry.source_warehouse)}</b></div>
				<span aria-hidden="true">→</span><div><small>领入仓库</small><b>${esc(entry.kitchen_warehouse)}</b></div></div>
				<p class="ky-issue-meta">${esc(entry.name)} · 供餐日期 ${esc(this.frm.doc.meal_date)}</p>
				${canApprove ? `<label class="ky-issue-date">实际领用日期
					<input type="date" required data-issue-date max="${esc(entry.latest_issue_date)}" value="${esc(entry.latest_issue_date)}">
					<small>按食材从原料仓交给厨房的日期记账。</small></label>`
					: `<p class="ky-issue-meta">实际领用日期 · ${entry.docstatus === 1 ? esc(entry.posting_date) : "待交接确认"}</p>`}
				<table><thead><tr><th>食材</th><th>当日计划量</th><th>本次领用</th></tr></thead><tbody>${rows.map((r) => {
					const qty = entry.issue_quantities[r.item_code] || "0";
					const diff = Number(qty) !== Number(r.planned_qty);
					const unit = esc(__(r.stock_uom));
					return `<tr><th>${esc(r.item_name || r.item_code)}</th><td>${fmt(r.planned_qty)} ${unit}</td>
						<td><b>${fmt(qty)} ${unit}</b>${diff ? '<small class="ky-issue-diff">与计划有差异</small>' : ""}</td></tr>`;
				}).join("")}</tbody></table>`;
		}
		consumptionDetails(entry, canApprove) {
			const pending = entry.docstatus === 0;
			const ingredients = new Map(this.ledger.rows.map((row) => [row.item_code, row]));
			const lines = Object.entries(entry.consumption_lines).map(([code, line]) => {
				const row = ingredients.get(code);
				const unit = esc(__(row?.stock_uom || ""));
				const quantity = (qty) => `${fmt(qty)} ${unit}`;
				return `<tr><th>${esc(row?.item_name || code)}</th>${pending ? `<td>${quantity(line.before)}</td>` : ""}
					<td><b>${quantity(line.qty)}</b></td>${pending ? `<td>${quantity(line.after)}</td>` : ""}</tr>
					${line.lot_warning ? `<tr><td colspan="4" class="ky-lot-warning">${esc(line.lot_warning)}</td></tr>` : ""}`;
			});
			return `<div class="ky-issue-route"><div><small>耗用仓库</small><b>${esc(entry.kitchen_warehouse)}</b></div><span></span>
				<div><small>供餐日期</small><b>${esc(this.frm.doc.meal_date)}</b></div></div>
				<p class="ky-issue-meta">${esc(entry.name)} · 经办人 ${esc(entry.prepared_by)}</p>
				${canApprove ? `<label class="ky-issue-date">实际耗用日期
					<input type="date" required data-consumption-date min="${esc(entry.earliest_consumption_date)}" max="${esc(entry.latest_consumption_date)}" value="${esc(entry.consumption_date)}">
					<small>按实际加工用料的日期扣库。食材批次须在供餐日有效。</small></label>`
					: `<p class="ky-issue-meta">实际耗用日期 · ${pending ? "待主管确认" : esc(entry.posting_date)}</p>`}
				<table><thead><tr><th>食材</th>${pending ? "<th>厨房结存</th>" : ""}<th>本次耗用</th>${pending ? "<th>确认后结存</th>" : ""}</tr></thead>
				<tbody>${lines.join("")}</tbody></table>
				${pending && !entry.can_review ? '<p class="ky-help">由另一位有提交权限的库存主管确认耗用。</p>' : ""}
				${entry.approved_by ? `<p class="ky-issue-meta">审核人 ${esc(entry.approved_by)} · ${esc(frappe.datetime.str_to_user(entry.approved_at))}</p>` : ""}`;
		}
		openStockReview(name, action) {
			const entry = this.ledger.stock_entries.find((e) => e.name === name && e.action === action);
			const isIssue = action === "领用";
			if (!(isIssue ? entry?.issue_quantities : entry?.consumption_lines) || this.stockDialog) return;
			const canApprove = entry.docstatus === 0 && entry.can_review && !frappe.boot.read_only;
			const dialog = new frappe.ui.Dialog({
				title: canApprove ? "审核" + action : action + "明细",
				no_submit_on_enter: true,
				fields: [{fieldname: "details", fieldtype: "HTML"}],
			});
			this.stockDialog = dialog;
			dialog.$wrapper.addClass("ky-issue-drawer").one("hidden.bs.modal", () => {
				this.stockDialog = null;
				dialog.$wrapper.remove();
			});
			const body = dialog.fields_dict.details.$wrapper;
			let review = entry;
			let revision = 0;
			const render = () => {
				const details = isIssue ? this.issueDetails(review, canApprove) : this.consumptionDetails(review, canApprove);
				body.html(details + (review.review_blocker ? `<p class="ky-issue-note" role="status">${esc(review.review_blocker)}</p>` : ""));
			};
			render();
			if (canApprove) {
				if (!isIssue) body.on("change", "[data-consumption-date]", async (event) => {
					const input = event.currentTarget;
					const selected = input.value;
					const version = ++revision;
					review = {...entry, consumption_date: selected, review_token: null};
					dialog.get_primary_btn().prop("disabled", true);
					if (!input.reportValidity()) return;
					try {
						const refreshed = await rpc("preview_kitchen_consumption_date", {
							day_name: this.name, stock_entry: entry.name, consumption_date: selected,
						});
						if (this.stockDialog !== dialog || version !== revision) return;
						if (!refreshed?.review_token || refreshed.consumption_date !== selected) throw new Error();
						review = {...entry, ...refreshed};
					} catch {
						if (this.stockDialog !== dialog || version !== revision) return;
						review.review_blocker = "未能核对所选日期的库存，请重选日期或重新打开耗用明细。";
					}
					render();
					dialog.get_primary_btn().prop("disabled", !review.review_token || !!review.review_blocker);
				});
				dialog.set_primary_action(isIssue ? "确认领用并调拨" : "确认耗用并扣减库存", async () => {
					if (this.approving || !review.review_token || review.review_blocker || cur_frm !== this.frm || this.frm.doc.name !== this.name) return;
					const args = {day_name: this.name, stock_entry: entry.name, review_token: review.review_token};
					if (isIssue) {
						const dateInput = body.find("[data-issue-date]")[0];
						if (!dateInput.reportValidity()) return;
						args.issue_date = dateInput.value;
					} else {
						const input = body.find("[data-consumption-date]")[0];
						if (!input.reportValidity() || input.value !== review.consumption_date) return;
						args.consumption_date = input.value;
					}
					this.approving = true;
					try {
						const result = await rpc(isIssue ? "approve_kitchen_issue" : "approve_kitchen_consumption", args, true);
						if (result?.stock_entry !== entry.name) throw new Error("未取得审核结果，请刷新状态。");
						if (!isIssue) this.action = null;
						frappe.show_alert({message: isIssue ? "领用已审核，调拨完成" : "耗用已审核，厨房结存已更新", indicator: "green"});
					} catch (e) {
						if (!e?._server_messages && !e?.responseJSON?._server_messages)
							frappe.msgprint(esc(e?.message || "审核未确认，请刷新后核对。"));
					} finally {
						this.approving = false;
						dialog.hide();
						if (cur_frm === this.frm && this.frm.doc.name === this.name) await this.load();
					}
				});
				dialog.get_primary_btn().prop("disabled", !!entry.review_blocker);
			}
			dialog.show();
		}
		qtyTable(rows, editable, prep) {
			if (!rows.length) return '<p class="ky-empty">本日没有可操作的食材。</p>';
			return `<div class="ky-scroll"><table><thead><tr><th>食材</th><th>${prep ? "计划量" : "厨房结存"}</th>${editable ? "<th>本次数量</th>" : ""}</tr></thead><tbody>${rows.map((r) => `<tr><th>${esc(r.item_name || r.item_code)}</th><td>${fmt(prep ? r.planned_qty : balance(r))} ${esc(__(r.stock_uom))}</td>${editable ? `<td>${input("qty", r.item_code, r.stock_uom, this.quantityFor(r), r.item_name + "本次数量")}</td>` : ""}</tr>`).join("")}</tbody></table></div>`;
		}
		service(editable) {
			const l = this.ledger,
				row = this.mealRow();
			if (!row) return '<p class="ky-empty">本日缺少对应餐次。</p>';
			const menu = l.menus?.[this.meal] || {},
				ed = this.editFor(row);
			return `<nav class="ky-meals" aria-label="选择餐次">${slots
				.map((s, i) => {
					const r = this.frm.doc.meals.find((x) => x.meal_type === s);
					return r
						? `<button type="button" data-act="meal:${s}" aria-pressed="${s === this.meal}">${icon(mealIcons[i])}<b>${s}</b><small>${mealStatus(r, l.menus?.[s])}</small></button>`
						: "";
				})
				.join("")}</nav><div class="ky-pair"><section class="ky-card ky-card-body"><h3>${this.meal}菜单</h3>
				${menu.suspended ? `<p class="ky-empty">计划停供${menu.reason ? " · " + esc(menu.reason) : ""}</p>` : (menu.dishes || []).map((d) => `<div class="ky-dish"><span class="ky-photo">${icon("utensils")}${photo(d.image) ? `<img src="${esc(d.image)}" alt="">` : ""}</span><b>${esc(d.name)}</b></div>`).join("") || '<p class="ky-empty">暂无已编排菜品</p>'}</section>
				<section class="ky-card ky-card-body"><h3>${editable ? "确认" : ""}${this.meal}人数</h3><p>计划供餐 <b>${fmt(row.planned_headcount)}</b> 人</p>
				<div class="ky-stepper">${editable ? btn("minus", "−") : ""}<label><input data-key="actual" aria-label="实际供餐人数" type="number" min="0" step="1" inputmode="numeric" placeholder="实际人数" value="${esc(ed.actual)}" ${editable ? "" : "disabled"}></label>${editable ? btn("plus", "＋") : ""}</div>
				<div class="ky-diff"><span data-diff></span>${editable ? btn("use-plan", menu.suspended ? "填入停供人数 0" : "按计划填入") : ""}</div>
				<label class="ky-label">差异或停供原因<textarea data-key="reason" rows="2" ${editable ? "" : "disabled"}>${esc(ed.reason)}</textarea></label>
				${editable ? `<footer>${btn("confirm-meal", `确认${this.meal}人数`, true)}</footer>` : ""}</section></div>`;
		}
		updateDifference(row) {
			const value = this.editFor(row).actual,
				delta = Number(value) - Number(row.planned_headcount);
			this.root
				.find("[data-diff]")
				.text(
					value === ""
						? "待登记实际人数"
						: Number(value) === 0
							? "实际停供，请填写原因"
							: delta === 0
								? "与计划人数一致"
								: `比计划${delta > 0 ? "多" : "少"} ${fmt(Math.abs(delta))} 人`,
				);
		}
		consumptionCard(entry) {
			const done = entry.docstatus === 1;
			return `<section class="ky-card ky-card-body"><header class="ky-between"><h3>耗用单</h3>
				<span class="ky-pill ${done ? "ok" : "pending"}">${done ? "已耗用" : "待库存主管审核"}</span></header>
				<p class="ky-issue-meta">${esc(entry.name)} · 供餐日期 ${esc(this.frm.doc.meal_date)}${done ? " · 实际耗用 " + esc(entry.posting_date) : ""}</p>
				${done && entry.approved_by ? `<p class="ky-help">审核人 ${esc(entry.approved_by)} · ${esc(frappe.datetime.str_to_user(entry.approved_at))}</p>` : ""}
				${!done ? '<p class="ky-help">由另一位库存主管核对实际耗用，确认后扣减厨房库存。</p>' : ""}
				${entry.review_blocker ? `<p class="ky-issue-note">${esc(entry.review_blocker)}</p>` : ""}
				<footer>${btn("refresh", "刷新状态")}${entry.consumption_lines ? btn("consumption:" + entry.name, entry.can_review ? "审核耗用" : "查看耗用明细", !!entry.can_review) : ""}</footer></section>`;
		}
		stock(editable) {
			const l = this.ledger,
				headers = ["期初", "领用", "耗用", "退料", "损耗", "结存"];
			const canStock = editable && frappe.model.can_create("Stock Entry");
			const recent = l.stock_entries || [];
			const consumptions = recent.filter((e) => e.action === "耗用" && e.docstatus !== 2);
			const latest = consumptions.find((e) => e.docstatus === 0) || consumptions.at(-1);
			const panel = this.action && canStock ? this.stockForm()
				: `<div class="ky-stock-panel">${latest ? this.consumptionCard(latest) : ""}${this.carry(editable)}</div>`;
			return `<div class="ky-ledger"><section class="ky-card ky-card-body"><h3>食材收支明细</h3><div class="ky-tools"><input type="search" data-key="query" aria-label="查找食材" placeholder="查找食材" value="${esc(this.query)}">
				${canStock ? actions.map((a) => btn("stock:" + a, a)).join("") : ""}${btn("refresh", "刷新流水")}</div>
				<div class="ky-scroll"><table><thead><tr><th>食材</th>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${l.rows.map((r) => `<tr data-search="${esc([r.item_name, r.item_code].join(" ").toLowerCase())}"><th>${esc(r.item_name || r.item_code)}<small>${esc(__(r.stock_uom))}</small></th>${[r.opening_qty, r.issued_qty, r.consumed_qty, r.returned_qty, r.loss_qty, balance(r)].map((q) => `<td>${fmt(q)}</td>`).join("")}</tr>`).join("")}</tbody></table></div><p class="ky-no-match ky-empty" hidden>没有匹配的食材。</p>
				<p class="ky-help">仅已提交的库存单计入余额。</p>${l.opening_day?.day_name ? `<a href="/desk/meal-kitchen-day/${encodeURIComponent(l.opening_day.day_name)}">查看期初来源日结</a>` : ""}
				${recent.length ? `<h4>关联库存单</h4>${recent.map(stockLink).join("")}` : ""}</section>${panel}</div>`;
		}
		stockForm() {
			const a = this.action,
				pending = this.ledger.stock_entries.find((r) => r.action === a && !r.docstatus);
			if (a === "耗用" && pending) return this.consumptionCard(pending);
			const rows = this.ledger.rows.filter(
				(r) => r.allowed_actions.includes(a) && (a !== "领用" || r.can_issue),
			);
			const hint = !pending && a === "耗用" && rows.length
				? '<p class="ky-help">按当日剩余计划量预填，最多填至厨房结存。请按实际耗用修改，未使用的食材填 0 或留空。</p>' : "";
			return `<aside class="ky-card ky-card-body"><div class="ky-between"><h3>登记${a}</h3>${btn("carry", "返回盘点")}</div>${hint}${pending ? stockLink(pending) : this.qtyTable(rows, true, false)}
				${!pending && rows.length ? `${a === "损耗" ? `<label class="ky-label">损耗原因<textarea data-key="loss">${esc(this.lossReason)}</textarea></label>` : ""}<footer>${btn("draft", a === "耗用" ? "提交耗用审核" : "生成" + a + "草稿", true)}</footer>` : ""}</aside>`;
		}
		carry(editable) {
			const l = this.ledger,
				rows = l.rows.filter((r) => Number(balance(r)) > 0);
			const future = this.frm.doc.meal_date > frappe.datetime.get_today();
			const canCount = editable && !future && !l.has_drafts;
			return `<aside class="ky-card ky-card-body"><h3>${icon("scale")} 清点厨房余料</h3>${
				!rows.length
					? '<p class="ky-empty">本日没有正结存，无需盘点余料。</p>'
					: `
				<p class="ky-pill ${l.carry_confirmation_current ? "ok" : "pending"}">${rows.length} 项${l.carry_confirmation_current ? "已实盘" : "待盘点"}</p>
				${rows.map((r) => `<div class="ky-count"><b>${esc(r.item_name || r.item_code)}</b><small>账面 ${fmt(balance(r))} ${esc(__(r.stock_uom))}</small>${l.carry_confirmation_current ? `<small>已盘 ${fmt(l.physical_counts?.[r.item_code])} ${esc(__(r.stock_uom))}</small>` : ""}${canCount ? input("count", r.item_code, r.stock_uom, this.counts.get(r.item_code), r.item_name + "实盘量") : ""}</div>`).join("")}
				<label class="ky-label">留厨说明<textarea data-key="carry" ${canCount ? "" : "disabled"}>${esc(this.carryNotes ?? this.frm.doc.carry_notes ?? "")}</textarea></label>
				${canCount ? `<footer>${btn("count", "保存实盘记录", true)}</footer>` : editable ? `<p class="ky-help">${future ? "供餐日当天可登记实盘。" : "先处理未提交的库存单，再清点余料。"}</p>` : ""}`
			}</aside>`;
		}
		review(editable) {
			const l = this.ledger,
				d = this.frm.doc,
				closed = d.docstatus === 1;
			const confirmed = (d.meals || []).filter((r) => r.actual_confirmed).length;
			const blocks = d.docstatus ? [] : l.blockers || [];
			const permitted =
				editable &&
				this.frm.perm?.[0]?.submit &&
				d.owner !== frappe.session.user &&
				(!l.carry_confirmation_current || l.carry_reviewer !== frappe.session.user) &&
				!frappe.workflow.has_workflow(this.frm.doc);
			return `<section class="ky-card ky-card-body"><h3>${closed ? "当日日结记录" : "日结复核"}</h3><div class="ky-checks">
				<div><b>实际供餐人数</b><span>${confirmed} / 5 餐已确认</span>${btn("view:meals", "查看餐次")}</div>
				<div><b>库存单据</b><span>${l.has_drafts ? "有待处理草稿" : "已提交流水 " + l.stock_entries.filter((r) => r.docstatus === 1).length + " 笔"}</span>${btn("view:ledger", "查看流水")}</div>
				<div><b>厨房余料</b><span>${l.carry_required ? (l.carry_confirmation_current ? "已实盘" : "待实盘") : "无正结存"}</span>${btn("view:ledger", "查看余料")}</div></div>
				${blocks.length ? `<ul class="ky-blockers">${blocks.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>` : ""}
				${closed ? `<p>审核人 ${esc(d.approved_by || "—")} · ${esc(d.approved_at || "")}</p>` : editable ? `<footer><small>由另一位有权限的审核人员完成日结。</small>${permitted ? btn("submit", "复核并提交日结", true, !l.can_close) : ""}</footer>` : ""}</section>`;
		}
		async activate(el) {
			const [a, key] = el.dataset.act.split(":");
			if (this.busy) return;
			if (a === "refresh") return this.load();
			if (a === "issue" || a === "consumption")
				return this.openStockReview(el.dataset.act.slice(a.length + 1), a === "issue" ? "领用" : "耗用");
			if (a === "view" || a === "meal" || a === "stock" || a === "carry") {
				if (a === "view") {
					this.view = key;
					if (key === "prep") this.action = "领用";
					if (key === "ledger") this.action = null;
				} else if (a === "meal") {
					this.view = "meals";
					this.meal = key;
				} else {
					this.view = a === "stock" && key === "领用" ? "prep" : "ledger";
					this.action = a === "carry" ? null : key;
				}
				return this.draw();
			}
			if (!writable(this.frm)) return;
			const row = this.mealRow();
			if (["minus", "plus", "use-plan"].includes(a)) {
				const ed = this.editFor(row);
				ed.actual = String(
					a === "use-plan"
						? Number(row.planned_headcount)
						: Math.max(0, Number(ed.actual || 0) + (a === "plus" ? 1 : -1)),
				);
				this.root.find("[data-key=actual]").val(ed.actual);
				return this.updateDifference(row);
			}
			this.busy = true;
			el.disabled = true;
			try {
				if (a === "confirm-meal") await this.confirmMeal(row);
				else if (a === "draft") await this.createDraft();
				else if (a === "count") await this.confirmCarry();
				else if (a === "submit" && this.ledger.can_close) await this.frm.savesubmit();
			} catch (e) {
				if (!e?._server_messages && !e?.responseJSON?._server_messages)
					frappe.msgprint(esc(e?.message || "操作未完成，请重新核对。"));
			} finally {
				this.busy = false;
				el.disabled = false;
			}
		}
		async confirmMeal(row) {
			const ed = this.editFor(row),
				actual = Number(ed.actual);
			if (!ed.actual.trim() || !Number.isSafeInteger(actual) || actual < 0)
				throw new Error("请填写实际供餐人数，停供填 0。");
			if ((actual === 0 || actual !== Number(row.planned_headcount)) && !ed.reason.trim())
				throw new Error("请填写差异或停供原因。");
			await frappe.model.set_value(row.doctype, row.name, "actual_headcount", actual);
			await frappe.model.set_value(row.doctype, row.name, "reason", ed.reason.trim());
			await frappe.model.set_value(row.doctype, row.name, "actual_confirmed", 1);
			if (this.frm.is_dirty()) await this.frm.save();
			this.mealEdits.delete(row.name);
			await this.load();
			frappe.show_alert({ message: row.meal_type + "人数已确认", indicator: "green" });
		}
		async createDraft() {
			if (this.frm.is_dirty()) throw new Error("请先保存执行资料，再生成库存单。");
			const action = this.stockAction,
				items = [];
			const eligible = this.ledger.rows.filter((r) => r.allowed_actions.includes(action));
			for (const r of eligible) {
				const v = this.quantityFor(r);
				if (!v || v === "0") continue;
				const qty = Number(v);
				if (!Number.isFinite(qty) || qty < 0) throw new Error("数量须为非负数。");
				if (qty > 0) items.push({ item_code: r.item_code, qty: v });
			}
			if (!items.length) throw new Error("请至少填写一种食材的实际操作量。");
			if (action === "损耗" && !this.lossReason.trim()) throw new Error("请填写实际损耗原因。");
			const result = await rpc(
				"create_kitchen_stock_entry",
				{ day_name: this.name, action, items, reason: action === "损耗" ? this.lossReason : "" },
				true,
			);
			if (!result?.stock_entry) throw new Error("未取得库存单草稿。");
			this.quantities.clear();
			if (action === "领用" || action === "耗用") {
				this.view = action === "领用" ? "prep" : "ledger";
				await this.load();
				frappe.show_alert({message: action + "单待库存主管审核", indicator: "green"});
				return;
			}
			if (action === "损耗") this.lossReason = "";
			frappe.set_route("Form", "Stock Entry", result.stock_entry);
		}
		async confirmCarry() {
			if (this.frm.is_dirty()) throw new Error("请先保存执行资料，再登记实盘。");
			const positive = this.ledger.rows.filter((r) => Number(balance(r)) > 0);
			const physical_counts = positive.map((r) => ({
				item_code: r.item_code,
				qty: this.counts.get(r.item_code) || "",
			}));
			if (
				!positive.length ||
				physical_counts.some((r) => !r.qty.trim() || !Number.isFinite(Number(r.qty)) || Number(r.qty) < 0)
			)
				throw new Error("请填写每项余料的实际清点数量。");
			const notes = (this.carryNotes ?? this.frm.doc.carry_notes ?? "").trim();
			if (!notes) throw new Error("请填写食材留厨说明。");
			const result = await rpc(
				"confirm_kitchen_carry",
				{ day_name: this.name, physical_counts, notes },
				true,
			);
			if (!result?.carry_confirmed) throw new Error("实盘未确认，请刷新流水核对。");
			this.counts.clear();
			this.carryNotes = undefined;
			await this.frm.reload_doc();
			frappe.show_alert({ message: "清点记录已保存", indicator: "green" });
		}
	}
	frappe.ui.form.on(type, {
		setup(frm) {
			frm.set_query("kitchen_warehouse", () => ({
				filters: { company: frm.doc.company, is_group: 0, name: ["!=", frm.doc.source_warehouse] },
			}));
		},
		refresh(frm) {
			for (const field of ["meals", "items"]) {
				const grid = frm.fields_dict[field]?.grid;
				if (grid) {
					grid.cannot_add_rows = true;
					grid.cannot_delete_rows = true;
				}
			}
			if (frm.is_new()) {
				frm.fields_dict.ledger_html.$wrapper.html(
					'<p class="ky-placeholder">请从已提交周食谱的「厨房执行 → 打开每日执行」建立当日记录。</p>',
				);
				return;
			}
			if (frm._kitchen?.name !== frm.doc.name) frm._kitchen = new KitchenDay(frm);
			if (frm.doc.docstatus === 0 && !frm.is_dirty() && !frappe.workflow.has_workflow(frm.doc)) {
				if (frm.toolbar.get_action_status() === "Submit") {
					frm.page.set_primary_action(__("查看日结清单"), () => {
						frm.fields_dict.ledger_html.tab?.set_active();
						frm._kitchen.view = "close";
						frm._kitchen.load();
					});
				}
				frm.layout.message?.children(".form-message").filter((_, el) =>
					el.textContent.trim() === __("Submit this document to confirm")
				).remove();
			}
			frm._kitchen.load();
			frm.add_custom_button(__("周食谱计划"), () =>
				frappe.set_route("Form", "Meal Planning Week", frm.doc.meal_week),
			);
		},
		async before_submit(frm) {
			if (frm.doc.meals?.length !== 5 || frm.doc.meals.some((r) => !r.actual_confirmed))
				frappe.throw("请逐一确认五个餐次的实际供餐人数。");
			if (
				frm.doc.meals.some(
					(r) =>
						(Number(r.actual_headcount) === 0 ||
							Number(r.actual_headcount) !== Number(r.planned_headcount)) &&
						!r.reason?.trim(),
				)
			)
				frappe.throw("请填写人数差异或停供原因。");
			const ledger = await rpc("get_kitchen_ledger", { day_name: frm.doc.name });
			if (!ledger?.can_close) frappe.throw(esc(ledger?.blockers?.join(" ") || "请先核对本日库存流水。"));
		},
	});
	frappe.ui.form.on("Meal Kitchen Meal", {
		actual_headcount(frm, cdt, cdn) {
			return frappe.model.set_value(cdt, cdn, "actual_confirmed", 0);
		},
	});
})();
