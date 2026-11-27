(() => {
	const f = frappe;
	if (f.tgyCanteenFormsLoaded) return;
	f.tgyCanteenFormsLoaded = true;
	const prefix = "tongjianyun.canteen_ops.";
	const site = "Tongjianyun Canteen";
	const term = "Tongjianyun Meal Term Project";
	const dispatch = "Tongjianyun Canteen Purchase Dispatch";
	const delivery = "Tongjianyun Canteen Delivery";
	const receiving = "Tongjianyun Canteen Receiving";
	const sample = "Tongjianyun Food Sample";
	const companion = "Tongjianyun Meal Companion";
	const statement = "Tongjianyun Canteen Reconciliation";
	const finding = "Tongjianyun Canteen Finding";
	const voucher = "Tongjianyun Canteen Finance Request";
	const review = "Tongjianyun Canteen Price Review";
	const rule = "Tongjianyun Canteen Policy";

	const api = async (method, args = {}, type = "POST") =>
		(await f.call({ method: prefix + method, args, type, freeze: type !== "GET" })).message;
	const open = (doctype, name) => f.set_route("Form", doctype, name);
	const change = async (frm, method, args) => {
		if (frm.is_dirty()) await frm.save();
		await api(method, { name: frm.doc.name, ...args });
		await frm.reload_doc();
	};
	const dialog = (title, fields, primary_action) => {
		const modal = new f.ui.Dialog({
			title, fields, primary_action_label: "确认",
			async primary_action(values) {
				await primary_action(values);
				modal.hide();
			}
		});
		modal.show();
	};
	const option = (field, label, fieldtype, options, defaultValue) => ({
		fieldname: field, label, fieldtype, reqd: 1, options, default: defaultValue
	});
	const saved = (frm) => !frm.is_new();
	const role = (...roles) => roles.some((name) => f.user_roles.includes(name));
	const allowed = (doctype, perm = "create") => (f.boot.user.can_create || []).includes(doctype) ||
		(perm === "write" && (f.boot.user.can_write || []).includes(doctype)) || f.session.user === "Administrator";
	const newDoc = (doctype, defaults) => f.new_doc(doctype, defaults);
	const photoExisting = (frm) => {
		if (frm.is_new()) frm.set_intro("先保存单据，再把私有附件上传到本单。", "blue");
	};

	function setSiteQuery(frm) {
		if ([sample,companion,finding].includes(frm.doctype) && !role("System Manager") && role("膳食园方负责人","膳食保健员","膳食安全员")) {
			frm.set_query("company",()=>({query:prefix+"meal_operations.scope_links",filters:{}}));
		}
		frm.set_query("canteen", () => ({ filters: { company: frm.doc.company, disabled: 0 } }));
	}
	function showLabels(doctype, names, foodLots = false) {
		const pop = window.open("", "_blank", "width=620,height=720");
		if (!pop) {
			f.msgprint("请允许打开打印窗口。");
			return;
		}
		const doc = pop.document;
		doc.title = "膳食标签打印";
		const style = doc.createElement("style");
		style.textContent = "body{font:14px system-ui;margin:16px;color:#111}.label{box-sizing:border-box;width:68mm;min-height:43mm;border:1px solid #bbb;padding:10px;margin:0 0 8px;break-inside:avoid;display:grid;grid-template-columns:1fr 24mm;gap:3px}.label h2{margin:0;font-size:16px}.label p{margin:3px 0}.label img{width:24mm;align-self:center}.text{min-width:0;overflow-wrap:anywhere}";
		doc.head.append(style);
		const state = doc.createElement("p");
		state.textContent = "正在生成标签…";
		doc.body.append(state);
		api("ui.get_labels", { doctype, names: JSON.stringify(names), food_lots: foodLots ? 1 : 0 }, "GET").then(async (rows) => {
			if (pop.closed) return;
			state.remove();
			const images = [];
			for (const entry of rows) {
				const label = doc.createElement("section");
				label.className = "label";
				const text = doc.createElement("div");
				text.className = "text";
				const heading = doc.createElement("h2");
				heading.textContent = entry.title;
				text.append(heading);
				for (const line of [entry.name, ...entry.text]) {
					const row = doc.createElement("p");
					row.textContent = line || "";
					text.append(row);
				}
				const image = doc.createElement("img");
				image.alt = "追溯二维码";
				image.src = entry.qr;
				label.append(text, image);
				doc.body.append(label);
				images.push(image.decode().catch(() => null));
			}
			await Promise.all(images);
			pop.focus();
			pop.print();
		}).catch(() => {
			state.textContent = "标签生成失败，请返回列表核对所选记录。";
		});
	}
	f.tgyCanteenPrintLabels = showLabels;

	async function fromWeek(frm, adjustment) {
		const result = await api("purchasing.prepare_dispatch", {
			week_name: adjustment ? frm.doc.meal_week : frm.doc.name,
			meal_adjustment: adjustment ? frm.doc.name : undefined
		});
		if (result.dispatch) return open(dispatch, result.dispatch);
		if (result.request) {
			f.show_alert("请先核对并提交采购申请，再办理下发。");
			return open("Material Request", result.request);
		}
		f.msgprint("本次没有需要下发的采购申请。");
	}

	f.ui.form.on("Meal Planning Week", {
		refresh(frm) {
			if (frm.doc.docstatus === 1 && allowed("Tongjianyun Meal Publication")) {
				frm.add_custom_button("食谱公示", async () => {
					const type = "Tongjianyun Meal Publication";
					const rows = await f.db.get_list(type, {filters:{meal_week:frm.doc.name,docstatus:["<",2]},limit:1});
					if (rows.length) return open(type,rows[0].name);
					return f.new_doc(type,{meal_week:frm.doc.name,company:frm.doc.company,
						week_start:frm.doc.week_start,canteen:frm.doc.custom_tjy_canteen});
				});
			}
			if (frm.doc.docstatus === 1 && allowed(dispatch)) {
				frm.add_custom_button("生成 / 下发采购申请", () => fromWeek(frm, false), "采购操作");
			}
		}
	});
	f.ui.form.on("Meal Plan Adjustment", {
		refresh(frm) {
			if (frm.doc.docstatus === 1 && frm.doc.material_request && allowed(dispatch)) {
				frm.add_custom_button("下发单餐变更采购申请", () => fromWeek(frm, true), "采购操作");
			}
		}
	});
	f.ui.form.on("Material Request", {
		refresh(frm) {
			if (frm.doc.docstatus !== 1 || frm.doc.material_request_type !== "Purchase" || !allowed(dispatch)) return;
			api("ui.dispatch_source", {request: frm.doc.name}, "GET").then(source => {
				if (!source || f.get_route().at(-1)!==frm.doc.name) return;
				frm.add_custom_button("下发食堂采购", async () => {
					const result = await api("purchasing.prepare_dispatch", source);
					if (result.dispatch) open(dispatch,result.dispatch);
				});
			});
		}
	});
	f.ui.form.on(dispatch, {
		setup: setSiteQuery,
		refresh(frm) {
			if (frm.doc.docstatus !== 1) return;
			frm.add_custom_button("查看采购申请", () => open("Material Request", frm.doc.material_request));
			if (!allowed("Request for Quotation")) return;
			frm.add_custom_button("生成食材询价单", async () => {
				const result = await f.call({
					method: "erpnext.stock.doctype.material_request.mapper.make_request_for_quotation",
					args: { source_name: frm.doc.material_request }
				});
				f.model.sync(result.message);
				open("Request for Quotation", result.message.name);
			});
		}
	});
	f.ui.form.on("Request for Quotation", {
		refresh(frm) {
			if (!saved(frm) || !frm.doc.docstatus) return;
			frm.add_custom_button("查看食材报价对比", () => {
				f.route_options = { quotation_request: frm.doc.name, company: frm.doc.company };
				f.set_route("query-report", "Tongjianyun Canteen Quotation Comparison");
			});
		}
	});
	f.ui.form.on(term, { setup: setSiteQuery });
	f.ui.form.on("Meal Kitchen Day", {
		refresh(frm) {
			if (!saved(frm) || frm.doc.docstatus === 2) return;
			const defaults = { company: frm.doc.company, meal_day: frm.doc.name, meal_date: frm.doc.meal_date };
			for (const [type,label] of [["Tongjianyun Meal Class Feedback","班级进餐反馈"],["Tongjianyun Meal Diet Handover","特殊餐交接"]]) {
				if (allowed(type)) frm.add_custom_button(label,()=>newDoc(type,{company:frm.doc.company,meal_week:frm.doc.meal_week,service_date:frm.doc.meal_date}),"逐餐登记");
			}
			for (const [doctype, label] of [[sample, "登记留样"], [companion, "登记陪餐"]]) {
				if (allowed(doctype)) frm.add_custom_button(label, () => newDoc(doctype, defaults), "逐餐登记");
			}
		}
	});
	f.ui.form.on(delivery, {
		setup: setSiteQuery,
		async delivery_acceptance_result(frm) {
			const result = await api("purchasing.delivery_acceptance", { name: frm.doc.name }, "GET");
			if (!result.items.length) return f.msgprint(result.stage);
			const summary = new f.ui.Dialog({ title: result.stage,
				fields: [{ fieldname: "result", fieldtype: "HTML" }],
				primary_action_label: result.receiving ? "打开验收单" : "关闭",
				primary_action() {
					summary.hide();
					if (result.receiving) open(receiving, result.receiving);
				}
			});
			const list = $("<ul>");
			for (const row of result.items) {
				list.append($("<li>").text((frm.doc.__onload?.delivery_item_names?.[row.item_code] || row.item_code) + " · 随货 " + row.quantity + " · 合格 " +
					row.accepted + " · 拒收 " + row.rejected + " " + row.uom));
			}
			summary.fields_dict.result.$wrapper.append(list);
			summary.show();
		},
		refresh(frm) {
			if (frm.is_new() || frm.doc.docstatus === 2) return;
			if (frm.doc.progress !== "拒接" && frm.doc.items?.some(row =>
				(row.lot_number || row.receipt_trace_no) && row.manufactured_on && row.expires_on)) {
				frm.add_custom_button("打印食材批次标签", () => showLabels(delivery, [frm.doc.name], true));
			}
			if (frm.doc.docstatus === 1) {
				frm.add_custom_button("打印随货二维码", () => showLabels(delivery, [frm.doc.name]));
				if (frm.doc.progress !== "到货") {
					frm.add_custom_button("查看验收结果", () => frm.trigger("delivery_acceptance_result"));
				}
				if (frm.perm?.[0]?.write) {
					frm.add_custom_button("补充票证或检验报告", () => dialog("登记补充票证", [
						option("evidence_type", "票证类型", "Select", [
							"送货单", "产品合格证明", "同批次检验报告", "检疫证明", "肉品品质检验合格证", "食品经营资质", "其他票证"
						]),
						{fieldname:"scope", label:"送货单覆盖范围", fieldtype:"Select",
							options:["本次配送全部明细","指定食材"], default:"本次配送全部明细",
							depends_on:"eval:doc.evidence_type === '送货单'"},
						option("reference_no", "票证号", "Data"),
						{ fieldname: "item_code", label: "对应食材", fieldtype: "Select",
							depends_on:"eval:doc.evidence_type !== '送货单' || doc.scope === '指定食材'",
							mandatory_depends_on:"eval:doc.evidence_type === '送货单' && doc.scope === '指定食材'",
							options: ["", ...new Set(frm.doc.items.map((row) => row.item_code))] },
						{ fieldname: "lot_number", label: "适用批号", fieldtype: "Data",
							depends_on:"eval:doc.evidence_type !== '送货单' || doc.scope === '指定食材'" },
						{ fieldname: "valid_until", label: "票证有效期", fieldtype: "Date" }
					], (values) => {
						const {scope, ...ticket} = values;
						if (ticket.evidence_type === "送货单" && scope !== "指定食材") {
							ticket.item_code = ticket.lot_number = "";
						}
						new f.ui.FileUploader({
							doctype: delivery, docname: frm.doc.name, allow_multiple: false, make_private: 1,
							async on_success(file) {
								await api("purchasing.add_delivery_evidence", { name: frm.doc.name, ...ticket, attachment: file.file_url });
								await frm.reload_doc();
							}
						});
					}), "履约状态");
				}
			}
		}
	});
	const sync = (frm) => {
		clearTimeout(frm.__tgy_receive_sync);
		if (!frm.__tgy_enable_live_sync || frm.doc.docstatus || frm.is_new() || !navigator.onLine) return;
		frm.__tgy_receive_sync = setTimeout(async () => {
			if (!frm.is_dirty() || f.get_route().at(-1) !== frm.doc.name || !navigator.onLine) return;
			try {
				await frm.save();
				f.show_alert("现场记录已同步");
			} catch {
				f.show_alert({ message: "同步待处理，请核对未保存的验收记录", indicator: "orange" });
			}
		}, 1600);
	};
	f.ui.form.on(receiving, {
		setup: setSiteQuery,
		refresh(frm) {
			if (frm.is_new() || frm.doc.docstatus) return;
			frm.add_custom_button("获取验收定位", () => {
				if (!navigator.geolocation) return f.msgprint("当前设备无法获取定位。");
				navigator.geolocation.getCurrentPosition(async ({ coords }) => {
					await frm.set_value({
						position: coords.latitude.toFixed(6) + "," + coords.longitude.toFixed(6),
						accuracy: coords.accuracy, location_at: f.datetime.now_datetime()
					});
					sync(frm);
				}, () => f.msgprint("定位未成功，请确认浏览器位置权限。"), { enableHighAccuracy: true, timeout: 12000 });
			}, "验收取证");
			frm.add_custom_button(frm.__tgy_enable_live_sync ? "关闭联网自动同步" : "开启联网自动同步", () => {
				frm.__tgy_enable_live_sync = !frm.__tgy_enable_live_sync;
				sync(frm);
				frm.refresh();
			}, "验收取证");
			frm.add_custom_button("同步验收记录", () => frm.save(), "验收取证");
		},
		photo: sync, arrived_at: sync, remarks: sync
	});
	f.ui.form.on("Tongjianyun Canteen Receiving Item", {
		gross_weight: sync, tare_weight: sync, accepted_qty: sync, rejected_qty: sync, reason: sync, evidence_verified: sync
	});
	f.ui.form.on(sample, {
		setup: setSiteQuery,
		refresh(frm) {
			photoExisting(frm);
			if (frm.doc.docstatus !== 1) return;
			frm.add_custom_button("生成并打印留样标签", () => showLabels(sample, [frm.doc.name]));
			if (!frm.doc.disposed_at && allowed(sample, "write")) {
				frm.add_custom_button("留样到期处置", () => dialog("留样到期处置",
					[option("reason", "处置说明", "Small Text")], ({ reason }) =>
						change(frm, "safety.dispose_sample", { reason })));
			}
		}
	});
	f.ui.form.on(companion, { setup: setSiteQuery, refresh: photoExisting });
	f.ui.form.on(statement, {
		setup: setSiteQuery,
		async company(frm) {
			if (!frm.doc.company || !frm.is_new() || frm.doc.currency) return;
			const { message } = await f.db.get_value("Company", frm.doc.company, "default_currency");
			if (message?.default_currency) await frm.set_value("currency", message.default_currency);
		},
		refresh(frm) {
			if (frm.doc.docstatus === 2) return;
			if (role("膳食供应商") && !role("System Manager")) {
				frm.disable_save();
				frm.fields.forEach((field) => {
					if (field.df.fieldname && f.meta.has_field(statement, field.df.fieldname)) {
						frm.set_df_property(field.df.fieldname, "read_only", 1);
					}
				});
				if (saved(frm) && !frm.doc.docstatus && !frm.doc.supplier_confirmed_at) {
					frm.add_custom_button("确认供应商对账", async () => {
						await api("finance.confirm_statement", { name: frm.doc.name });
						await frm.reload_doc();
					});
				}
				return;
			}
			if (!frm.doc.docstatus && allowed(statement, "write")) {
				frm.add_custom_button("加载已验收对账明细", async () => {
					for (const field of ["canteen", "supplier", "from_date", "to_date", "currency"]) {
						if (!frm.doc[field]) return f.msgprint("请先选择食堂、供应商、日期和币种。");
					}
					if ((frm.doc.items || []).length) {
						await new Promise((resolve, reject) => f.confirm("重新加载会替换当前未提交明细。", resolve, reject));
					}
					const { canteen, supplier, from_date, to_date, currency } = frm.doc;
					const rows = await api("finance.preview_statement", { canteen, supplier, from_date, to_date, currency }, "GET");
					frm.clear_table("items");
					for (const row of rows) frm.add_child("items", row);
					frm.refresh_field("items");
				});
			}
			if (frm.doc.docstatus === 1 && allowed("Purchase Invoice")) {
				const receipts = [...new Set(frm.doc.items.filter((row) => !row.disputed).map((row) => row.purchase_receipt))];
				frm.add_custom_button("生成采购发票草稿", () => dialog("核对供应商发票", [
					option("receipt", "采购收货单", "Select", receipts),
					option("bill_no", "供应商发票号码", "Data"),
					option("bill_date", "发票日期", "Date", undefined, f.datetime.get_today())
				], async (values) => open("Purchase Invoice", await api("finance.make_invoice", { name: frm.doc.name, ...values }))));
			}
		}
	});
	f.ui.form.on(voucher, {
		setup: setSiteQuery,
		refresh(frm) {
			photoExisting(frm);
			if (frm.doc.docstatus !== 1 || !allowed("Journal Entry")) return;
			frm.add_custom_button("生成会计凭证草稿", async () =>
				open("Journal Entry", await api("finance.make_journal_entry", { name: frm.doc.name })));
		}
	});
	f.ui.form.on(finding, {
		setup: setSiteQuery,
		refresh(frm) {
			if (!saved(frm) || !allowed(finding, "write")) return;
			if (frm.doc.progress === "待整改" && (frm.doc.assigned_to === f.session.user || role("System Manager"))) {
				frm.add_custom_button("提交整改", () => change(frm, "safety.advance_finding", { action: "提交整改" }));
			}
			if (frm.doc.progress === "待复核" && role("System Manager", "膳食教育监管", "膳食食品安全监管", "膳食财政监管")) {
				for (const action of ["通过", "退回"]) {
					frm.add_custom_button(action, () => dialog("复核整改",
						[option("note", "复核意见", "Small Text")], ({ note }) =>
							change(frm, "safety.advance_finding", { action, note })), "整改复核");
				}
			}
		}
	});
	f.ui.form.on(rule, { setup: setSiteQuery });
	for (const doctype of [review, "Tongjianyun Canteen Credential", "Tongjianyun Canteen Training"]) {
		f.ui.form.on(doctype, { setup: setSiteQuery, refresh: photoExisting });
	}
	f.ui.form.on(site, {
		setup(frm) {
			for (const field of ["raw_warehouse", "kitchen_warehouse", "quarantine_warehouse"]) {
				frm.set_query(field, () => ({ filters: { company: frm.doc.company, is_group: 0, disabled: 0 } }));
			}
		}
	});
})();
