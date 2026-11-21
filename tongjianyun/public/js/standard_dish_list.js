(() => {
	const layout = "标准菜品档案";
	const settings = (frappe.listview_settings.Item ??= {});
	const onload = settings.onload;
	settings.onload = function (list) {
		onload?.call(this, list);
		const getFormLink = list.get_form_link.bind(list);
		list.get_form_link = function (doc) {
			if (frappe.router.doctype_layout === layout) {
				return frappe.utils.get_form_link("Item", doc.name, false, null, { layout });
			}
			return getFormLink(doc);
		};
		// The native row handler only forwards the pathname, dropping the layout query.
		list.$result[0].addEventListener("click", (event) => {
			if (frappe.router.doctype_layout !== layout || event.ctrlKey || event.metaKey) return;
			if (event.target.closest(
				"a, button, input, [data-toggle='dropdown'], .filterable, .select-like, .file-select, .list-row-like"
			)) return;
			const row = event.target.closest(".list-row, .image-view-header, .file-header");
			const link = row?.querySelector(".list-subject a");
			if (!link) return;
			event.preventDefault();
			event.stopPropagation();
			frappe.set_route(link.pathname + link.search);
		}, true);
		const makeNew = list.make_new_doc.bind(list);
		list.make_new_doc = async function () {
			if (frappe.router.doctype_layout !== layout) {
				return makeNew();
			}
			const { message: options } = await frappe.call({
				method: "tongjianyun.dish_library.dish_options",
				type: "GET",
			});
			return frappe.model.with_doctype("Item", () => {
				const doc = frappe.model.get_new_doc("Item", null, null, true);
				doc.custom_tjy_standard_dish = 1;
				doc.item_code = options.item_code;
				doc.is_purchase_item = 0;
				doc.disabled = 0;
				if (options.default_unit) doc.stock_uom = options.default_unit;
				if (options.default_item_group) doc.item_group = options.default_item_group;
				frappe.route_options = { layout };
				return frappe.set_route("Form", "Item", doc.name);
			});
		};
	};
})();
