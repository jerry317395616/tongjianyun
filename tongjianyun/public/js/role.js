const localize_role_sidebar_title = (frm) => {
	if (!frm.doc?.name || !frm.sidebar?.sidebar) {
		return;
	}

	const translated_name = __(frm.get_title());
	frm.sidebar.sidebar
		.find(".sidebar-meta-details .form-title-text > span")
		.text(translated_name);
};

const localize_role_document_permissions = (frm) => {
	const documents_tab = frm.role_form?.tabs?.document_tab;
	if (!documents_tab || documents_tab.__ione_core_localized) {
		return;
	}

	const get_columns = documents_tab.columns.bind(documents_tab);
	documents_tab.columns = () =>
		get_columns().map((column) => {
			if (column.fieldname === "parent") {
				return { ...column, fieldname: "parent_label" };
			}
			if (column.fieldname === "source") {
				return { ...column, fieldname: "source_label" };
			}
			return column;
		});

	const transform_permissions = documents_tab.transform.bind(documents_tab);
	documents_tab.transform = (permissions) =>
		transform_permissions(permissions).map((permission) => ({
			...permission,
			parent_label: __(permission.parent || ""),
			source_label: __(permission.source || ""),
		}));

	documents_tab.__ione_core_localized = true;
};

frappe.ui.form.on("Role", {
	refresh(frm) {
		localize_role_sidebar_title(frm);
		localize_role_document_permissions(frm);
	},
});
