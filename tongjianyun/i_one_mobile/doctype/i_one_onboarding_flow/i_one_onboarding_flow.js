function apply_step_order(frm, ordered) {
	let changed = false;

	ordered.forEach((row, index) => {
		const position = index + 1;
		if (row.idx !== position || Number(row.sequence) !== position) {
			changed = true;
		}
		row.idx = position;
		row.sequence = position;
	});

	if (!changed && ordered.every((row, index) => frm.doc.steps[index]?.name === row.name)) {
		return;
	}

	frm.doc.steps = ordered;
	frm.dirty();
	frm.refresh_field("steps");
}

function normalize_steps(frm) {
	const rows = [...(frm.doc.steps || [])];
	rows.sort((left, right) => {
		const leftPosition = Number(left.sequence) || rows.length + 1;
		const rightPosition = Number(right.sequence) || rows.length + 1;
		return leftPosition - rightPosition || (left.idx || 0) - (right.idx || 0);
	});
	apply_step_order(frm, rows);
}

function insert_step_at_position(frm, cdn) {
	if (frm.__reordering_onboarding_steps) {
		return;
	}

	const rows = [...(frm.doc.steps || [])];
	const moved = rows.find(row => row.name === cdn);
	if (!moved) {
		return;
	}

	const requested = Number.parseInt(moved.sequence, 10);
	const target = Math.min(Math.max(requested || rows.length, 1), rows.length);
	const ordered = rows.filter(row => row.name !== cdn);
	ordered.splice(target - 1, 0, moved);

	frm.__reordering_onboarding_steps = true;
	try {
		apply_step_order(frm, ordered);
	} finally {
		frm.__reordering_onboarding_steps = false;
	}
}

frappe.ui.form.on("I-ONE Onboarding Flow", {
	onload_post_render(frm) {
		normalize_steps(frm);
	},
	validate(frm) {
		normalize_steps(frm);
	},
});

frappe.ui.form.on("I-ONE Onboarding Step", {
	steps_add(frm, cdt, cdn) {
		const row = frappe.get_doc(cdt, cdn);
		row.sequence = (frm.doc.steps || []).length;
		frm.refresh_field("steps");
	},
	sequence(frm, cdt, cdn) {
		insert_step_at_position(frm, cdn);
	},
});
