const format_role_name = (value) => frappe.utils.escape_html(__(value || ""));

const current_role_settings = frappe.listview_settings["Role"] || {};
const current_custom_filters = current_role_settings.custom_filter_configs;

const get_current_custom_filters = async () => {
	const configs =
		typeof current_custom_filters === "function"
			? await current_custom_filters()
			: current_custom_filters || [];

	return (configs || []).filter((config) => config.fieldname !== "name");
};

frappe.listview_settings["Role"] = {
	...current_role_settings,
	hide_name_filter: true,
	custom_filter_configs: async () => [
		{
			fieldname: "name",
			fieldtype: "Link",
			options: "Role",
			label: __("ID"),
			condition: "=",
			only_select: true,
			is_filter: 1,
		},
		...(await get_current_custom_filters()),
	],
	formatters: {
		...(current_role_settings.formatters || {}),
		name: format_role_name,
		role_name: format_role_name,
	},
};
