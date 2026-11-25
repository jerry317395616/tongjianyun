const localize_user_timezone_options = (options = []) =>
	options.map((option) => {
		if (typeof option === "string") {
			return { label: __(option), value: option };
		}

		const value = option.value ?? option.label;
		return {
			...option,
			label: __(option.label ?? value),
			value,
		};
	});

const refresh_user_timezone_display = (frm) => {
	const control = frm.fields_dict.time_zone;
	const timezone = frm.doc.time_zone || control?.value || control?.$input?.val();
	const ready =
		timezone &&
		!control.$input?.is(":focus") &&
		typeof control.set_formatted_input === "function";

	if (ready) {
		control.set_formatted_input(timezone);
	}

	return ready;
};

const setup_user_timezone_localization = (frm) => {
	const control = frm.fields_dict.time_zone;
	if (!control || typeof control.set_data !== "function") {
		return;
	}

	if (!control.__ione_core_original_set_data) {
		const original_set_data = control.set_data.bind(control);
		control.__ione_core_original_set_data = original_set_data;
		control.set_data = (options) => {
			const result = original_set_data(localize_user_timezone_options(options));
			window.setTimeout(() => refresh_user_timezone_display(frm), 0);
			return result;
		};
	}

	const timezone = frm.doc.time_zone || control.value || control.$input?.val();
	const timezones = frappe.all_timezones?.length
		? frappe.all_timezones
		: timezone
			? [timezone]
			: [];
	if (timezones.length) {
		control.set_data(timezones);
	}

	window.clearTimeout(frm.__ione_core_timezone_i18n_timer);

	const apply = (attempt = 0) => {
		if (refresh_user_timezone_display(frm)) {
			return;
		}

		if (attempt < 20) {
			frm.__ione_core_timezone_i18n_timer = window.setTimeout(
				() => apply(attempt + 1),
				250
			);
		}
	};

	apply();
};

frappe.ui.form.on("User", {
	before_load(frm) {
		setup_user_timezone_localization(frm);
	},
	refresh(frm) {
		setup_user_timezone_localization(frm);
	},
	time_zone(frm) {
		setup_user_timezone_localization(frm);
	},
});
