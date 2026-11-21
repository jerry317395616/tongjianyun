const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const test = require("node:test");
const { runInNewContext } = require("node:vm");

const app = resolve(__dirname, "..");

function load(file, frappe) {
	runInNewContext(readFileSync(resolve(app, file), "utf8"), { frappe });
}

test("the previous bookmark takes users to the native dish list", () => {
	const page = {};
	const calls = [];
	const frappe = {
		pages: { "standard-dish-library": page },
		set_route(...args) { calls.push(args); },
	};
	load("tongjianyun/page/standard_dish_library/standard_dish_library.js", frappe);
	page.on_page_show();
	assert.deepEqual(calls, [["List", "Item"]]);
	assert.equal(frappe.route_options.layout, "标准菜品档案");
	assert.equal(frappe.route_options.custom_tjy_standard_dish, 1);
});

test("the library creates an Item with dish defaults and leaves the general Item action available", async () => {
	const doc = { name: "new-item" };
	const routes = [];
	const frappe = {
		listview_settings: { Item: {} },
		router: { doctype_layout: null },
		call: async () => ({ message: { item_code: "DISH-QA", default_unit: "份" } }),
		model: {
			with_doctype(doctype, done) {
				assert.equal(doctype, "Item");
				return done();
			},
			get_new_doc() { return doc; },
		},
		set_route(...args) { routes.push(args); },
	};
	load("public/js/standard_dish_list.js", frappe);
	const list = { make_new_doc: () => "normal Item" };
	frappe.listview_settings.Item.onload(list);
	assert.equal(await list.make_new_doc(), "normal Item");
	frappe.router.doctype_layout = "标准菜品档案";
	await list.make_new_doc();
	assert.deepEqual(routes, [["Form", "Item", "new-item"]]);
	assert.equal(frappe.route_options.layout, "标准菜品档案");
	assert.equal(doc.custom_tjy_standard_dish, 1);
	assert.equal(doc.is_purchase_item, 0);
	assert.equal(doc.item_code, "DISH-QA");
	assert.equal(doc.stock_uom, "份");
});

test("a native dish form opens a scoped BOM list and prefilled recipe form", () => {
	let handlers;
	const buttons = {};
	const bom = { name: "new-bom" };
	const routes = [];
	const frappe = {
		ui: { form: { on: (_doctype, events) => { handlers = events; } } },
		model: {
			can_read: () => true,
			can_create: () => true,
			with_doctype: (_doctype, done) => done(),
			get_new_doc: () => bom,
		},
		set_route(...args) { routes.push({ args, item: frappe.route_options.item, layout: frappe.route_options.layout }); },
	};
	load("public/js/standard_dishes.js", frappe);
	handlers.refresh({
		doc: { name: "DISH-QA", custom_tjy_standard_dish: 1, custom_tjy_dish_category: "素菜" },
		is_new: () => false,
		add_custom_button: (label, action) => { buttons[label] = action; },
	});
	buttons["查看配方"]();
	buttons["添加配方"]();
	assert.deepEqual(routes, [
		{ args: ["List", "BOM"], item: "DISH-QA", layout: "标准菜品" },
		{ args: ["Form", "BOM", "new-bom"], item: undefined, layout: "标准菜品" },
	]);
	assert.equal(bom.item, "DISH-QA");
	assert.equal(bom.quantity, 1);
	assert.equal(bom.custom_tjy_recipe_category, "素菜");
	assert.equal(bom.custom_tjy_standard_recipe, 1);
});
