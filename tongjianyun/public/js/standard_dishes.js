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
			method: "tongjianyun.dish_library.copy_recipe",
			type: "POST",
			args: { dish, source },
			freeze: true,
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
		if (draft) {
			const label = draft.can_edit ? "继续编辑" : draft.state === "待审核" ? "查看待审核配方" : "查看草稿";
			recipeAction($actions, label, () => openRecipe(draft.name), true);
		} else if (can_create_recipe && (company || !companies.length)) {
			if (current) {
				recipeAction($actions, "复制为新版", () => copyRecipe(dish.name, current.name));
			} else {
				recipeAction($actions, "添加配方", () => addRecipe(dish, company), true);
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
			return;
		}

		const hint = draft ? `暂无在用配方，当前配方${draft.state === "草稿" ? "为草稿" : draft.state}。` :
			!company && companies.length ? "请选择机构查看配方。" : "暂无在用配方。";
		$("<div>", { class: "text-muted" }).text(hint).appendTo($content);
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
