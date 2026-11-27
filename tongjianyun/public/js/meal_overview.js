/* Read-only page summaries. Counts on lists describe loaded rows; report metrics use the current result. */
(() => {
	const groups = [
		["食谱编排","menu","book-open",["自定义周食谱","食谱公示"]],
		["采购验收","purchase","truck",["采购申请","供应商配送批次","食材扫码验收","实时库存与效期","食堂盘点报表"]],
		["今日供餐","service","calendar-days",["每周膳食任务","逐餐供餐与日结","食品留样","陪餐登记与评价","到园成品交接","班级进餐反馈","特殊餐交接"]],
		["检查整改","safety","shield-check",["食品安全检查","监管数据质量","监管整改","家长膳食意见"]],
		["台账分析","analysis","chart-bar",["膳食台账","食材采购报表","食材采购与消耗分析","食材批次流转","膳食质量指标"]],
		["基础设置","directory","settings",["标准菜品库","标准食材库","学期膳食项目","食堂资质与场所档案","食堂证照与健康证","食堂证照到期提醒","食堂岗位配置","人员配置分析","从业人员培训记录","地方采购与财务流程","特殊膳食安排"]],
		["财务结算","finance","wallet",["供应商对账单","供应商对账与结算","食堂会计凭证申请","食堂账务记录","食堂经营报表","食堂收支报表"]],
	];
	const byTitle = new Map(groups.flatMap(group => group[3].map(title => [title,group])));
	const listDimensions = {
		"自定义周食谱":["custom_tjy_canteen","week_start"],"食谱公示":["canteen","week_start"],
		"采购申请":["company","schedule_date"],"供应商配送批次":["supplier","expected_on","progress"],"食材扫码验收":["supplier","inspector"],
		"每周膳食任务":["task_kind","assigned_to"],"逐餐供餐与日结":["meal_date","kitchen_warehouse"],
		"食品留样":["meal_type","weight"],"陪餐登记与评价":["companion","meal_type"],"到园成品交接":["supplier","meal_type"],
		"班级进餐反馈":["student_group","meal_type"],"特殊餐交接":["student_group","meal_type"],
		"食品安全检查":["period","canteen"],"监管整改":["progress","assigned_to"],"家长膳食意见":["category","canteen"],
		"食材批次流转":["item_code","supplier"],"标准菜品库":["custom_tjy_dish_category"],"标准食材库":["item_group","stock_uom"],
		"学期膳食项目":["canteen","responsible_user"],"食堂资质与场所档案":["service_mode","manager"],
		"食堂证照与健康证":["subject_kind","credential_type"],"食堂岗位配置":["designation","shift_type"],
		"从业人员培训记录":["topic","employee"],"地方采购与财务流程":["procurement_mode","canteen"],
		"特殊膳食安排":["student_group","student"],"供应商对账单":["supplier","canteen"],"食堂会计凭证申请":["operation","canteen"],
	};
	const dimensions = {
		canteen:"涉及食堂", custom_tjy_canteen:"涉及食堂", week_start:"供餐周数",company:"涉及园所",schedule_date:"需用日期数",
		supplier:"供应商数",expected_on:"到货日期数",inspector:"验收人数",task_kind:"任务类型",assigned_to:"负责人数",
		meal_date:"供餐天数",kitchen_warehouse:"厨房仓数",meal_type:"餐次种类",companion:"陪餐人数",student_group:"涉及班级",
		period:"检查类型",progress:"进度类别",category:"意见类别",item_code:"食材种数",custom_tjy_dish_category:"菜品分类",
		item_group:"食材分类",stock_uom:"计量单位种数",responsible_user:"负责人数",service_mode:"供餐方式",manager:"负责人数",
		subject_kind:"归属类别",credential_type:"证照类别",designation:"岗位种数",shift_type:"班次种类",topic:"培训主题",
		employee:"参训人数",procurement_mode:"采购模式",student:"涉及幼儿",operation:"业务类型",
	};
	const present = value => value !== null && value !== undefined && value !== "";
	const unique = (rows,key) => [...new Set(rows.map(row => row[key]).filter(present))];
	const number = new Intl.NumberFormat("zh-CN",{maximumFractionDigits:3});
	function metric(label,value,unit="",tone="") { return {label,value:String(value),unit,tone}; }
	function distinct(rows,field,label) {
		const values=unique(rows,field);
		return values.length ? metric(label,number.format(values.length)) : null;
	}
	function listFacts(title,rows) {
		const facts=[metric("已加载记录",number.format(rows.length),"条")];
		for (const field of listDimensions[title] || []) {
			if (field === "weight") {
				const weights=unique(rows,field).map(Number).filter(Number.isFinite);
				if (weights.length) facts.push(metric("单份留样量",range(weights),"克"));
			} else {
				const fact=distinct(rows,field,dimensions[field]);
				if (fact) facts.push(fact);
			}
		}
		return facts;
	}
	function range(values) {
		const lo=values.reduce((a,b)=>Math.min(a,b)), hi=values.reduce((a,b)=>Math.max(a,b));
		return lo===hi ? number.format(lo) : number.format(lo)+"–"+number.format(hi);
	}
	const reportDimensions = {
		"实时库存与效期":["item_code","warehouse"],"食堂盘点报表":["item_code","warehouse"],
		"监管数据质量":["category","canteen"],"膳食台账":["meal_date","meal_week"],"食材采购报表":["item_code","supplier"],
		"食材采购与消耗分析":["item_code","stock_uom"],"膳食质量指标":["metric"],"食堂证照到期提醒":["credential_type"],
		"人员配置分析":["designation","shift_type"],"供应商对账与结算":["supplier","reconciliation"],
		"食堂账务记录":["account","canteen"],"食堂经营报表":["date","canteen"],"食堂收支报表":["canteen"],
	};
	function reportFacts(title,rows) {
		if (!rows.length) return [];
		if (title==="食堂收支报表" && unique(rows,"currency").length===1 && rows.every(r=>r.currency && ["income","expense","surplus"].every(k=>present(r[k]) && Number.isFinite(Number(r[k]))))) {
			const currency=rows[0].currency==="CNY" ? "元" : rows[0].currency;
			return [["income","确认收入"],["expense","确认费用"],["surplus","收支差额"]].map(([key,label])=>
				metric(label,new Intl.NumberFormat("zh-CN",{minimumFractionDigits:2,maximumFractionDigits:2}).format(rows.reduce((sum,row)=>sum+Number(row[key]),0)),currency));
		}
		if (title==="食堂经营报表") {
			const closed=rows.filter(row=>row.stage==="已日结");
			const facts=[metric("已日结",closed.length,"条"),metric("待日结或核对",rows.length-closed.length,"条",closed.length<rows.length ? "attention" : "")];
			if (closed.length && closed.every(row=>present(row.actual) && Number.isFinite(Number(row.actual)))) {
				facts.push(metric("已日结实际供餐",number.format(closed.reduce((sum,row)=>sum+Number(row.actual),0)),"人次"));
			}
			return facts;
		}
		const captions={...dimensions,warehouse:"涉及仓库",meal_week:"供餐周数",metric:"指标项数",reconciliation:"对账单数",account:"会计科目数",date:"统计天数"};
		const facts=(reportDimensions[title] || []).map(k=>distinct(rows,k,captions[k])).filter(Boolean);
		if (title==="实时库存与效期" || title==="食堂证照到期提醒") {
			const label=title==="实时库存与效期" ? "需核对记录" : "临期或过期";
			const issues=rows.filter(r=>r.stage && (title==="实时库存与效期" ? r.stage!=="正常" : ["临期","已过期"].includes(r.stage))).length;
			facts.push(metric(label,number.format(issues),"条",issues ? "attention" : ""));
		} else if (title==="食堂盘点报表") {
			const diff=rows.filter(r=>present(r.difference) && Number(r.difference)!==0).length;
			facts.push(metric("盘点有差异",number.format(diff),"条",diff ? "attention" : ""));
		} else if (title==="膳食质量指标") {
			facts.push(metric("已有计算结果",number.format(rows.filter(r=>present(r.rate)).length),"项"));
		}
		if (facts.length<3 && title!=="膳食质量指标") facts.unshift(metric("结果明细",number.format(rows.length),"条"));
		return facts.slice(0,3);
	}
	function scopeName(rows,explicitCompany) {
		if (explicitCompany) return explicitCompany;
		const companies=unique(rows,"company");
		return companies.length===1 ? companies[0] : companies.length>1 ? number.format(companies.length)+" 个园所" : "";
	}
	function el(tag,cls,text) {
		const node=document.createElement(tag);
		node.className=cls;
		if (present(text)) node.textContent=text;
		return node;
	}
	function clear(main) { main?.querySelector(":scope > .tjy-overview")?.remove(); }
	function draw(main, title, mode, heading, context, facts, sections=[], completion) {
		const group=byTitle.get(title);
		if (!main || !group) return;
		const route=JSON.stringify(frappe.get_route());
		const signature=JSON.stringify([route,heading,context,facts,sections.map(s=>s.label),completion && [completion.total,completion.done,completion.next?.df.fieldname]]);
		let panel=main.querySelector(":scope > .tjy-overview");
		if (panel?.dataset.signature===signature) return;
		if (!panel) {panel=el("section","tjy-overview");main.prepend(panel);}
		panel.dataset.signature=signature;
		panel.dataset.route=route;
		panel.dataset.mode=mode;
		panel.setAttribute("aria-label",title+"摘要");
		const identity=el("div","tjy-overview-identity");
		const art=el("span","tjy-section-art");
		art.setAttribute("aria-hidden","true");
		const text=el("div","tjy-overview-text");
		const path=el("div","tjy-overview-path");
		const mark=el("span","tjy-overview-mark");
		mark.setAttribute("aria-hidden","true");
		mark.innerHTML=frappe.utils.icon(group[2],"sm");
		path.append(mark,document.createTextNode(group[0]));
		const headline=mode==="form" && heading ? heading : title;
		text.append(path,el("h2","tjy-overview-heading",headline));
		const detail=[mode!=="form" && heading!==title ? heading : "", context].filter(Boolean).join(" · ");
		if (detail) text.append(el("div","tjy-overview-context",detail));
		identity.append(art,text);
		const counters=el("dl","tjy-overview-facts");
		counters.setAttribute("aria-label",mode==="list" ? "本页数据" : mode==="report" ? "筛选结果" : "单据信息");
		for (const fact of facts) {
			const box=el("div","tjy-fact"),value=el("dd","tjy-fact-value",fact.value);
			if (fact.tone) box.dataset.tone=fact.tone;
			if (fact.unit) value.append(el("small","tjy-fact-unit",fact.unit));
			box.append(el("dt","tjy-fact-label",fact.label),value);counters.append(box);
		}
		const metrics=el("div","tjy-metrics");
		if (facts.length) metrics.append(el("div","tjy-metrics-caption",counters.getAttribute("aria-label")),counters);
		if (completion?.total) {
			const detail=el("div","tjy-completion-line");
			detail.append(el("span","","本页必填项"),el("strong","",completion.done+" / "+completion.total));
			const progress=el("progress","tjy-completion-meter");
			progress.max=completion.total;
			progress.value=completion.done;
			progress.setAttribute("aria-label","本页必填项已填写");
			metrics.append(detail,progress);
			if (completion.next) {
				const next=completion.next;
				const target=el("button","tjy-next-field","填写"+next.df.label+" →");
				target.type="button";
				target.onclick=()=>{
					next.wrapper.scrollIntoView({block:"center",behavior:"instant"});
					if (typeof next.set_focus==="function") next.set_focus();
					else next.wrapper.querySelector("input,textarea,select,button")?.focus();
				};
				metrics.append(target);
			}
		}
		panel.replaceChildren(identity,metrics);
		if (sections.length>=2) {
			const nav=el("nav","tjy-section-links");nav.setAttribute("aria-label","跳至表单分区");
			for (const [index,section] of sections.entries()) {
				const button=el("button","tjy-section-link",section.label);
				button.type="button";
				button.onclick=()=>{
					const head=sectionHeads(main)[index];
					if (!head) return;
					if (head.classList.contains("collapsed") || head.parentElement.classList.contains("collapsed")) head.click();
					head.tabIndex=-1;
					head.focus({preventScroll:true});
					head.scrollIntoView({block:"start",behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"instant":"smooth"});
				};
				nav.append(button);
			}
			panel.append(nav);
		}
	}
	function list(list,title) {
		if (list.doctype === "Tongjianyun Canteen Receiving") return;
		const main=list.page.main?.[0],rows=list.data || [];
		const filter=list.get_filters_for_args?.().find(f=>f[0]===list.doctype && f[1]==="company" && f[2]==="=");
		const scope=scopeName(rows,filter?.[3]);
		const facts=listFacts(title,rows);
		if (list.doctype === "Tongjianyun Canteen Policy") {
			draw(main, title, "list", scope || title, "按食堂和有效期设置采购经办人、验收票证和对账方式。", facts);
			return;
		}
		if (list.doctype === "Tongjianyun Canteen Delivery") {
			const count = states => rows.filter(row => row.docstatus !== 2 && states.includes(row.progress)).length;
			draw(main, title, "list", "供应商配送批次", "园方按订单建立批次，供应商接单发货，食堂凭随货码验收。", [
				metric("本页待接单", count(["待接单"]), "批"), metric("备货分拣中", count(["已接单", "备货", "分拣"]), "批"),
				metric("配送途中", count(["配送"]), "批"),
			]);
			return;
		}
		const unit=({"标准食材库":"种食材","标准菜品库":"道菜品"})[title];
		const heading=scope || (unit ? "本页 "+facts[0].value+" "+unit : facts[0].value+" 条"+title+"记录");
		draw(main,title,"list",heading,"",scope ? facts.filter(f=>f.label!=="涉及园所" || f.value!=="1") : facts.slice(1));
	}
	function report(report,title) {
		const main=report.page.main?.[0],rows=report.data || [];
		if (!rows.length) {clear(main);return;}
		const get = key => report.filters?.find(f=>f.df.fieldname===key)?.get_value();
		const start=get("from_date"),end=get("to_date");
		const period=start && end ? (start===end ? start : start+" 至 "+end) : "";
		const scope=scopeName(rows,get("company"));
		draw(main,title,"report",scope || period || "本次查询结果",scope ? period : "",reportFacts(title,rows));
	}
	function sectionHeads(main) {
		return [...main.querySelectorAll(".form-layout > .form-page .form-section > .section-head")]
			.filter(head=>head.offsetWidth && head.textContent.trim() && !head.closest(".grid-row"));
	}
	function form(frm,title,labels) {
		if (["Tongjianyun Canteen Policy", "Tongjianyun Canteen Delivery", "Tongjianyun Canteen Receiving", "Meal Kitchen Day"].includes(frm.doctype)) return;
		const main=frm.page.main?.[0];
		if (!main) return;
		if (frm.is_new()) {
			const sections=sectionHeads(main).map(head=>({label:head.textContent.trim()}));
			const required=Object.values(frm.fields_dict).filter(c=>
				c.df.reqd && !c.df.hidden && c.disp_status==="Write" && c.wrapper?.offsetWidth && typeof c.get_value==="function");
			const missing=required.filter(c=>{
				const value=c.get_value();
				return !present(value) || (typeof value==="string" && !value.trim()) || (Array.isArray(value) && !value.length);
			});
			const completion={total:required.length,done:required.length-missing.length,next:missing[0]};
			draw(main,title,"form",title,"新建记录",[],sections,completion);
			return;
		}
		const readable=k=>{const c=frm.fields_dict[k];return c && !c.df.hidden && c.disp_status!=="None" && c.perm?.[0]?.read!==0 && present(frm.doc[k]) ? frm.doc[k] : "";};
		const canteen=readable("canteen") || readable("custom_tjy_canteen"),company=readable("company");
		const site=labels["Tongjianyun Canteen"]?.[canteen] || "";
		const fields=["service_date","meal_date","arrived_at","posting_date","week_start","due_date","from_date","to_date","meal_type","weight","amount","net_total"];
		const facts=fields.filter(k=>readable(k)!=="").slice(0,3).map(k=>{
			const df=frm.fields_dict[k].df;
			let val=readable(k),unit="";
			if (df.fieldtype==="Datetime") val=frappe.datetime.str_to_user(val);
			if (k==="weight") {val=number.format(val);unit="克";}
			if (df.fieldtype==="Currency") {
				unit=frm.doc.currency || "";
				if (unit==="CNY") unit="元";
				val=number.format(val);
			}
			return metric(df.label.replace(/（克）/g,""),val,unit);
		});
		const sections=sectionHeads(main).map(head=>({label:head.textContent.trim()}));
		if (!site && !company && !facts.length) {
			draw(main,title,"form",title,"",[],sections);
			return;
		}
		draw(main,title,"form",site || company || title,site && company && site!==company ? company : "",facts,sections);
	}
	function scope(title) {
		const group=byTitle.get(title);
		if (group) document.body.dataset.tjyMealGroup=group[1];
		else delete document.body.dataset.tjyMealGroup;
		const route=JSON.stringify(frappe.get_route());
		for (const panel of document.querySelectorAll(".tjy-overview")) if (!group || panel.dataset.route!==route) panel.remove();
	}
	frappe.tjyMealOverview={list,report,form,clear,scope,listFacts,reportFacts,listDimensions,byTitle};
})();
