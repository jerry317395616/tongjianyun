(() => {
	const layout = "标准菜品档案";
	const settings = (frappe.listview_settings.Item ??= {});
	const onload = settings.onload;
	settings.onload = function (list) {
		onload?.call(this, list);
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
				frappe.route_options = { layout };
				return frappe.set_route("Form", "Item", doc.name);
			});
		};
	};
})();
