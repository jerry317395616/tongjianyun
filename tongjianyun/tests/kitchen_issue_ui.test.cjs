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
	const entry = { name: "TRANSFER", action: "领用", docstatus: 0, posting_date: "2026-11-30",
		issue_quantities: { RICE: "200" }, review_token: "revision", source_warehouse: "原料仓", kitchen_warehouse: "厨房仓" };
	const widget = () => ({ off() {return this;}, on() {return this;}, find() {return this;}, each() {return this;},
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
		utils: {escape_html: String, icon: () => ""}, datetime: {str_to_obj: d => new Date(d), str_to_user: String},
		workflow: {has_workflow: () => false}, model: {can_create: () => true}, show_alert() {},
		set_route() {assert.fail("领用操作离开了厨房执行单");},
		call: async ({method, args}) => {
			const action = method.split(".").pop();
			if (action === "get_kitchen_ledger") return {message: ledger};
			calls.push({action, args});
			if (action === "create_kitchen_stock_entry") ledger.stock_entries = [entry];
			else if (action === "approve_kitchen_issue") Object.assign(entry, {docstatus: 1, can_review: false, approved_by: "主管", approved_at: "2026-11-30"});
			else assert.fail(action);
			return {message: {stock_entry: entry.name}};
		}};
	vm.runInNewContext(script, {frappe, cur_frm: frm, __: String});
	fields["Meal Kitchen Day"].refresh(frm);
	return {k: frm._kitchen, root, entry, ledger, calls, dialogs};
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
	k.openIssue(entry.name);
	assert.equal(dialogs[0].confirm, undefined);
	assert.match(dialogs[0].fields_dict.details.$wrapper.content, /与计划有差异/);
});

test("主管可提前核对，业务日前禁止提交", async () => {
	const {k, entry, ledger, calls, dialogs} = screen();
	Object.assign(entry, {can_review: true, review_blocker: "2026-11-30 起可确认调拨"});
	ledger.stock_entries.push(entry);
	await k.load();
	k.openIssue(entry.name);
	assert.equal(dialogs[0].disabled, true);
	await dialogs[0].confirm();
	assert.equal(calls.length, 0);
});

test("主管确认时使用已核对的版本并返回本页显示调拨结果", async () => {
	const {k, root, entry, ledger, calls, dialogs} = screen();
	entry.can_review = true;
	ledger.stock_entries.push(entry);
	await k.load();
	k.openIssue(entry.name);
	const d = dialogs[0];
	assert.equal(d.label, "确认领用并调拨");
	assert.equal(d.disabled, false);
	await Promise.all([d.confirm(), d.confirm()]);
	assert.equal(calls.length, 1);
	assert.deepEqual({...calls[0].args}, {day_name: "DAY", stock_entry: "TRANSFER", review_token: "revision"});
	assert.equal(d.visible, false);
	assert.match(root.content, /已领用/);
	assert.match(root.content, /审核人 主管/);
	assert.match(root.content, /去逐餐供餐/);
});
