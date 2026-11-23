const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { resolve } = require("node:path");
const test = require("node:test");
const { runInNewContext } = require("node:vm");

const app = resolve(__dirname, "..");

function load(file, frappe, globals = {}) {
	runInNewContext(readFileSync(resolve(app, file), "utf8"), { frappe, ...globals });
}

function nativeList() {
	const list = {
		make_new_doc: () => "normal Item",
		get_form_link: (doc) => `/desk/native/${encodeURIComponent(doc.name)}`,
		$result: [{ addEventListener(type, handler, capture) {
			assert.equal(type, "click");
			assert.equal(capture, true);
			list.clickRow = handler;
		} }],
	};
	return list;
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
	const doc = { name: "new-item", item_group: "Products" };
	const routes = [];
	const frappe = {
		listview_settings: { Item: {} },
		router: { doctype_layout: null },
		call: async () => ({ message: {
			item_code: "DISH-QA", default_unit: "份", default_item_group: "食谱样例菜品",
		} }),
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
	const list = nativeList();
	frappe.listview_settings.Item.onload(list);
	assert.equal(await list.make_new_doc(), "normal Item");
	assert.equal(doc.item_group, "Products");
	frappe.router.doctype_layout = "标准菜品档案";
	await list.make_new_doc();
	assert.deepEqual(routes, [["Form", "Item", "new-item"]]);
	assert.equal(frappe.route_options.layout, "标准菜品档案");
	assert.equal(doc.custom_tjy_standard_dish, 1);
	assert.equal(doc.is_purchase_item, 0);
	assert.equal(doc.item_code, "DISH-QA");
	assert.equal(doc.stock_uom, "份");
	assert.equal(doc.item_group, "食谱样例菜品");
});

test("dish and recipe row links retain the layout on canonical native forms", () => {
	for (const [doctype, layout, file] of [
		["Item", "标准菜品档案", "standard_dish_list.js"],
		["BOM", "标准菜品", "standard_recipe_list.js"],
	]) {
		const calls = [];
		const frappe = {
			listview_settings: {},
			router: { doctype_layout: null },
			utils: { get_form_link: (type, name, _html, _text, query) =>
				`/desk/${type.toLowerCase()}/${encodeURIComponent(name)}?${new URLSearchParams(query)}` },
			set_route: (...args) => calls.push(args),
		};
		const list = nativeList();
		load(`public/js/${file}`, frappe);
		frappe.listview_settings[doctype].onload(list);
		const row = { name: "测试/A & B" };
		assert.equal(list.get_form_link(row), `/desk/native/${encodeURIComponent(row.name)}`);

		frappe.router.doctype_layout = layout;
		const href = list.get_form_link(row);
		const url = new URL(href, "https://child.example");
		assert.equal(url.pathname, `/desk/${doctype.toLowerCase()}/${encodeURIComponent(row.name)}`);
		assert.equal(url.searchParams.get("layout"), layout);

		const interaction = {
			target: { closest: (selector) => selector.startsWith(".list-row") ?
				{ querySelector: () => url } : null },
			preventDefault: () => calls.push("preventDefault"),
			stopPropagation: () => calls.push("stopPropagation"),
		};
		list.clickRow({ ...interaction, ctrlKey: true });
		list.clickRow({ ...interaction, target: { closest: () => ({}) } });
		assert.deepEqual(calls, []);
		list.clickRow(interaction);
		assert.deepEqual(calls, ["preventDefault", "stopPropagation", [href]]);
		frappe.router.doctype_layout = null;
		list.clickRow(interaction);
		assert.equal(calls.length, 3);
	}
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
		set_df_property() {},
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

function element(tag, attributes = {}) {
	if (typeof tag !== "string") return tag;
	const node = {
		tag, attributes, children: [], events: {}, content: "", value: attributes.value,
		empty() { this.children.length = 0; this.content = ""; return this; },
		text(content) { this.empty(); this.content = String(content); return this; },
		appendTo(parent) { parent.children.push(this); this.parent = parent; return this; },
		remove() { this.parent.children = this.parent.children.filter((child) => child !== this); },
		on(type, selector, action) { this.events[type] = action || selector; return this; },
		focus() {},
		val(...args) { if (!args.length) return this.value; this.value = args[0]; return this; },
		prop(key, value) { this.attributes[key] = value; return this; },
		find(selector) {
			const nodes = selector.split(", ").flatMap((tag) => this.findAll(`<${tag}>`));
			return { prop: (key, value) => nodes.forEach((node) => node.prop(key, value)) };
		},
		findAll(tag) {
			return this.children.flatMap((child) => [...(child.tag === tag ? [child] : []), ...child.findAll(tag)]);
		},
	};
	node[0] = node;
	return node;
}

class DataTable {
	constructor(root, options) {
		this.root = root;
		this.options = options;
		this.columns = options.columns;
		this.refresh(options.data);
		this.cellmanager = {
			getCell$: (column, row) => this.cells[row]?.[column],
			updateCell: (column, row, value) => { this.data[row][column] = value; },
			submitEditing: () => {
				const active = this.active;
				if (!active) return Promise.resolve();
				return Promise.resolve(active.editor.getValue()).then((value) => {
					const oldCell = this.data[active.row][active.column];
					if ((oldCell.content ?? oldCell) === value) return;
					const done = active.editor.setValue(value);
					this.data[active.row][active.column] = value;
					return done;
				});
			},
			deactivateEditing: (submit = true) => {
				const done = submit ? this.cellmanager.submitEditing() : undefined;
				this.active = null;
				this.cellmanager.$editingCell = null;
				return done;
			},
		};
	}
	refresh(data) {
		this.data = data;
		this.cells = Array.from(data, (row) => Array.from(row, () => element("<div>")));
	}
	edit(row, column) {
		const cell = this.data[row][column];
		assert.notEqual(cell.editable, false);
		assert.notEqual(this.columns[column].editable, false);
		const parent = element("<div>");
		const value = cell.content ?? cell;
		const editor = this.options.getEditor(column, row, value, parent, this.columns[column]);
		this.active = { row, column, editor };
		this.cellmanager.$editingCell = this.cells[row][column];
		editor.initValue(value);
		return parent.children[0];
	}
	destroy() { this.destroyed = true; }
}

test("the dish DataTable saves the active cell, links units to the item and keeps published quantities visible", async () => {
	let handlers;
	const wrapper = element("<div>");
	const routes = [];
	const queries = [];
	const controls = [];
	const alerts = [];
	const instances = [];
	let completeLookup;
	let failSave = true;
	let draft = { name: "BOM-DRAFT", state: "待审核", can_edit: false,
		ingredients: [{ name: "番茄", gross: 120, net: 100, uom: "克" }] };
	let secondCompanyDraft;
	const frappe = {
		ui: { form: {
			on: (_doctype, events) => { handlers = events; },
			make_control({ parent, df }) {
				const $input = element("<input>").appendTo(parent);
				const control = {
					name: df.fieldname, $input, query: df.get_query, get_input_value: () => $input.val(),
					get_filter_description: () => "原生筛选说明",
					awesomplete: {
						get_item() { return this.suggestion; },
						item() {
							const caption = { textContent: "编码和说明" };
							return {
								caption,
								querySelector(tag) {
									assert.equal(tag, "p");
									return caption;
								},
							};
						},
					},
					render(suggestion) {
						this.awesomplete.suggestion = suggestion;
						return this.awesomplete.item(suggestion).caption;
					},
					select(code) { $input.events["awesomplete-selectcomplete"]({ originalEvent: { text: { value: code } } }); },
				};
				controls.push(control);
				return control;
			},
		} },
		model: { can_read: () => true },
		db: { get_value: () => new Promise((resolve) => { completeLookup = resolve; }) },
		DataTable: class extends DataTable {
			constructor(...args) { super(...args); instances.push(this); }
		},
		require: async (asset) => assert.equal(asset, "report.bundle.css"),
		utils: { escape_html: (value) => value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;") },
		show_alert: ({ message }) => alerts.push(message),
		call: async ({ method, type, args }) => {
			queries.push({ method, type, ...args });
			const company = args.company || "甲园";
			if (method.endsWith("load_editor")) return { message: company === "甲园" ? {
				mode: "revision", recipe: "BOM-PUBLISHED", modified: "version-1",
				ingredients: [{ row: "row-1", item_code: "TOMATO", name: "番茄", gross: 100, net: 85, uom: "克" }],
			} : { mode: "new", recipe: null, modified: null, ingredients: [] } };
			if (method.endsWith("save_ingredients")) {
				if (failSave) {
					failSave = false;
					throw new Error("Save rejected");
				}
				secondCompanyDraft = { name: "BOM-NEW", state: "草稿", can_edit: true,
					ingredients: [{ name: "番茄", gross: 100, net: 85, uom: "克" }] };
				return { message: { recipe: "BOM-NEW" } };
			}
			return { message: {
				company, companies: ["甲园", "乙园"], can_create_recipe: true,
				current: company === "甲园" ? { name: "BOM-PUBLISHED", ingredients: [
					{ name: "番茄", gross: 100, net: 85, uom: "克" },
					{ name: "<食材>", gross: 1, net: null, uom: "克" },
				] } : null,
				draft: company === "甲园" ? draft : secondCompanyDraft,
			} };
		},
		set_route(...args) { routes.push({ args, ...frappe.route_options }); },
	};
	load("public/js/standard_dishes.js", frappe, { $: element });
	const form = {
		doc: { name: "DISH-QA", custom_tjy_standard_dish: 1, custom_tjy_dish_category: "素菜" },
		doctype_layout: { name: "标准菜品档案" },
		fields_dict: { custom_tjy_dish_recipe_preview: { $wrapper: wrapper } },
		is_new: () => false,
		set_df_property() {},
	};
	const click = (label) => wrapper.findAll("<button>").find((button) => button.content === label).events.click();
	const tableData = () => wrapper.findAll("<table>").map((table) => [
		table.attributes["aria-label"], table.findAll("<td>").map((cell) => cell.content),
	]);
	await handlers.refresh(form);
	assert.deepEqual(tableData(), [
		["在用配方食材", ["番茄", "100", "85", "克", "<食材>", "1", "—", "克"]],
		["待审核配方食材", ["番茄", "120", "100", "克"]],
	]);
	click("查看待审核配方");
	assert.deepEqual(routes.at(-1), { args: ["Form", "BOM", "BOM-DRAFT"], layout: "标准菜品" });

	const select = wrapper.findAll("<select>")[0];
	await select.val("乙园").events.change();
	assert.equal(queries.at(-1).company, "乙园");
	assert.equal(wrapper.findAll("<table>").length, 0);
	await click("添加食材");
	assert.equal(queries.at(-1).method, "tongjianyun.dish_recipe_editor.load_editor");
	const table = instances.at(-1);
	table.edit(0, 0);
	const ingredient = controls.at(-1);
	assert.equal(ingredient.query().query, "tongjianyun.dish_recipe_editor.ingredient_query");
	assert.equal(ingredient.get_filter_description(), "");
	assert.deepEqual(ingredient.render({ value: "TOMATO", label: "TOMATO", description: "番茄, 鲜切" }),
		{ textContent: "番茄, 鲜切", title: "番茄, 鲜切" });
	assert.deepEqual(ingredient.render({ value: "TOMATO", label: "番茄", description: "TOMATO" }),
		{ textContent: "番茄", title: "番茄" });
	ingredient.select("TOMATO");
	await Promise.resolve();
	table.edit(0, 1).val("100");
	await table.cellmanager.deactivateEditing();
	table.edit(0, 2).val("85");
	const saving = click("保存配方草稿");
	await Promise.resolve();
	assert.ok(!queries.some((query) => query.method.endsWith("save_ingredients")));
	completeLookup({ message: { item_name: "<番茄>", stock_uom: "克" } });
	await saving;
	assert.equal(table.columns[0].format("TOMATO"), "&lt;番茄&gt;");
	assert.equal(table.data[0][3], "克");
	assert.equal(table.destroyed, undefined);
	assert.equal(wrapper.findAll("<span>").at(-1).content, "保存失败，当前修改仍可继续编辑。");
	table.edit(0, 3);
	assert.equal(controls.at(-1).query().filters.item_code, "TOMATO");
	assert.equal(controls.at(-1).get_filter_description(), "原生筛选说明");
	await click("保存配方草稿");
	const saved = queries.filter((query) => query.method.endsWith("save_ingredients")).at(-1);
	assert.equal(saved.company, "乙园");
	assert.equal(saved.dish, "DISH-QA");
	assert.deepEqual(JSON.parse(saved.ingredients), [{ item_code: "TOMATO", gross: "100", net: "85", uom: "克" }]);
	assert.deepEqual(alerts, ["配方草稿已保存"]);
	assert.equal(table.destroyed, true);
	assert.ok(wrapper.findAll("<button>").some((button) => button.content === "继续编辑"));
	assert.deepEqual(tableData(), [["配方草稿食材", ["番茄", "100", "85", "克"]]]);

	draft = null;
	await handlers.refresh(form);
	await click("编辑配方");
	assert.equal(wrapper.findAll("<h6>")[0].content, "编辑新版配方草稿");
	const revision = instances.at(-1);
	assert.equal(wrapper.findAll("<table>").length, 1);
	assert.equal(revision.data[0][0].editable, false);
	await click("添加食材");
	assert.equal(revision.data.length, 2);
	await revision.root.events.click({ currentTarget: { dataset: { removeIngredient: "1" } } });
	assert.equal(revision.data.length, 1);
	click("取消");
	assert.equal(revision.destroyed, true);
	assert.equal(wrapper.findAll("<table>").length, 1);
	assert.equal(queries.filter((query) => query.method.endsWith("save_ingredients")).length, 2);
});
