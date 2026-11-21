const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const test = require("node:test");
const { runInNewContext } = require("node:vm");

const app = resolve(__dirname, "..");
const route = "standard-dish-library";

test("adding a recipe carries the selected dish into the standard recipe layout", async () => {
	const buttons = {};
	const makeNode = (tag) => ({
		appendTo() { return this; },
		empty() { return this; },
		append() { return this; },
		addClass() { return this; },
		text(label) {
			this.label = label;
			return this;
		},
		on(event, handler) {
			if (tag === "<button>" && event === "click") buttons[this.label] = handler;
			return this;
		},
	});
	const dish = { name: "DISH-01", category: "素菜", state: "待配置配方", can_make_recipe: true };
	const doc = { name: "new-bom-01" };
	const navigations = [];
	const frappe = {
		pages: { [route]: {} },
		ui: { make_app_page: () => ({
			main: makeNode("<main>"),
			add_field: () => ({ get_value: () => "" }),
			clear_primary_action() {},
		}) },
		call: async () => ({ message: {
			rows: [dish], can_create_recipe: true, can_create_dish: false, page_size: 20,
		} }),
		model: {
			with_doctype(doctype, callback) {
				assert.equal(doctype, "BOM");
				return callback();
			},
			get_new_doc() {
				frappe.route_options = null;
				return doc;
			},
		},
		set_route(...args) {
			navigations.push({ args, layout: frappe.route_options?.layout });
		},
	};
	const path = resolve(app, "tongjianyun/page/standard_dish_library/standard_dish_library.js");
	runInNewContext(readFileSync(path, "utf8"), { frappe, $: makeNode });
	const wrapper = {};
	frappe.pages[route].on_page_load(wrapper);
	await frappe.pages[route].on_page_show(wrapper);
	buttons["添加配方"]();
	assert.deepEqual(navigations, [{ args: ["Form", "BOM", doc.name], layout: "标准菜品" }]);
	assert.equal(doc.item, dish.name);
	assert.equal(doc.custom_tjy_standard_recipe, 1);
	assert.equal(doc.custom_tjy_recipe_category, "素菜");
	assert.equal(doc.quantity, 1);
});
