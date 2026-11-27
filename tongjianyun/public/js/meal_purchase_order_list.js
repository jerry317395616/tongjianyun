(() => {
	const settings = (frappe.listview_settings["Purchase Order"] ||= {});
	const nativeLoad = settings.onload;
	const mealList = () => frappe.router.doctype_layout === frappe.tjyMealDesk.purchaseOrderLayout;

	settings.onload = function (list) {
		nativeLoad?.call(this, list);
		const getFilters = list.get_filters_for_args.bind(list);
		list.get_filters_for_args = () => {
			const filters = getFilters();
			if (mealList()) filters.push([list.doctype, "custom_meal_week", "is", "set"]);
			return filters;
		};

		const getSearchParams = list.get_search_params.bind(list);
		list.get_search_params = () => {
			const params = getSearchParams();
			if (mealList()) {
				params.delete("custom_meal_week", JSON.stringify(["is", "set"]));
				params.set("layout", frappe.tjyMealDesk.purchaseOrderLayout);
			}
			return params;
		};

		const getLink = list.get_form_link.bind(list);
		list.get_form_link = doc => mealList() ? frappe.tjyMealDesk.purchaseOrderLink(doc.name) : getLink(doc);
		list.$result[0].addEventListener("click", event => {
			if (!mealList() || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
			if (event.target.closest("a,button,input,label,[data-toggle=dropdown],.filterable,.select-like,.file-select,.list-row-like")) return;
			const link = event.target.closest(".list-row")?.querySelector(".list-subject a");
			if (!link) return;
			event.preventDefault();
			event.stopPropagation();
			frappe.set_route(link.pathname + link.search);
		}, true);

		const makeNew = list.make_new_doc.bind(list);
		list.make_new_doc = () => {
			if (!mealList()) return makeNew();
			frappe.prompt([{ fieldname: "week", label: "来源周食谱", fieldtype: "Link", options: "Meal Planning Week",
				reqd: 1, get_query: () => ({ filters: { docstatus: 1 } }) }],
			({ week }) => frappe.set_route("Form", "Meal Planning Week", week), "选择采购来源", "打开周食谱");
		};

		const setupColumns = list.setup_columns.bind(list);
		list.setup_columns = fields => {
			if (!mealList() || fields?.length) return setupColumns(fields);
			return setupColumns([...new Set([list.meta.title_field || "name", "name", "custom_meal_week", "schedule_date", "grand_total", "status_field"])]
				.map(fieldname => ({ fieldname })));
		};
		const beforeRefresh = list.before_refresh.bind(list);
		list.before_refresh = async () => {
			await beforeRefresh();
			const active = mealList();
			if (list._tjyMealOrderList === active) return;
			if (active || list._tjyMealOrderList) {
				list.page.set_title(active ? frappe.tjyMealDesk.purchaseOrderLayout : __(list.doctype));
				await list.setup_columns();
			}
			list._tjyMealOrderList = active;
		};
	};
})();
