(() => {
	const layoutName = "标准食材档案";
	const nutritionTab = "custom_tjy_nutrition_tab";
	const statusField = "custom_tjy_nutrition_status";
	const icons = { profile: "layers", buying: "shopping-cart", more: "settings" };
	const states = { "已匹配": "matched", "待审核": "review" };

	function addIcon($parent, name) {
		return $("<span>", { class: "tjy-ingredient-icon", "aria-hidden": "true" })
			.html(frappe.utils.icon(name, "md")).prependTo($parent);
	}

	function makeProfile(frm, $pane, sections) {
		const $grid = $("<div>", { class: "tjy-ingredient-grid" }).insertBefore(sections.profile.wrapper);
		const $profile = $("<div>", { class: "tjy-ingredient-identity" }).appendTo($grid);
		const $photo = $("<div>", { class: "tjy-ingredient-photo" }).appendTo($profile);
		const $emptyPhoto = $("<div>", { class: "tjy-ingredient-photo-empty" }).appendTo($photo);
		addIcon($emptyPhoto, "image");
		$("<span>").text("暂无食材图片").appendTo($emptyPhoto);
		const $image = $("<img>", { alt: "", hidden: true }).appendTo($photo);
		$image.on("load error", (event) => {
			const loaded = event.type === "load";
			$image.prop("hidden", !loaded);
			$emptyPhoto.prop("hidden", loaded);
		});

		const $identity = $("<div>", { class: "tjy-ingredient-identity-body" }).appendTo($profile);
		const $name = $("<h2>").appendTo($identity);
		$("<div>", { class: "tjy-ingredient-code-label" }).text("食材编码").appendTo($identity);
		const $code = $("<div>", { class: "tjy-ingredient-code" }).appendTo($identity);
		const $summary = $("<div>", { class: "tjy-ingredient-summary" }).appendTo($identity);
		const $nutrition = $("<div>", { class: "tjy-ingredient-nutrition-state" }).appendTo($summary);
		addIcon($nutrition, "leaf");
		$("<span>").text("营养数据").appendTo($nutrition);
		const $status = $("<span>", { class: "tjy-ingredient-pill" }).appendTo($nutrition);
		const $nutritionLink = $("<button>", { type: "button", class: "tjy-ingredient-nutrition-link" })
			.text("前往营养成分").appendTo($summary)
			.on("click", () => frm.layout.select_tab(nutritionTab));
		$("<span>", { "aria-hidden": "true" }).html(frappe.utils.icon("chevron-right", "xs"))
			.appendTo($nutritionLink);

		const $fields = $("<div>", { class: "tjy-ingredient-fields" }).appendTo($grid);
		const $details = $("<div>", { class: "tjy-ingredient-card" }).appendTo($fields)
			.append(sections.profile.wrapper, sections.aliases.wrapper);
		sections.profile.wrapper.addClass("tjy-ingredient-details");
		sections.aliases.wrapper.addClass("tjy-ingredient-aliases");
		sections.buying.wrapper.addClass("tjy-ingredient-card tjy-ingredient-buying").appendTo($fields);
		sections.more.wrapper.addClass("tjy-ingredient-advanced");
		sections.code.wrapper.addClass("tjy-ingredient-original-code");
		for (const key of Object.keys(icons)) {
			if (sections[key].head) addIcon(sections[key].head, icons[key]);
		}

		const ui = { $name, $code, $image, $emptyPhoto, $status, $nutritionLink, $details };
		$pane.addClass("tjy-ingredient-basic").data("tjy-ingredient-basic", ui);
		return ui;
	}

	function renderProfile(frm) {
		if (frm.doctype_layout?.name !== layoutName) return;
		const $pane = frm.layout.tabs.find((tab) => tab.df.fieldname === "details")?.wrapper;
		if (!$pane?.length) return;
		let ui = $pane.data("tjy-ingredient-basic");
		if (!ui) {
			const sections = {};
			for (const [key, fieldname] of Object.entries({
				profile: "overview", aliases: "aliases_section", buying: "purchasing", more: "advanced", code: "code",
			})) {
				const section = frm.layout.sections.find((entry) => entry.df.fieldname === `custom_tjy_ing_${fieldname}`);
				if (!section?.wrapper?.length) return;
				sections[key] = section;
			}
			ui = makeProfile(frm, $pane, sections);
		}

		const { doc } = frm;
		const code = doc.item_code || (frm.is_new() ? "" : doc.name);
		const name = doc.item_name?.trim() || (frm.is_new() ? "新建食材" : code);
		const status = doc[statusField] || "缺少数据";
		ui.$name.text(name);
		ui.$code.text(code || "自动生成");
		ui.$status.text(status).attr("data-state", states[status] || "missing");
		ui.$nutritionLink.prop("hidden", frm.layout.tabs.find((tab) => tab.df.fieldname === nutritionTab)?.is_hidden() !== false);
		ui.$details.prop("hidden", !ui.$details.find(".frappe-control:not(.hide-control)").length);

		const photo = doc[frm.meta.image_field] || "";
		ui.$image.attr("alt", name);
		if ((ui.$image.attr("src") || "") !== photo) {
			ui.$image.prop("hidden", true).attr("src", photo || null);
			ui.$emptyPhoto.prop("hidden", false);
		}
	}

	frappe.ui.form.on("Item", {
		async onload(frm) {
			const doc = frm.doc;
			if (!frm.is_new() || !doc.custom_tjy_standard_ingredient || doc.item_code?.trim()) return;
			const { message: code } = await frappe.call({
				method: "tongjianyun.ingredient_library.new_ingredient_code",
				type: "GET",
			});
			if (frm.doc === doc && !doc.item_code?.trim()) {
				// The native Item Code change event uses the code as a default Item Name.
				doc.item_code = code;
				frm.refresh_field("item_code");
				renderProfile(frm);
			}
		},
		async refresh(frm) {
			if (frm.doctype_layout?.name !== layoutName) return;

			const code = frm.fields_dict.item_code;
			code.df.reqd = 0;
			code.refresh();
			frm.fields_dict.custom_tjy_ingredient_aliases.$input?.attr("rows", 2).css("height", "auto");

			const doc = frm.doc;
			await frappe.require("/assets/tongjianyun/css/standard_ingredient_profile.css?v=profile-1.css");
			if (frm.doc === doc) renderProfile(frm);

			await frappe.require("/assets/tongjianyun/js/ingredient_nutrition.js?v=profile-status-1.js");
			if (frm.doc === doc && frm.doctype_layout?.name === layoutName) return frappe.tjy_ingredient_nutrition(frm);
		},
		item_name: renderProfile,
		image: renderProfile,
		custom_tjy_nutrition_status: renderProfile,
		item_code(frm) {
			const { doc } = frm;
			if (frm.is_new() && doc.custom_tjy_standard_ingredient && doc.item_code && doc.item_name === doc.item_code) {
				return frm.set_value("item_name", "");
			}
			renderProfile(frm);
		},
	});
})();
