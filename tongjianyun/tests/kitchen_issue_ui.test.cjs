const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "../i_one_ai/doctype/meal_kitchen_day/meal_kitchen_day.js"), "utf8");

function screen() {
	const fields = {}, calls = [], dialogs = [];
	const ingredient = { item_code: "RICE", item_name: "小米", stock_uom: "克", can_issue: true,
		allowed_actions: ["领用"], planned_qty: "240", suggested_issue_qty: "240" };
	const ledger = { day_name: "DAY", rows: [ingredient], stock_entries: [] };
	const entry = { name: "TRANSFER", action: "领用", docstatus: 0, posting_date: "2026-11-30", latest_issue_date: "2026-11-28",
		consumption_date: "2026-11-28", earliest_consumption_date: "2026-11-27", latest_consumption_date: "2026-11-28",
		issue_quantities: { RICE: "200" }, review_token: "revision", source_warehouse: "原料仓", kitchen_warehouse: "厨房仓" };
	const dateField = {value: "2026-11-28", reportValidity: () => true};
	const widget = () => ({ off() {return this;}, on(e, selector, fn) {if (selector === "[data-consumption-date]") this.recheck = fn; return this;}, find(s) {return ["[data-issue-date]", "[data-consumption-date]"].includes(s) ? [dateField] : this;}, each() {return this;},
		one() {return this;}, addClass() {return this;}, html(v) {this.content = v; return this;} });
	const root = widget();
	class Dialog {
		constructor() {this.$wrapper = widget(); this.fields_dict = { details: { $wrapper: widget() } }; dialogs.push(this);}
		set_primary_action(label, action) {this.label = label; this.confirm = action;}
		get_primary_btn() {return { prop: (_, value) => {this.disabled = value;} };}
		show() {this.visible = true;}
		hide() {this.visible = false;}
	}
	const frm = {doc: {name: "DAY", meal_date: "2026-11-30", docstatus: 0, meals: []}, fields_dict: {ledger_html: {$wrapper: root}},
		is_new: () => false, is_dirty: () => false, layout: {}, toolbar: {get_action_status: () => ""}, add_custom_button() {}, perm: [{write: 1}]};
	const frappe = {ui: {form: {on: (name, events) => {fields[name] = events;}}, Dialog}, boot: {},
		utils: {escape_html: String, icon: () => ""}, datetime: {str_to_obj: d => new Date(d), str_to_user: String, get_today: () => "2026-11-30"},
		workflow: {has_workflow: () => false}, model: {can_create: () => true}, show_alert() {},
		set_route() {assert.fail("操作离开了厨房执行单");},
		call: async ({method, args}) => {
			const action = method.split(".").pop();
			if (action === "get_kitchen_ledger") return {message: ledger};
			calls.push({action, args});
			if (action === "preview_kitchen_consumption_date") return {message: {consumption_date: args.consumption_date, review_token: "new-date", review_blocker: ""}};
			if (action === "create_kitchen_stock_entry") ledger.stock_entries = [entry];
			else if (["approve_kitchen_issue", "approve_kitchen_consumption"].includes(action)) Object.assign(entry, {docstatus: 1, can_review: false, approved_by: "主管", approved_at: "2026-11-30"});
			else assert.fail(action);
			return {message: {stock_entry: entry.name}};
		}};
	vm.runInNewContext(script, {frappe, cur_frm: frm, __: String});
	fields["Meal Kitchen Day"].refresh(frm);
	return {k: frm._kitchen, root, entry, ledger, calls, dialogs, dateField};
}

test("生成领用草稿留在本页，创建人可以核对真实领用量", async () => {
	const {k, root, entry, calls, dialogs} = screen();
	await k.load();
	k.changed({dataset: {map: "qty", code: "RICE"}, value: "200"});
	await k.createDraft();
	assert.equal(calls[0].args.items[0].qty, "200");
	assert.match(root.content, /待库存主管审核/);
	assert.match(root.content, /200 克/);
	assert.doesNotMatch(root.content, /生成领用单，待审核/);
	k.openStockReview(entry.name, "领用");
	assert.equal(dialogs[0].confirm, undefined);
	assert.match(dialogs[0].fields_dict.details.$wrapper.content, /与计划有差异/);
});

test("耗用预填建议量并保留实际修改，清空或填零的食材不进入草稿", async () => {
	const {k, root, ledger, calls, entry} = screen();
	Object.assign(entry, {name: "USE", action: "耗用", consumption_lines: {RICE: {qty: "240", before: "240", after: "0"}}});
	ledger.rows = Object.entries({RICE: "240", EGG: "0.624", MILK: "1.8", TOFU: "0.384"}).map(
		([item_code, qty]) => ({
			item_code, stock_uom: item_code === "RICE" ? "克" : "公斤",
			allowed_actions: ["耗用", "退料", "损耗"], balance_qty: qty, suggested_consumption_qty: qty,
		}),
	);
	await k.load();
	const open = (action) => k.activate({dataset: {act: "stock:" + action}});
	await open("耗用");
	assert.match(root.content, /data-code="RICE" value="240"/);
	assert.match(root.content, /data-code="EGG" value="0.624"/);
	for (const [code, value] of [["EGG", "0.5"], ["MILK", ""], ["TOFU", "0"]])
		k.changed({dataset: {map: "qty", code}, value});
	await open("退料");
	assert.match(root.content, /data-code="RICE" value=""/);
	await open("耗用");
	assert.match(root.content, /data-code="MILK" value=""/);
	assert.match(root.content, /data-code="TOFU" value="0"/);
	assert.equal(calls.length, 0);
	await k.createDraft();
	assert.equal(calls[0].args.action, "耗用");
	assert.deepEqual(Array.from(calls[0].args.items, row => ({...row})), [
		{item_code: "RICE", qty: "240"}, {item_code: "EGG", qty: "0.5"},
	]);
	await k.load();
	assert.doesNotMatch(root.content, /提交耗用审核/);
	assert.match(root.content, /待库存主管审核/);
	k.openStockReview(entry.name, "耗用");
	assert.equal(k.stockDialog.confirm, undefined);
});

test("启用单独工作流时不可直接调拨", async () => {
	const {k, entry, ledger, calls, dialogs} = screen();
	Object.assign(entry, {can_review: true, review_blocker: "请按已启用的库存审批工作流审批"});
	ledger.stock_entries.push(entry);
	await k.load();
	k.openStockReview(entry.name, "领用");
	assert.equal(dialogs[0].disabled, true);
	await dialogs[0].confirm();
	assert.equal(calls.length, 0);
});

test("主管确认时使用已核对的版本并返回本页显示调拨结果", async () => {
	const {k, root, entry, ledger, calls, dialogs} = screen();
	entry.can_review = true;
	ledger.stock_entries.push(entry);
	await k.load();
	k.openStockReview(entry.name, "领用");
	const d = dialogs[0];
	assert.equal(d.label, "确认领用并调拨");
	assert.match(d.fields_dict.details.$wrapper.content, /供餐日期 2026-11-30/);
	assert.match(d.fields_dict.details.$wrapper.content, /data-issue-date max="2026-11-28" value="2026-11-28"/);
	assert.equal(d.disabled, false);
	await Promise.all([d.confirm(), d.confirm()]);
	assert.equal(calls.length, 1);
	assert.deepEqual({...calls[0].args}, {day_name: "DAY", stock_entry: "TRANSFER", review_token: "revision", issue_date: "2026-11-28"});
	assert.equal(d.visible, false);
	assert.match(root.content, /已领用/);
	assert.match(root.content, /审核人 主管/);
	assert.match(root.content, /去逐餐供餐/);
});

test("既有耗用草稿在余料盘点审核，显示扣减前后数量和审核记录", async () => {
	const {k, root, entry, ledger, calls, dialogs} = screen();
	Object.assign(entry, {name: "USE", action: "耗用", can_review: true, prepared_by: "厨房经办",
		consumption_lines: {RICE: {before: "240", qty: "200", after: "40"}}});
	ledger.stock_entries = [entry];
	await k.load();
	await k.activate({dataset: {act: "view:ledger"}});
	assert.match(root.content, /审核耗用/);
	assert.doesNotMatch(root.content, /href="\/desk\/stock-entry\/USE"/);
	await k.activate({dataset: {act: "consumption:USE"}});
	const d = dialogs[0];
	assert.match(d.fields_dict.details.$wrapper.content, /小米[\s\S]*240 克[\s\S]*200 克[\s\S]*40 克/);
	assert.equal(d.label, "确认耗用并扣减库存");
	await Promise.all([d.confirm(), d.confirm()]);
	assert.equal(calls.length, 1);
	assert.equal(calls[0].action, "approve_kitchen_consumption");
	assert.deepEqual({...calls[0].args}, {day_name: "DAY", stock_entry: "USE", review_token: "revision", consumption_date: "2026-11-28"});
	assert.match(root.content, /审核人 主管/);
	assert.match(root.content, /清点厨房余料/);
});

test("调整实际加工日期后，必须使用新日期的核对结果", async () => {
	const {k, entry, ledger, calls, dialogs, dateField} = screen();
	Object.assign(entry, {action: "耗用", can_review: true, review_blocker: "2026-11-30 起可确认",
		consumption_lines: {RICE: {before: "240", qty: "200", after: "40", lot_warning: "大米批次有效期至 2026-11-29"}}});
	ledger.stock_entries = [entry];
	await k.load();
	k.openStockReview(entry.name, "耗用");
	assert.match(dialogs[0].fields_dict.details.$wrapper.content, /2026-11-30 起可确认/);
	assert.match(dialogs[0].fields_dict.details.$wrapper.content, /大米批次有效期至 2026-11-29/);
	assert.equal(dialogs[0].disabled, true);
	await dialogs[0].confirm();
	assert.equal(calls.length, 0);
	dateField.value = "2026-11-27";
	await dialogs[0].fields_dict.details.$wrapper.recheck({currentTarget: dateField});
	assert.equal(dialogs[0].disabled, false);
	await dialogs[0].confirm();
	assert.equal(calls.at(-1).args.consumption_date, dateField.value);
	assert.equal(calls.at(-1).args.review_token, "new-date");
});
