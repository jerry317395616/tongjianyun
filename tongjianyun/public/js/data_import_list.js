const data_import_list_settings = frappe.listview_settings["Data Import"] || {};

data_import_list_settings.formatters = {
	...(data_import_list_settings.formatters || {}),
	name(value, df, doc) {
		const match = value?.match(/^(.+?) Import on (.+)$/);
		if (!match) {
			return frappe.utils.escape_html(value || "");
		}

		const document_type = doc.reference_doctype || match[1];
		return frappe.utils.escape_html(
			__("{0} Import on {1}", [__(document_type), match[2]])
		);
	},
};

frappe.listview_settings["Data Import"] = data_import_list_settings;
