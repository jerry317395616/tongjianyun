(() => {
	const layout = "标准菜品";
	const settings = (frappe.listview_settings.BOM ??= {});
	const onload = settings.onload;
	settings.onload = function (list) {
		onload?.call(this, list);
		const getFormLink = list.get_form_link.bind(list);
		list.get_form_link = function (doc) {
			if (frappe.router.doctype_layout === layout) {
				return frappe.utils.get_form_link("BOM", doc.name, false, null, { layout });
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
		const make_new_doc = list.make_new_doc.bind(list);
		list.make_new_doc = function () {
			if (frappe.router.doctype_layout !== layout) {
				return make_new_doc();
			}
			return frappe.model.with_doctype("BOM", () => {
				const doc = frappe.model.get_new_doc("BOM", null, null, true);
				doc.custom_tjy_standard_recipe = 1;
				doc.quantity = 1;
				const item = list.filter_area?.get().find((filter) => filter[1] === "item" && filter[2] === "=");
				if (item) doc.item = item[3];
				frappe.route_options = { layout };
				return frappe.set_route("Form", "BOM", doc.name);
			});
		};
	};
})();
