(() => {
	const method = "tongjianyun.canteen_ops.delivery_lots.apply_lots";
	const number = new Intl.NumberFormat("zh-CN", {maximumFractionDigits: 9});
	const incomplete = row => !row.lot_number?.trim() || !row.manufactured_on || !row.expires_on;
	const escape = value => frappe.utils.escape_html(String(value ?? ""));
	const button = (key, caption, css = "") =>
		`<button type="button" data-action="${key}" class="${css}">${caption}</button>`;

	function open(frm) {
		if (frm.is_new() || frm.doc.docstatus || !frm.perm?.[0]?.write ||
			!["待接单", "已接单", "备货", "分拣"].includes(frm.doc.progress)) return;
		const name = frm.doc.name;
		const dialog = new frappe.ui.Dialog({
			title: "快速补录配送明细", size: "extra-large", no_submit_on_enter: true,
			fields: [{fieldname: "entry", fieldtype: "HTML"}],
		});
		const root = dialog.fields_dict.entry.$wrapper.addClass("tjy-lots");
		dialog.$wrapper.addClass("tjy-lots-dialog");
		root.html(`<div class="lots-toolbar">
			<div class="lots-progress" aria-live="polite"></div>
			<label>需求日期<select data-filter="date"></select></label>
			<div class="lots-switch" role="group" aria-label="展示范围">${button("pending","待补")}${button("all","全部")}</div>
		</div><div class="lots-layout">
			<aside><label>查找食材<input data-filter="search" type="search" placeholder="输入食材名称或编码"></label>
			<div class="lots-groups" aria-label="食材列表"></div></aside>
			<section class="lots-editor" aria-label="补录所选食材"></section>
		</div>`);
		let rows, names, dates, version, code = "", date = "", mode = "pending", search = "";
		let detailOnMobile = false, saving = false, needsReload = false;
		const drafts = new Map();
		const key = () => JSON.stringify([code, date, mode]);
		const title = id => names[id] || id;
		const demand = row => dates[row.order_item] || "";
		const blank = () => ({lot_number:"", manufactured_on:"", expires_on:""});
		function read() {
			rows = (frm.doc.items || []).map(r => ({...r}));
			names = frm.doc.__onload?.delivery_item_names || {};
			dates = frm.doc.__onload?.delivery_order_dates || {};
			version = frm.doc.modified;
		}
		function visibleGroups() {
			const groups = new Map();
			for (const row of rows) {
				if (date && demand(row) !== date || mode === "pending" && !incomplete(row)) continue;
				if (!(title(row.item_code) + " " + row.item_code).toLowerCase().includes(search)) continue;
				if (!groups.has(row.item_code)) groups.set(row.item_code, []);
				groups.get(row.item_code).push(row);
			}
			return groups;
		}
		function draft(group) {
			if (!drafts.has(key())) {
				const only = group.length === 1 && incomplete(group[0]) && !group[0].lot_number ? group[0] : null;
				drafts.set(key(), {selected: new Set(only ? [only.name] : []), split: false,
					first: only ? {...only} : blank(), second: blank(), quantity: "", typed: false});
			}
			return drafts.get(key());
		}
		function refreshFilters() {
			const options = [...new Set(Object.values(dates).filter(Boolean))].sort();
			root.find('[data-filter="date"]').html('<option value="">全部日期</option>' +
				options.map(v => `<option value="${escape(v)}">${escape(v)}</option>`).join("")).val(date);
			root.find(".lots-switch button").each((_, b) => b.setAttribute("aria-pressed", b.dataset.action === mode));
			const done = rows.filter(row => !incomplete(row)).length;
			root.find(".lots-progress").html(`<strong>已补 ${done} / ${rows.length} 行</strong><progress max="${rows.length || 1}" value="${done}"></progress>`);
		}
		function lotInputs(id, values, label) {
			const inputs = [["lot_number","供应商批号","text"],["manufactured_on","生产日期","date"],["expires_on","有效期","date"]]
				.map(([field,caption,type]) => `<label>${caption}<input type="${type}" data-lot="${id}" data-field="${field}"
					value="${escape(values[field])}" ${field === "lot_number" ? 'maxlength="140" placeholder="按包装或随货单填写"' : ""} required></label>`).join("");
			return `<fieldset><legend>${label}</legend><div class="lots-inputs">${inputs}</div></fieldset>`;
		}
		function render() {
			const groups = visibleGroups();
			if (!groups.has(code)) code = groups.keys().next().value || "";
			if (!code) detailOnMobile = false;
			root.toggleClass("show-detail", detailOnMobile);
			refreshFilters();
			root.find(".lots-groups").html([...groups].map(([id, group]) => {
				const pending = group.filter(incomplete).length;
				return `<button type="button" data-code="${escape(id)}" aria-pressed="${id === code}">
					<span>${escape(title(id))}</span><small>${pending ? pending+" 行待补" : "已补齐"}</small></button>`;
			}).join("") || '<p class="lots-empty">当前筛选下没有食材。</p>');
			const editor = root.find(".lots-editor");
			if (!code) {
				editor.html('<p class="lots-empty">可切换到「全部」，或调整日期和搜索条件。</p>');
				return;
			}
			const group = groups.get(code), data = draft(group);
			const selected = group.filter(row => data.selected.has(row.name));
			const single = selected.length === 1 ? selected[0] : null;
			if (!single) data.split = false;
			const eligible = group.filter(r => incomplete(r) && !r.lot_number);
			const selectAll = eligible.length && eligible.every(r => data.selected.has(r.name));
			const lines = group.map(row => `<label class="lots-line">
				<input type="checkbox" data-row="${escape(row.name)}" ${data.selected.has(row.name) ? "checked" : ""}>
				<span><strong>${escape(demand(row) || "需求日未登记")}</strong><small>第 ${row.idx} 行</small></span>
				<span>${number.format(row.quantity)} ${escape(row.uom)}</span>
				<span class="lots-existing">${escape(row.lot_number || "待填批号")}<small>${row.manufactured_on || row.expires_on ?
					escape((row.manufactured_on || "待填") + " 至 " + (row.expires_on || "待填")) : ""}</small></span></label>`).join("");
			editor.html(`${button("back","‹ 食材列表","lots-back")}
				<div class="lots-heading"><h3>${escape(title(code))}</h3><span>${group.length} 行配送明细</span></div>
				<div class="lots-list-head"><span>选择同一批货对应的行</span>
				${eligible.length ? button("select",selectAll ? "取消勾选待补行" : "勾选本食材待补行","lots-link") : ""}</div>
				<div class="lots-lines">${lines}</div>
				<div class="lots-edit-mode"><strong>${data.split ? "拆成两批" : "填写批次资料"}</strong>
				${single ? button("split",data.split ? "返回同批填写" : "拆成两批","lots-link") : ""}</div>
				${data.split ? `<div class="lots-quantities"><label>第一批数量（${escape(single.uom)}）<input type="number" data-quantity min="0" step="any" value="${escape(data.quantity)}"></label>
				<div>第二批数量<strong class="lots-remainder"></strong></div><div>原行数量<strong>${number.format(single.quantity)} ${escape(single.uom)}</strong></div></div>` : ""}
				${lotInputs("first",data.first,data.split ? "第一批" : "同批食材共用以下资料")}
				${data.split ? lotInputs("second",data.second,"第二批") : ""}
				<div class="lots-footer"><span aria-live="polite">${selected.length ? "已选 " + selected.length + " 行" : "请先勾选配送明细"}</span>
				${button("save", data.split ? "保存两批并继续" : "应用到 " + selected.length + " 行并继续","lots-save")}</div>
				${needsReload ? button("reload","重新读取最新明细","lots-link") : ""}`);
			editor.find('[data-action="save"]').prop("disabled", !selected.length || saving || needsReload);
			updateRemainder();
		}
		function updateRemainder() {
			const data = drafts.get(key());
			if (!data?.split) return;
			const row = rows.find(r => data.selected.has(r.name));
			const left = Number(row.quantity) - Number(data.quantity);
			root.find(".lots-remainder").text(data.quantity && left > 0 ? number.format(left)+" "+row.uom : "—");
		}
		function seedSelected(data, group) {
			if (data.typed) return;
			const chosen = group.filter(row => data.selected.has(row.name));
			data.first = chosen.length === 1 ? {...chosen[0]} : blank();
		}
		async function reload() {
			if (window.cur_frm !== frm || frm.doc.name !== name) { dialog.hide(); return false; }
			await frm.reload_doc();
			if (frm.doc.name !== name || frm.doc.docstatus || frm.doc.progress === "拒接" || !frm.perm?.[0]?.write) {
				dialog.hide(); return false;
			}
			read(); needsReload = false; drafts.clear();
			return true;
		}
		async function save() {
			if (saving || needsReload) return;
			const groups = visibleGroups(), group = groups.get(code);
			if (!group) return;
			const data = draft(group), selected = group.filter(row => data.selected.has(row.name));
			if (!selected.length) return;
			for (const input of root.find(".lots-editor input[required]")) if (!input.reportValidity()) return;
			const entries = (data.split ? [data.first, data.second] : [data.first]).map(lot => ({
				lot_number: (lot.lot_number || "").trim(), manufactured_on: lot.manufactured_on, expires_on: lot.expires_on}));
			if (entries.some(lot => !lot.lot_number || lot.expires_on < lot.manufactured_on)) return frappe.msgprint("请核对批号、生产日期和有效期。");
			if (data.split) {
				if (!(Number(data.quantity) > 0 && Number(data.quantity) < selected[0].quantity)) return frappe.msgprint("第一批数量须大于零且小于原行数量。");
				if (entries[0].lot_number === entries[1].lot_number) return frappe.msgprint("两批的供应商批号应不同。");
				entries[0].quantity = data.quantity;
			}
			const order = [...groups.keys()], idx = order.indexOf(code);
			const next = order.slice(idx + 1).concat(order.slice(0, idx + 1));
			const previous = code;
			saving = true; root.find('button,input,select').prop("disabled",true);
			let applied = false;
			try {
				await frappe.call({method, args:{name, modified: version, item_code:code, row_names:selected.map(r => r.name), lots:entries},
					freeze:true, freeze_message:"正在保存批次资料"});
				applied = true;
				if (!await reload()) return;
				frappe.show_alert({message: "已保存「" + escape(title(previous)) + "」的批次资料", indicator: "green"});
				if (!rows.some(incomplete)) { dialog.hide(); return; }
				if (search && ![...visibleGroups().values()].some(group => group.some(incomplete))) {
					search = ""; root.find('[data-filter="search"]').val("");
				}
				const remaining = visibleGroups();
				code = next.find(id => remaining.get(id)?.some(incomplete))
					|| [...remaining.keys()].find(id => remaining.get(id).some(incomplete)) || "";
			} catch (error) {
				needsReload = applied || error?.exc_type === "TimestampMismatchError" || error?.responseJSON?.exc_type === "TimestampMismatchError" || !error?.status;
				if (needsReload) frappe.show_alert("请重新读取本单，核对最新的补录进度。");
			} finally {
				saving = false;
				root.find('input,select,button').prop("disabled",false);
				render();
			}
		}
		root.on("input", "[data-lot]", function () {
			const data = drafts.get(key()); data[this.dataset.lot][this.dataset.field] = this.value; data.typed = true;
		}).on("input", "[data-quantity]", function () {
			drafts.get(key()).quantity = this.value; updateRemainder();
		}).on("input", '[data-filter="search"]', function () {
			search = this.value.trim().toLowerCase(); render();
		}).on("change", '[data-filter="date"]', function () {
			date = this.value; render();
		}).on("click", "[data-code]", function () {
			code = this.dataset.code; detailOnMobile = true; render();
		}).on("change", "[data-row]", function () {
			const data = drafts.get(key());
			if (this.checked) data.selected.add(this.dataset.row);
			else data.selected.delete(this.dataset.row);
			data.split = false; seedSelected(data, visibleGroups().get(code)); render();
		}).on("keydown", "[data-lot],[data-quantity]", function (event) {
			if (event.key === "Enter" && !event.isComposing) { event.preventDefault(); event.stopPropagation(); save(); }
		}).on("click", "[data-action]", async function () {
			if (saving) return;
			const action = this.dataset.action;
			if (action === "save") return save();
			if (action === "reload") { if (await reload()) render(); return; }
			if (action === "pending" || action === "all") mode = action;
			if (action === "back") detailOnMobile = false;
			if (action === "split") { const data = drafts.get(key()); data.split = !data.split; }
			if (action === "select") {
				const group = visibleGroups().get(code), data = draft(group);
				const eligible = group.filter(r => incomplete(r) && !r.lot_number);
				const deselect = eligible.every(r => data.selected.has(r.name));
				for (const row of eligible) deselect ? data.selected.delete(row.name) : data.selected.add(row.name);
				seedSelected(data, group);
			}
			render();
		});
		read();
		if (!rows.some(incomplete)) mode = "all";
		render(); dialog.show();
	}
	frappe.tjyDeliveryLots = {open};
})();
