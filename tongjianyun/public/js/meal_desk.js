/* Native Desk presentation for meal operations. Rows and links keep their original IDs. */
(() => {
	const types = {
		"Meal Planning Week": "自定义周食谱", "Meal Kitchen Day": "逐餐供餐与日结",
		"Material Request": "采购申请", "Item": "标准菜品库",
		"Tongjianyun Meal Publication": "食谱公示", "Tongjianyun Canteen Delivery": "供应商配送批次",
		"Tongjianyun Canteen Receiving": "食材扫码验收", "Tongjianyun Meal Weekly Task": "每周膳食任务",
		"Tongjianyun Food Sample": "食品留样", "Tongjianyun Meal Companion": "陪餐登记与评价",
		"Tongjianyun Meal Delivery Handover": "到园成品交接", "Tongjianyun Meal Class Feedback": "班级进餐反馈",
		"Tongjianyun Meal Diet Handover": "特殊餐交接", "Tongjianyun Meal Safety Check": "食品安全检查",
		"Tongjianyun Canteen Finding": "监管整改", "Tongjianyun Meal Family Opinion": "家长膳食意见",
		"Tongjianyun Canteen Stock Lot Movement": "食材批次流转", "Tongjianyun Meal Term Project": "学期膳食项目",
		"Tongjianyun Canteen": "食堂资质与场所档案", "Tongjianyun Canteen Credential": "食堂证照与健康证",
		"Tongjianyun Canteen Staffing Rule": "食堂岗位配置", "Tongjianyun Canteen Training": "从业人员培训记录",
		"Tongjianyun Canteen Policy": "地方采购与财务流程", "Tongjianyun Meal Diet Arrangement": "特殊膳食安排",
		"Tongjianyun Canteen Reconciliation": "供应商对账单", "Tongjianyun Canteen Finance Request": "食堂会计凭证申请",
	};
	const sharedColumns = {
		"标准食材库": ["item_name", "item_group", "stock_uom", "custom_meal_procurement_policy"],
		"标准菜品库": ["item_name", "custom_tjy_dish_category", "stock_uom"],
		"采购申请": ["title", "status_field", "company", "transaction_date", "schedule_date"],
		"自定义周食谱": ["title", "status", "custom_tjy_canteen", "week_start", "company"],
		"逐餐供餐与日结": ["meal_date", "status", "kitchen_warehouse", "prepared_by", "meal_week"],
	};
	// A second line identifies the business context when Frappe folds columns on smaller screens.
	const rowContext = {
		"Tongjianyun Meal Weekly Task":["week_start","company"], "Tongjianyun Canteen Finding":["category","company"],
		"Tongjianyun Canteen Stock Lot Movement":["lot_number"], "Tongjianyun Meal Publication":["week_start"],
		"Tongjianyun Canteen Receiving":["company"], "Tongjianyun Canteen Delivery":["purchase_order","company"],
		"Tongjianyun Meal Safety Check":["company"], "Tongjianyun Meal Class Feedback":["company"],
		"Tongjianyun Meal Diet Arrangement":["company"], "Tongjianyun Meal Diet Handover":["alternate"],
		"Tongjianyun Meal Family Opinion":["menu_detail","company"], "Tongjianyun Canteen Credential":["issuer"],
		"Tongjianyun Meal Term Project":["company"], "Tongjianyun Food Sample":["storage_location"],
		"Tongjianyun Meal Companion":["company"], "Tongjianyun Canteen Finance Request":["company"],
		"Tongjianyun Canteen Reconciliation":["from_date"], "Tongjianyun Canteen Training":["trainer"],
		"Tongjianyun Canteen":["district","region"], "Tongjianyun Canteen Policy":["company"],
		"Tongjianyun Canteen Staffing Rule":["department"], "Tongjianyun Meal Delivery Handover":["company"],
	};
	const captions = {
		item_name: "名称", item_group: "食材分类", stock_uom: "单位", custom_tjy_dish_category: "菜品分类",
		transaction_date: "申请日期", schedule_date: "需用日期", company: "园所", title: "名称", name: "单号",
	};
	const translated = {
		Administrator:"管理员", Guest:"访客", Kg:"千克", kg:"千克", g:"克", Gram:"克", Nos:"个",
		Litre:"升", Liter:"升", ml:"毫升", Box:"盒", Purchase:"采购", "Material Transfer":"调拨",
		"Material Issue":"出库", Manufacture:"生产", Draft:"草稿", Submitted:"已提交", Cancelled:"已取消",
		Pending:"待处理", Ordered:"已下单", "Partially Ordered":"部分下单", Received:"已收货",
		"Partially Received":"部分收货", Completed:"已完成", Stopped:"已停止", Open:"进行中", Closed:"已关闭",
		"To Receive and Bill":"待收货及开票", "To Bill":"待开票", "To Receive":"待收货",
		"Purchase Receipt":"采购收货单", "Purchase Order":"采购订单", "Purchase Invoice":"采购发票",
		"Journal Entry":"记账凭证", "Stock Entry":"库存单据", "Stock Reconciliation":"库存盘点",
		"Supplier Quotation":"供应商报价", "Material Request":"采购申请", CNY:"人民币",
	};
	const targets = new Set(["Tongjianyun Canteen","Tongjianyun Meal Term Project","Meal Planning Week","Item","BOM",
		"Employee","Student","Student Batch Name","Supplier","Warehouse","Account","Project","User","Task"]);
	const mealTimes = new Map([["早餐","morning"],["早点","snack"],["午餐","midday"],["午点","snack"],["晚餐","evening"]]);
	const reportStates = new Map([
		...["正常","有效","已日结","已确认","已完成","已过账"].map(s=>[s,"good"]),
		...["临期","需处理","待确认","待日结","日结依据待核对","待核对"].map(s=>[s,"check"]),
		...["已过期","不合格","已取消","拒收"].map(s=>[s,"risk"]),
	]);
	const reports = new Map();
	const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
	const chinese = (v) => typeof v === "string" ? (translated[v] || v) : v;
	function titleFor(type) {
		if (type === "Item") {
			const layout = frappe.router.doctype_layout || new URLSearchParams(location.search).get("layout");
			return ({"标准食材档案":"标准食材库","标准菜品档案":"标准菜品库"})[layout];
		}
		if (type === "Material Request" && (frappe.router.current_shell || frappe.app?.sidebar?.current_module) !== "膳食与食堂") return;
		return types[type];
	}
	function syncScope() {
		const [view, type] = frappe.get_route();
		const active = (["List","Form"].includes(view) && titleFor(type)) || (view === "query-report" && reports.get(type));
		frappe.tjyMealOverview.scope(active);
		frappe.tjyMealFilters.scope(active);
		document.body.classList.toggle("tjy-meal-desk", Boolean(active));
	}
	function subject(type, doc, value) {
		if (type === "Tongjianyun Food Sample" && doc.external_dish) return doc.external_dish;
		if (type === "Material Request") {
			const match = /^Meal procurement (\d{4}-\d{2}-\d{2}) - (\d{4}-\d{2}-\d{2})$/.exec(doc.title || "");
			if (match) return match[1] + " 至 " + match[2] + " 食材采购";
		}
		return chinese(value);
	}

	// Resolve only records already present on the visible page, using the current user's read permissions.
	async function namesFor(pairs) {
		const grouped = new Map();
		for (const [type, id] of pairs) {
			if (!id || !targets.has(type)) continue;
			if (!grouped.has(type)) grouped.set(type, new Set());
			grouped.get(type).add(id);
		}
		const labels = {};
		const entries = [...grouped].flatMap(([type, ids]) => [...ids].map(id => [type,id]));
		for (let start = 0; start < entries.length; start += 500) {
			const references = {};
			for (const [type,id] of entries.slice(start,start+500)) (references[type] ||= []).push(id);
			const {message} = await frappe.call({method:"tongjianyun.canteen_ops.desk_labels.link_labels", args:{references}, type:"POST"});
			for (const [type, values] of Object.entries(message || {})) Object.assign(labels[type] ||= Object.create(null), values);
		}
		return labels;
	}

	async function formatList(list) {
		const label = titleFor(list.doctype);
		if (!label || frappe.get_route()[0] !== "List" || frappe.get_route()[1] !== list.doctype) return;
		syncScope();
		list.page.set_title(label);
		frappe.tjyMealOverview.list(list,label);
		frappe.tjyMealFilters.render(list,label);
		const action = list.page.btn_primary?.find(".es-button__label").first();
		if (list.doctype !== "Tongjianyun Canteen Delivery" && /^(添加|新建|Add |New )/.test(action?.text() || "")) action.text("新建"+label);

		const rows = new Map(list.data.map(doc => [doc.name, doc]));
		const cells = [];
		for (const row of list.$result[0].querySelectorAll(".list-row")) {
			const anchor = row.querySelector(".list-subject a[data-name]");
			const doc = rows.get(anchor?.dataset.name);
			if (!doc) continue;
			const shown = new Set(list.columns.map(col => col.df?.fieldname));
			const detail = (rowContext[list.doctype] || []).filter(k => !shown.has(k)).map(k => doc[k]).filter(Boolean).join(" · ");
			const parent = anchor.parentElement;
			parent.querySelector(".tjy-meal-row-context")?.remove();
			parent.classList.toggle("tjy-meal-row-title", Boolean(detail));
			if (detail) {
				const line = document.createElement("small");
				line.className = "tjy-meal-row-context";
				line.textContent = detail;
				line.title = detail;
				parent.append(line);
			}
			for (const col of list.columns) {
				const df = col.df;
				if (!df || !["Field","Subject"].includes(col.type)) continue;
				const primary = col.type === "Subject";
				const node = primary ? anchor : row.querySelector('[data-fieldname="'+CSS.escape(df.fieldname)+'"] .filterable');
				if (!node) continue;
				const raw = doc[df.fieldname];
				if (df.fieldname === "meal_type" && mealTimes.has(raw)) node.dataset.mealTime = mealTimes.get(raw);
				const initial = primary ? subject(list.doctype,doc,node.textContent) : chinese(node.textContent.trim());
				if (initial && initial !== node.textContent) node.textContent = initial;
				if (primary) node.title = [initial, doc.name].filter(Boolean).join(" · ");
				const target = df.fieldtype === "Link" ? df.options : null;
				if (target && raw) cells.push({node, target, raw, doc, primary});
			}
		}
		const labels = await namesFor(cells.map(c => [c.target,c.raw]));
		for (const {node,target,raw,doc,primary} of cells) {
			const value = labels[target]?.[raw];
			if (value && node.isConnected) {
				node.textContent = chinese(value);
				node.title = primary ? value+" · "+doc.name : value+" · "+raw;
			}
		}
	}
	function installLists() {
		for (const type of Object.keys(types)) {
			const settings = (frappe.listview_settings[type] ||= {});
			if (settings._tjyMealList) continue;
			settings._tjyMealList = true;
			if (type !== "Item" && type !== "Material Request") settings.hide_name_column = true;
			const extra = [...(rowContext[type] || [])];
			if (type !== "Item" && type !== "Material Request") extra.push(...(frappe.tjyMealOverview?.listDimensions[types[type]] || []));
			if (type === "Tongjianyun Food Sample") extra.push("external_dish");
			if (extra.length) settings.add_fields = [...new Set([...(settings.add_fields || []), ...extra])];
			const onload = settings.onload, refresh = settings.refresh;
			settings.onload = function(list) {
				onload?.call(this,list);
				if (type === "Tongjianyun Canteen Delivery") {
					const canArrange = () => list.can_create && !frappe.boot.read_only && frappe.model.can_read("Purchase Order")
						&& (!frappe.user_roles.includes("膳食供应商") || frappe.user_roles.includes("System Manager"));
					settings.primary_action = () => {
						if (canArrange()) return frappe.set_route(purchaseOrderLink());
						frappe.msgprint("请在园方已建立的配送批次中接单。");
					};
					list.set_primary_action = function () {
						if (canArrange()) this.page.set_primary_action("从采购订单建批", settings.primary_action, "plus");
						else this.page.clear_primary_action();
					};
					list.set_primary_action();
				}
				// Shared ERP doctypes retain their own columns outside the meal layouts.
				if (["Item","Material Request","Meal Planning Week","Meal Kitchen Day"].includes(type)) {
					const original = list.setup_columns.bind(list);
					list.setup_columns = async function(fields) {
						const label = titleFor(type);
						const preset = sharedColumns[label];
						const saved = this.list_filter?.active_layout_name;
						if (!preset || fields?.length || (saved && saved !== "default_layout")) return original(fields);
						await original(preset.filter(k => k === "status_field" || frappe.meta.get_docfield(type,k)).map(fieldname => ({fieldname})));
						for (const col of this.columns) {
							if (col.df && captions[col.df.fieldname]) col.df = {...col.df,label:captions[col.df.fieldname]};
						}
					};
					const beforeRefresh = list.before_refresh.bind(list);
					list.before_refresh = async function() {
						await beforeRefresh();
						await this.setup_columns();
					};
				}
			};
			settings.refresh = function(list) {
				refresh?.call(this,list);
				formatList(list).catch(console.error);
			};
		}
	}

	function registerReport(name, title) {
		reports.set(name,title);
		const settings = frappe.query_reports[name];
		const original = settings.formatter, onload = settings.onload, afterRefresh = settings.after_refresh;
		settings.after_refresh = function(report) {
			afterRefresh?.call(this,report);
			if (frappe.get_route()[1]===name) frappe.tjyMealOverview.report(report,title);
		};
		settings.onload = async function(report) {
			syncScope();
			frappe.tjyMealOverview.clear(report.page.main?.[0]);
			await onload?.call(this,report);
			report.page.set_title(title);
			if (name === "Tongjianyun Meal Quality Indicators" && !report.get_filter_value("canteen")) {
				const company = frappe.defaults.get_user_default("Company");
				const filters = {disabled:0};
				if (company) filters.company = company;
				const sites = await frappe.db.get_list("Tongjianyun Canteen", {filters,fields:["name"],order_by:"canteen_name asc",limit:1});
				if (sites.length && !report.get_filter_value("canteen")) await report.set_filter_value("canteen",sites[0].name);
			}
		};
		settings.formatter = function(value,row,col,data,standard,...rest) {
			const format = (val,r,field,record) => {
				if (name==="Tongjianyun Meal Quality Indicators" && field.fieldname==="rate" && record?.rate!=null && Number.isFinite(Number(record.rate))) {
					const percent=Math.max(0,Math.min(100,Number(record.rate)));
					return '<span class="tjy-report-rate"><span>'+standard(val,r,field,record)+'</span><meter aria-hidden="true" min="0" max="100" value="'+percent+'"></meter></span>';
				}
				if (["stage","day_status","actual_status"].includes(field.fieldname) && ["Data","Select"].includes(field.fieldtype) && reportStates.has(val)) {
					return '<span class="tjy-report-state" data-tone="'+reportStates.get(val)+'">'+standard(val,r,field,record)+'</span>';
				}
				const label = record?._meal_labels?.[field.fieldname];
				if (label && ["Link","Dynamic Link"].includes(field.fieldtype)) {
					const type = field.fieldtype === "Dynamic Link" ? record[field.options] : field.options;
					const href = frappe.utils.get_form_link(type,val);
					return '<a href="'+escape(href)+'" title="'+escape(val)+'">'+escape(chinese(label))+'</a>';
				}
				if (typeof val === "string" && chinese(val) !== val && !["Link","Dynamic Link"].includes(field.fieldtype)) return escape(chinese(val));
				return standard(val,r,field,record);
			};
			return original ? original.call(this,value,row,col,data,format,...rest) : format(value,row,col,data);
		};
	}

	async function formatForm(frm) {
		if (!titleFor(frm.doctype)) return;
		syncScope();
		const doc = frm.doc;
		const links = Object.values(frm.fields_dict).filter(c => c.df.fieldtype === "Link" && !c.df.hidden && c.get_value?.() && targets.has(c.df.options));
		const cells = [];
		for (const control of Object.values(frm.fields_dict)) {
			for (const row of control.grid?.grid_rows || []) {
				for (const [key,column] of Object.entries(row.columns || {})) {
					const field = frappe.meta.get_docfield(row.doc?.doctype,key);
					const id = row.doc?.[key];
					const cell = column.static_area?.[0];
					if (cell && field?.fieldtype === "Link" && id && targets.has(field.options)) cells.push({cell,type:field.options,id});
				}
			}
		}
		const labels = await namesFor([...links.map(c => [c.df.options,doc[c.df.fieldname]]), ...cells.map(c => [c.type,c.id])]);
		if (frm.doc !== doc || frappe.get_route()[0] !== "Form" || window.cur_frm !== frm) return;
		frappe.tjyMealOverview.form(frm,titleFor(frm.doctype),labels);
		for (const control of Object.values(frm.fields_dict)) {
			if (control.disp_status!=="Read" || !["Attach","Attach Image"].includes(control.df.fieldtype)) continue;
			const link=control.disp_area?.querySelector("a[href]");
			if (!link || link.getAttribute("href")!==doc[control.df.fieldname]) continue;
			link.textContent="查看"+control.df.label;
			link.title=doc[control.df.fieldname];
			link.classList.add("tjy-attachment-link");
		}
		const display = (type,id) => labels[type]?.[id] || (type==="User" && id===frappe.session.user && frappe.boot.user.full_name) || translated[id];
		for (const {cell,type,id} of cells) {
			const value = display(type,id) || (frm.doctype === "Tongjianyun Canteen Delivery" && type === "Item" && doc.__onload?.delivery_item_names?.[id]);
			if (value && cell.isConnected) {
				const target = cell.querySelector("a") || cell;
				target.textContent = value;
				target.title = id;
			}
		}
		for (const c of links) {
			const id = doc[c.df.fieldname], label = display(c.df.options,id);
			if (!label || c.$input?.is(":focus")) continue;
			if (c.$input && c.translate_and_set_input_value) c.translate_and_set_input_value(label,id);
			const link = c.disp_area?.querySelector("a");
			if (link) { link.textContent = label; link.title = id; }
		}
		if (!frm.is_new()) {
			const key = frm.meta.title_field, id = doc[key], target = frm.fields_dict[key]?.df.options;
			const value = subject(frm.doctype,doc,labels[target]?.[id] || chinese(id));
			if (value && typeof value === "string" && (value !== id || doc.external_dish)) frm.page.set_title(value);
		}
	}
	const purchaseOrderLayout = "膳食采购订单";
	function purchaseOrderLink(name) {
		return "/desk/膳食与食堂/purchase-order/" + (name ? encodeURIComponent(name) : "view/list") + "?layout=" + encodeURIComponent(purchaseOrderLayout);
	}
	frappe.tjyMealDesk = {installLists, registerReport, purchaseOrderLayout, purchaseOrderLink};
	frappe.router.on("change",syncScope);
	const formTimers = new WeakMap();
	const requiredTimers = new WeakMap();
	function queueForm(frm) {
		clearTimeout(formTimers.get(frm));
		formTimers.set(frm, setTimeout(() => { formatForm(frm).catch(console.error); }, 80));
	}
	$(document).on("form-refresh.tjyMealDesk",(_event,frm) => {
		if (!titleFor(frm.doctype)) return;
		$(frm.wrapper).off("grid-row-render.tjyMealDesk shown.bs.tab.tjyMealDesk").on("grid-row-render.tjyMealDesk shown.bs.tab.tjyMealDesk",() => queueForm(frm));
		$(frm.wrapper).off(".tjyRequired");
		if (frm.is_new()) $(frm.wrapper).on("input.tjyRequired change.tjyRequired", ".frappe-control", () => {
			clearTimeout(requiredTimers.get(frm));
			requiredTimers.set(frm,setTimeout(()=>{
				if (window.cur_frm===frm && frappe.get_route()[0]==="Form" && frm.is_new()) frappe.tjyMealOverview.form(frm,titleFor(frm.doctype),{});
			},120));
		});
		queueForm(frm);
	});
})();
