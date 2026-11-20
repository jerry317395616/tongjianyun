(() => {
	const settings = (frappe.listview_settings.BOM ??= {});
	const onload = settings.onload;
	settings.onload = function (list) {
		onload?.call(this, list);
		const make_new_doc = list.make_new_doc.bind(list);
		list.make_new_doc = function () {
			if (frappe.router.doctype_layout !== "标准菜品") {
				return make_new_doc();
			}
			return frappe.new_doc("BOM", { layout: "标准菜品" }, (doc) => {
				doc.custom_tjy_standard_recipe = 1;
				doc.quantity = 1;
			});
		};
	};
})();
