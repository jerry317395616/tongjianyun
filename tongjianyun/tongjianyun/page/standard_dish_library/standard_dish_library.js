frappe.pages["standard-dish-library"].on_page_show = () => {
	frappe.route_options = { layout: "标准菜品档案", custom_tjy_standard_dish: 1 };
	return frappe.set_route("List", "Item");
};
