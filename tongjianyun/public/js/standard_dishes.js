(() => {
	const dishLayout = "标准菜品档案";
	const recipeLayout = "标准菜品";
	const reuseLabel = "使用同名菜品";
	const previewField = "custom_tjy_dish_recipe_preview";

	function openRecipe(name) {
		frappe.route_options = { layout: recipeLayout };
		return frappe.set_route("Form", "BOM", name);
	}

	function viewRecipes(dish, company) {
		frappe.route_options = { layout: recipeLayout, item: dish, custom_tjy_standard_recipe: 1 };
		if (company) frappe.route_options.company = company;
		return frappe.set_route("List", "BOM");
	}

	function addRecipe(dish, company) {
		return frappe.model.with_doctype("BOM", () => {
			const doc = frappe.model.get_new_doc("BOM", null, null, true);
			doc.item = dish.name;
			if (company) doc.company = company;
			doc.quantity = 1;
			doc.custom_tjy_standard_recipe = 1;
			doc.custom_tjy_recipe_category = dish.custom_tjy_dish_category || "";
			return openRecipe(doc.name);
		});
	}

	async function copyRecipe(dish, source) {
		const { message } = await frappe.call({
			method: "tongjianyun.dish_library.copy_recipe", type: "POST", freeze: true, args: { dish, source },
		});
		return openRecipe(message.recipe);
	}

	function recipeAction($container, label, action, primary = false) {
		return $("<button>", { type: "button", class: `btn btn-xs mr-2 mb-2 ${primary ? "btn-primary" : "btn-default"}` })
			.text(label).on("click", action).appendTo($container);
	}

	function ingredientTable($container, rows) {
		const $table = $("<table>", { class: "table table-bordered table-sm mb-0", "aria-label": "每份食材带量" })
			.appendTo($("<div>", { class: "table-responsive" }).appendTo($container));
		const $head = $("<tr>").appendTo($("<thead>").appendTo($table));
		for (const title of ["食材名称", "每份采购毛用量", "每份可食净量", "单位"]) {
			$("<th>", { scope: "col" }).text(title).appendTo($head);
		}
		const $body = $("<tbody>").appendTo($table);
		for (const row of rows) {
			const $line = $("<tr>").appendTo($body);
			for (const value of [row.name, row.gross, row.net, row.uom]) {
				$("<td>").text(value ?? "—").appendTo($line);
			}
		}
	}

	function recipeLink($cell, fieldname, doctype, getQuery, change) {
		return frappe.ui.form.make_control({
			parent: $cell[0], render_input: true, only_input: true,
			df: { fieldtype: "Link", fieldname, options: doctype, get_query: getQuery, change },
		});
	}

	function ingredientEditorRow($body, dish, ingredient, remove) {
		const $line = $("<tr>").appendTo($body);
		const $item = $("<td>", { class: "w-25" }).appendTo($line);
		const quantityInput = (value, label) => $("<input>", {
			type: "number", min: 0, step: "any", "aria-label": label, class: "form-control input-xs",
		}).val(value ?? "").appendTo($("<td>").appendTo($line));
		const $gross = quantityInput(ingredient.gross, "每份采购毛用量");
		const $net = quantityInput(ingredient.net, "每份可食净量");
		const $unit = $("<td>", { class: "w-25" }).appendTo($line);
		let item;
		const itemCode = () => ingredient.item_code || item?.get_value();
		const unit = recipeLink($unit, "uom", "UOM", () => ({
			query: "erpnext.controllers.queries.get_item_uom_query", filters: { item_code: itemCode() },
		}));
		if (ingredient.item_code) {
			$item.text(ingredient.name);
			unit.set_value(ingredient.uom);
		} else {
			item = recipeLink($item, "item_code", "Item", () => ({
				query: "erpnext.manufacturing.doctype.bom.bom.item_query",
				filters: { name: ["!=", dish], disabled: 0, is_fixed_asset: 0, include_item_in_manufacturing: 1 },
			}), async () => {
				const code = itemCode();
				await unit.set_value("");
				if (!code) return;
				const { message } = await frappe.db.get_value("Item", code, "stock_uom");
				if (itemCode() === code && !unit.get_value()) await unit.set_value(message?.stock_uom || "");
			});
		}
		const read = () => ({
			row: ingredient.row, item_code: itemCode(), gross: $gross.val(), net: $net.val(), uom: unit.get_value(),
		});
		recipeAction($("<td>").appendTo($line), "删除", () => { remove(read); $line.remove(); });
		return read;
	}

	function renderIngredientEditor($editor, dish, company, source, onClose, onSaved) {
		const inputs = new Set();
		$("<h6>", { class: "mb-2" }).text(source.mode === "revision" ? "编辑新版配方草稿" : "编辑配方草稿").appendTo($editor);
		const $table = $("<table>", { class: "table table-bordered table-sm", "aria-label": "编辑食材明细" }).appendTo($editor);
		const $head = $("<tr>").appendTo($("<thead>").appendTo($table));
		for (const title of ["食材", "每份采购毛用量", "每份可食净量", "单位", "操作"]) {
			$("<th>", { scope: "col" }).text(title).appendTo($head);
		}
		const $body = $("<tbody>").appendTo($table);
		const addRow = (ingredient = {}) => inputs.add(ingredientEditorRow($body, dish, ingredient, (read) => inputs.delete(read)));
		for (const ingredient of source.ingredients) addRow(ingredient);
		if (!inputs.size) addRow();
		recipeAction($editor, "添加食材", () => addRow());
		recipeAction($editor, "取消", onClose);
		const $status = $("<span>", { class: "text-muted", role: "status" });
		const $save = recipeAction($editor, "保存配方草稿", async () => {
			const ingredients = JSON.stringify(Array.from(inputs, (read) => read()));
			$status.empty();
			$save.prop("disabled", true);
			try {
				await frappe.call({
					method: "tongjianyun.dish_recipe_editor.save_ingredients", type: "POST", freeze: true,
					args: { dish, company, recipe: source.recipe, modified: source.modified, ingredients },
				});
				frappe.show_alert({ message: "配方草稿已保存", indicator: "green" });
				return onSaved();
			} catch {
				$status.text("保存失败，当前修改仍可继续编辑。");
			} finally {
				$save.prop("disabled", false);
			}
		}, true);
		$status.appendTo($editor);
	}

	async function loadIngredientEditor($editor, dish, company, onClose, onSaved) {
		$editor.text("正在加载配方草稿…");
		try {
			const { message } = await frappe.call({
				method: "tongjianyun.dish_recipe_editor.load_editor", type: "GET", args: { dish, company },
			});
			renderIngredientEditor($editor.empty(), dish, company, message, onClose, onSaved);
		} catch {
			onClose();
		}
	}

	function renderPreview($content, $wrapper, dish, preview) {
		const { current, draft, company, companies, can_create_recipe } = preview;
		const $header = $("<div>", { class: "d-flex flex-wrap align-items-baseline justify-content-between" }).appendTo($content);
		if (companies.length > 1) {
			const $label = $("<label>", { class: "d-flex align-items-center text-muted mb-2" }).text("机构").appendTo($header);
			const $select = $("<select>", { class: "form-control input-xs ml-2" }).appendTo($label);
			if (!company) $("<option>", { value: "", disabled: true }).text("请选择").appendTo($select);
			for (const name of companies) $("<option>", { value: name }).text(name).appendTo($select);
			$select.val(company || "").on("change", () => loadPreview($wrapper, dish, $select.val()));
		} else if (company) {
			$("<span>", { class: "text-muted mb-2" }).text(company).appendTo($header);
		}

		const $actions = $("<div>", { class: "ml-auto" }).appendTo($header);
		const $editor = $("<div>", { class: "mt-3" });
		const startEditor = (selectedCompany) => {
			$header.find("button, select").prop("disabled", true);
			return loadIngredientEditor($editor, dish.name, selectedCompany, () => {
				$editor.empty();
				$header.find("button, select").prop("disabled", false);
			}, () => loadPreview($wrapper, dish, selectedCompany));
		};
		const openEditor = () => {
			if (company) return startEditor(company);
			return frappe.prompt([{ fieldname: "company", fieldtype: "Link", label: "机构", options: "Company", reqd: 1 }],
				({ company: selectedCompany }) => startEditor(selectedCompany), "选择机构", "继续");
		};
		if (draft) {
			if (draft.can_edit && draft.inline_edit !== false) recipeAction($actions, "继续编辑", openEditor, true);
			const label = draft.state === "待审核" ? "查看待审核配方" : "打开草稿";
			recipeAction($actions, label, () => openRecipe(draft.name));
		} else if (can_create_recipe && (company || !companies.length)) {
			if (current?.inline_edit === false) {
				recipeAction($actions, "复制为新版", () => copyRecipe(dish.name, current.name));
			} else {
				recipeAction($actions, current ? "编辑配方" : "添加食材", openEditor, true);
			}
		}
		recipeAction($actions, "查看配方", () => viewRecipes(dish.name, company));

		if (current) {
			const $status = $("<div>", { class: "d-flex flex-wrap align-items-center mb-2" }).appendTo($content);
			$("<span>", { class: "indicator-pill green mr-2" }).text("在用配方").appendTo($status);
			$("<button>", { type: "button", class: "btn btn-link btn-xs mr-2" })
				.text(current.name).on("click", () => openRecipe(current.name)).appendTo($status);
			if (draft) {
				$("<span>", { class: "indicator-pill orange" }).text(`新版${draft.state}`).appendTo($status);
			}
			if (current.ingredients?.length) ingredientTable($content, current.ingredients);
			else $("<div>", { class: "text-muted" })
				.text(current.ingredients ? "在用配方没有食材明细。" : "当前账号无权查看食材明细。").appendTo($content);
		} else {
			const hint = draft ? `暂无在用配方，当前配方${draft.state === "草稿" ? "为草稿" : draft.state}。` :
				!company && companies.length ? "请选择机构查看配方。" : "暂无在用配方。";
			$("<div>", { class: "text-muted" }).text(hint).appendTo($content);
		}
		$editor.appendTo($content);
	}

	async function loadPreview($wrapper, dish, company) {
		const $content = $("<div>").appendTo($wrapper.empty());
		$("<div>", { class: "text-muted", role: "status" }).text("正在加载配方…").appendTo($content);
		try {
			const { message } = await frappe.call({
				method: "tongjianyun.dish_library.recipe_preview",
				type: "GET",
				args: { dish: dish.name, company },
			});
			renderPreview($content.empty(), $wrapper, dish, message);
		} catch {
			$("<span>", { class: "text-muted mr-2" }).text("无法加载配方。").appendTo($content.empty());
			recipeAction($content, "重试", () => loadPreview($wrapper, dish, company));
		}
	}

	async function reuseDish(frm, label, existing) {
		const category = frm.doc.custom_tjy_dish_category;
		if (!category) {
			frappe.msgprint("请先填写菜品分类。");
			return;
		}
		const { message } = await frappe.call({
			method: "tongjianyun.dish_library.save_dish",
			type: "POST",
			args: { label, category, existing },
		});
		frm.doc.__unsaved = 0;
		frappe.route_options = { layout: dishLayout };
		return frappe.set_route("Form", "Item", message.dish);
	}

	frappe.ui.form.on("Item", {
		refresh(frm) {
			if (!frm.doc.custom_tjy_standard_dish) return;
			frm.set_df_property("item_name", "description", "填写菜品本名，例如小米粥。供餐时段在「适用餐次」设置。");
			const $preview = frm.fields_dict?.[previewField]?.$wrapper;
			if (frm.doctype_layout?.name === dishLayout && $preview) {
				if (frm.is_new()) return $preview.text("保存菜品档案后，即可添加配方和食材。");
				if (frappe.model.can_read("BOM")) return loadPreview($preview, frm.doc);
				$preview.text("当前账号无权查看配方。");
				if (!frm.doc.disabled && !frm.doc.is_purchase_item && frappe.model.can_create("BOM")) {
					recipeAction($preview, "添加配方", () => addRecipe(frm.doc), true);
				}
				return;
			}
			if (frm.is_new()) return;
			if (frappe.model.can_read("BOM")) {
				frm.add_custom_button("查看配方", () => viewRecipes(frm.doc.name));
			}
			if (!frm.doc.disabled && !frm.doc.is_purchase_item && frappe.model.can_create("BOM")) {
				frm.add_custom_button("添加配方", () => addRecipe(frm.doc));
			}
		},
		async item_name(frm) {
			if (!frm.is_new() || !frm.doc.custom_tjy_standard_dish) return;
			const label = (frm.doc.item_name || "").trim();
			frm.remove_custom_button(reuseLabel);
			frm.set_intro("");
			if (!label) return;
			const { message } = await frappe.call({
				method: "tongjianyun.dish_library.dish_options",
				type: "GET",
				args: { label },
			});
			if (!frm.is_new() || (frm.doc.item_name || "").trim() !== label || !message.matches?.length) return;
			const names = message.matches.map((match) => match.name);
			frm.set_intro("发现同名自制菜品，请核对后使用。", "orange");
			frm.add_custom_button(reuseLabel, () => frappe.prompt({
				fieldname: "item", fieldtype: "Link", options: "Item", label: "菜品", reqd: 1,
				default: names.length === 1 ? names[0] : undefined,
				get_query: () => ({ filters: { name: ["in", names] } }),
			}, ({ item }) => reuseDish(frm, label, item), reuseLabel));
		},
	});
})();
