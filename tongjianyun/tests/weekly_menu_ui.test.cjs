const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const test = require("node:test");
const { runInNewContext } = require("node:vm");

function element(tag, attrs = {}) {
	return {
		tag, attrs, length: 1, children: [], events: {}, content: "",
		text(text) { this.content = text; return this; },
		empty() { for (const child of this.children) child.host = null; this.children = []; this.content = ""; return this; },
		css() { return this; }, hide() { this.hidden = true; return this; }, show() { this.hidden = false; return this; },
		addClass(name) { this.attrs.class = `${this.attrs.class || ""} ${name}`.trim(); return this; },
		toggleClass(name, enabled) {
			const classes = new Set((this.attrs.class || "").split(/\s+/).filter(Boolean));
			if (typeof enabled !== "boolean") enabled = !classes.has(name);
			if (enabled) classes.add(name);
			else classes.delete(name);
			this.attrs.class = [...classes].join(" ");
			return this;
		},
		prop(key, value) { this.attrs[key] = value; return this; },
		find() { return this; }, on(type, action) { this.events[type] = action; return this; },
		appendTo(host) { this.host = host; host.children.push(this); return this; },
		insertBefore(anchor) { this.host = anchor.host; this.host.children.splice(this.host.children.indexOf(anchor), 0, this); return this; },
		parent() { return this.host || { length: 0 }; },
		prev() { return this.host.children[this.host.children.indexOf(this) - 1] || { length: 0, remove() {} }; },
		all(type) { return this.children.flatMap((child) => [...(child.tag === type ? [child] : []), ...child.all(type)]); },
	};
}

test("native week keeps creation compact and shows the calendar and meal drawer after saving", async () => {
	let hooks, dialog, initialized = false, saved, creating = true, intro;
	const page = element("<div>");
	const grid = element("<div>").appendTo(page);
	const days = ["2026-11-23", "2026-11-24", "2026-11-25", "2026-11-26", "2026-11-27"];
	const slots = ["早餐", "早点", "午餐", "午点", "晚餐"];
	const calls = [];
	const assets = [];
	class Dialog {
		constructor(options) {
			this.options = options;
			this.$wrapper = element("<div>");
			this.primary = element("<button>");
			this.values = Object.fromEntries(options.fields.map((field) => [field.fieldname, field.default]));
			this.fields_dict = Object.fromEntries(options.fields.map((field) => [field.fieldname,
				{ $wrapper: element("<div>"), $input: element("<input>") }]));
			options.fields.find((field) => field.fieldname === "category").onchange();
			dialog = this;
		}
		show() {} hide() { this.hidden = true; } get_value(name) { return this.values[name]; }
		get_primary_btn() { return this.primary; }
	}
	const frappe = {
		ui: { Dialog, form: { on(doctype, events) { assert.equal(doctype, "Meal Planning Week"); hooks = events; } } },
		utils: { debounce: (fn) => fn },
		datetime: { get_today: () => days[1] },
		require: async (path) => assets.push(path),
		msgprint(message) { assert.fail(message); },
		async call({ method, type, args }) {
			const operation = method.split(".").at(-1);
			calls.push([operation, type, args]);
			if (operation === "calendar") return { message: { days, slots, categories: ["素菜"], initialized, meals: initialized ?
				[{ date: days[1], slot: "早餐", menu: "", stopped: true, reason: "园所活动", headcount: 0 }] : [] } };
			if (operation === "initialize") { initialized = true; return { message: { skipped_recipes: 0 } }; }
			if (operation === "get_meal") return { message: { modified: "revision", base_headcount: 40, dishes: [
				{ item: "A", bom: "BOM-A-1", name: "原菜" },
			] } };
			if (operation === "dishes") return { message: { page_size: 15, has_more: false, rows: [
				{ item: "A", bom: "BOM-A-2", name: "原菜", category: "素菜" },
				{ item: "B", bom: "BOM-B", name: "新菜", category: "素菜" },
				{ item: "C", name: "待审菜", status: "配方待审核" },
			] } };
			if (operation === "save_meal") { saved = args; return { message: {} }; }
			throw new Error(operation);
		},
	};
	const form = {
		doc: { name: "MEAL-WEEK-QA", docstatus: 0 }, perm: [{ write: 1 }],
		layout: { wrapper: page },
		fields_dict: { meals: { $wrapper: grid } }, is_new: () => creating ? 1 : undefined, is_dirty: () => false,
		set_intro(text) { intro = text; },
		remove_custom_button() {}, reload_doc: async () => hooks.refresh(form),
	};
	runInNewContext(readFileSync(resolve(__dirname, "../public/js/weekly_menu_editor.js"), "utf8"), { frappe, $: element });
	await hooks.refresh(form);
	assert.equal(page.attrs.class, "tgy-week-create");
	assert.equal(intro, "保存后，可选择空白编排或复制上周。");
	assert.equal(calls.length, 0);
	creating = false;
	page.attrs.class = "";
	await hooks.refresh(form);
	assert.equal(page.attrs.class, "");
	assert.equal(page.all("<td>").length, 25);
	await page.all("<button>").find((node) => node.content === "复制上周").events.click();
	assert.equal(calls.find(([operation]) => operation === "initialize")[2].copy_previous, 1);
	assert.equal(page.all("<button>").filter((node) => node.attrs["aria-label"]).length, 25);
	assert.ok(page.all("<span>").some((node) => node.content === "园所活动"));
	assert.ok(page.all("<th>").some((node) => node.attrs["aria-current"] === "date"));
	assert.deepEqual(assets, ["/assets/tongjianyun/css/weekly_menu_editor.css?v=week-create.css"]);
	assert.equal(page.all("<progress>")[0].attrs.value, 1);
	assert.equal(page.all("<progress>")[0].attrs.max, 25);
	await page.all("<button>").find((node) => node.attrs["aria-label"] === `${days[1]} 午餐 未编排`).events.click();
	await new Promise(setImmediate);
	assert.equal(dialog.$wrapper.attrs.class, "tgy-week-picker");
	dialog.values.excluded_count = 3;
	dialog.options.fields.find((field) => field.fieldname === "excluded_count").onchange();
	assert.equal(dialog.fields_dict.counts_summary.$wrapper.all("<strong>")[0].content, "计划供餐 37 人");
	dialog.values.stopped = 1;
	dialog.options.fields.find((field) => field.fieldname === "stopped").onchange();
	assert.equal(dialog.fields_dict.counts_summary.$wrapper.all("<strong>")[0].content, "计划供餐 0 人");
	const options = dialog.fields_dict.options.$wrapper;
	assert.ok(options.all("<div>").some((node) => node.content === "配方待审核"));
	assert.ok(options.all("<button>").some((node) => node.content === "已选" && node.attrs.disabled));
	options.all("<button>").find((node) => node.content === "添加").events.click();
	dialog.fields_dict.chosen.$wrapper.all("<button>").find((node) => node.content === "上移").events.click();
	await dialog.options.primary_action({ excluded_count: 3, adjustment_reason: "请假" });
	assert.equal(saved.meal_date, days[1]);
	assert.equal(saved.meal_type, "午餐");
	assert.equal(saved.excluded_count, 3);
	assert.equal(saved.modified, "revision");
	assert.deepEqual(JSON.parse(saved.boms), ["BOM-B", "BOM-A-1"]);
	assert.equal(dialog.hidden, true);
});
