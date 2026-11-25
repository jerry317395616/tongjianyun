const ione_core_localize_student_heatmap = (root) => {
	root.querySelectorAll("svg text.domain-name, svg text.subdomain-name").forEach((label) => {
		const value = label.textContent.trim();
		const source = value.length === 3
			? value.charAt(0).toUpperCase() + value.slice(1).toLowerCase()
			: value;
		const translated = __(source, null, "Heatmap");
		if (translated !== source) {
			label.textContent = translated;
		}
	});
};

const ione_core_setup_student_heatmap_i18n = (frm) => {
	window.clearTimeout(frm.__ione_core_heatmap_i18n_timer);

	const attach = (attempt = 0) => {
		const root =
			frm.dashboard?.heatmap_area?.body?.[0] ||
			frm.$wrapper?.find(".form-heatmap")?.[0];

		if (root) {
			if (frm.__ione_core_heatmap_i18n_root !== root) {
				frm.__ione_core_heatmap_i18n_observer?.disconnect();
				frm.__ione_core_heatmap_i18n_root = root;
				frm.__ione_core_heatmap_i18n_observer = new MutationObserver(() => {
					ione_core_localize_student_heatmap(root);
				});
				frm.__ione_core_heatmap_i18n_observer.observe(root, {
					childList: true,
					characterData: true,
					subtree: true,
				});
			}

			ione_core_localize_student_heatmap(root);
			return;
		}

		if (attempt < 20) {
			frm.__ione_core_heatmap_i18n_timer = window.setTimeout(
				() => attach(attempt + 1),
				250
			);
		}
	};

	attach();
};

frappe.ui.form.on("Student", {
	refresh(frm) {
		ione_core_setup_student_heatmap_i18n(frm);
	},
});
