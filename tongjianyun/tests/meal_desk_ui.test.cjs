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
