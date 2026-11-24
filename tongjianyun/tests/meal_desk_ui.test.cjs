const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const script = fs.readFileSync(path.join(__dirname, "../public/js/meal_desk.js"), "utf8");
function desk() {
	const frappe = {
		router:{on() {}, current_shell:"膳食与食堂"}, get_route:() => ["List","Material Request"],
		query_reports:{}, listview_settings:{}, meta:{get_docfield:() => ({})},
		utils:{escape_html:s => String(s).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll('"',"&quot;"),
			get_form_link:(dt,id) => "/desk/" + dt + "/" + encodeURIComponent(id)},
	};
	vm.runInNewContext(script,{frappe,document:{}, $:() => ({on(){}}), URLSearchParams});
	return frappe;
}
test("meal reports keep original link IDs and escape display names", () => {
	const f = desk(), name = "Inventory";
	f.query_reports[name] = {formatter:(v,r,c,d,format) => c.fieldname==="qty" ? "quantity drilldown" : format(v,r,c,d)};
	f.tjyMealDesk.registerReport(name,"库存");
	const format = f.query_reports[name].formatter, row = {_meal_labels:{item:"白米 <一等>"}};
	assert.match(format("QHXB-RICE",0,{fieldname:"item",fieldtype:"Link",options:"Item"},row,()=>"fallback"),
		/href="\/desk\/Item\/QHXB-RICE".*白米 &lt;一等>/);
	assert.equal(format(0,0,{fieldname:"qty"},row,()=>"0"),"quantity drilldown");
	assert.equal(format("ID",0,{fieldname:"item",fieldtype:"Link",options:"Item"},{},()=>"original"),"original");
});
test("the meal purchase list keeps original actions, saved layouts and general ERP columns", async () => {
	const f = desk(), calls = [];
	f.listview_settings["Material Request"]={onload() { calls.push("original action"); }};
	f.tjyMealDesk.installLists(); f.tjyMealDesk.installLists();
	const list={list_filter:{active_layout_name:"default_layout"},columns:[],async before_refresh(){},
		async setup_columns(fields){calls.push(fields?.map(c=>c.fieldname).join(",") || "native");}};
	f.listview_settings["Material Request"].onload(list);
	await list.before_refresh();
	assert.deepEqual(calls,["original action","title,status_field,company,transaction_date,schedule_date"]);
	list.list_filter.active_layout_name="我的采购视图";
	await list.setup_columns();
	assert.equal(calls.at(-1),"native");
	list.list_filter.active_layout_name="default_layout";
	f.router.current_shell="Stock";
	await list.setup_columns();
	assert.equal(calls.at(-1),"native");
});

function overview() {
	const frappe = {};
	vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../public/js/meal_overview.js"), "utf8"), {frappe});
	return frappe.tjyMealOverview;
}
test("all forty meal entries have a group and sample weights describe the loaded rows", () => {
	const ui = overview();
	assert.equal(ui.byTitle.size, 40);
	assert.equal(Object.keys(ui.listDimensions).length, 27);
	const result = ui.listFacts("食品留样", [
		{meal_type:"早餐",weight:138}, {meal_type:"午餐",weight:135}, {meal_type:"午餐",weight:null}
	]);
	assert.equal(result[0].value, "3");
	assert.equal(result[1].value, "2");
	assert.equal(result[2].value, "135–138");
	assert.equal(result[2].unit, "克");
});
test("report summaries preserve zero, evidence gaps, and currency boundaries", () => {
	const ui = overview();
	const row = {currency:"CNY",income:432,expense:194.91,surplus:237.09};
	assert.equal(ui.reportFacts("食堂收支报表",[row])[2].value, "237.09");
	assert.equal(ui.reportFacts("食堂收支报表",[row,{...row,currency:"USD"}]).some(f=>f.label==="收支差额"),false);
	assert.equal(ui.reportFacts("食堂收支报表",[{...row,income:null}]).some(f=>f.label==="确认收入"),false);
	assert.equal(ui.reportFacts("膳食质量指标",[{metric:"a",rate:0},{metric:"b",rate:null}]).find(f=>f.label==="已有计算结果").value,"1");
	assert.equal(ui.reportFacts("实时库存与效期",[{stage:"正常"},{stage:"待核对"},{}]).find(f=>f.label==="需核对记录").value,"1");
});
test("operations reports count meals only when a day has been closed", () => {
	const ui = overview();
	const result = ui.reportFacts("食堂经营报表", [
		{stage:"已日结",actual:36}, {stage:"待日结"}, {stage:"日结依据待核对",actual:18}
	]);
	assert.equal(result.find(f=>f.label==="已日结实际供餐").value, "36");
	assert.equal(result.find(f=>f.label==="待日结或核对").value, "2");
	assert.equal(ui.reportFacts("食堂经营报表",[{stage:"待日结"}]).length, 2);
});

function quickViews() {
	const frappe = {perm:{has_perm:() => true}};
	vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../public/js/meal_list_filters.js"), "utf8"), {frappe});
	return frappe.tjyMealFilters;
}
test("list shortcuts keep company, support zero and preserve advanced filters", async () => {
	const ui = quickViews(), dt = "Tongjianyun Food Sample";
	let filters = [[dt,"company","=","青禾"],[dt,"docstatus","=",0]], count = 0;
	const list = {doctype:dt, meta:{fields:[],is_submittable:1}, start:20,
		filter_area:{get:() => filters, async remove(k){filters=filters.filter(f=>f[1]!==k);}, async add(fs){filters.push(...fs);}},
		async refresh(){count++;}};
	const config=ui.choicesFor(list,"食材扫码验收");
	assert.equal(ui.currentChoice(list,config),"0");
	await ui.setChoice(list,config,"1");
	assert.equal(filters[0][3],"青禾");
	assert.equal(ui.currentChoice(list,config),"1");
	assert.equal(list.start,0);
	await ui.setChoice(list,config,"");
	assert.equal(filters.length,1);
	for (const filter of [[dt,"docstatus","in",[0,1]], [dt,"docstatus","=",1,true], ["Other","docstatus","=",1]]) {
		filters.push(filter);
		assert.equal(ui.currentChoice(list,config),null);
		await ui.setChoice(list,config,"0");
		assert.equal(count,2);
		filters.pop();
	}
});
test("sample shortcuts follow the site's configured meal choices", () => {
	const ui=quickViews();
	const list={doctype:"Tongjianyun Food Sample",meta:{fields:[{fieldname:"meal_type",fieldtype:"Select",label:"餐次",options:"早餐\n午餐"}]}};
	const config=ui.choicesFor(list,"食品留样");
	assert.equal(config.field,"meal_type");
	assert.equal(config.choices.map(choice=>choice[1]).join("、"),"早餐、午餐");
});
