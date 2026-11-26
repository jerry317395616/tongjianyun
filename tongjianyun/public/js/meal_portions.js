(() => {
	const stylesheet = "/assets/tongjianyun/css/weekly_menu_editor.css?v=meal-picker-portion-editor.css";
	const decimal = new Intl.NumberFormat("zh-CN", { useGrouping: false, maximumFractionDigits: 9 });
	const amount = (value) => value == null || value === "" || !Number.isFinite(Number(value))
		? "—" : decimal.format(Number(value));
	const normalizedNet = (value) => value == null || Number(value) === 0 ? null : Number(value);

	async function load(args) {
		const response = await frappe.call({ method: "tongjianyun.meal_portions.details", args, type: "GET" });
		if (response.exc || !response.message) throw new Error("食材用量读取失败。");
		return response.message;
	}

	function render($host, data, pending, headcount, onChange) {
		const rows = data.rows;
		if (!rows.length) {
			$host.text("暂无可查看的食材用量。");
			return;
		}
		const editable = data.adjustable && Boolean(onChange);
		const values = new Map(rows.map((row) => [row.row, {
			gross: pending === undefined ? row.gross : row.standard_gross,
			net: pending === undefined ? row.net : row.standard_net,
		}]));
		for (const change of pending || []) values.set(change.row, { gross: change.gross, net: change.net });
		const units = new Set(rows.map((row) => row.uom === "g" ? "克" : row.uom));
		const unit = units.size === 1 ? units.values().next().value : "";
		let showDetails = false;
		let totals = [];
		let $totalHeading;

		function changes() {
			return rows.flatMap((row) => {
				const { gross, net } = values.get(row.row);
				return Number(gross) === Number(row.standard_gross) && normalizedNet(net) === normalizedNet(row.standard_net)
					? [] : [{ row: row.row, gross, net }];
			});
		}

		function updateTotals() {
			const count = headcount();
			$totalHeading.text(count == null ? "本餐合计" : `${count} 人合计`);
			for (const { row, $cell } of totals) {
				const gross = Number(values.get(row.row).gross);
				const total = count == null || !Number.isFinite(gross) || gross <= 0 ? null : gross * count;
				const kg = total >= 1000 && ["g", "克"].includes(row.uom);
				$cell.text(total == null ? "—" : `${amount(kg ? total / 1000 : total)} ${kg ? "kg" : row.uom}`);
			}
		}

		function addInput($cell, row, field, label) {
			const current = values.get(row.row);
			$("<input>", { class: "form-control input-xs", type: "number", step: "any", min: 0,
				"aria-label": `${row.name} ${label}（${row.uom}）` })
				.val(current[field] ?? "").on("input", function () {
					current[field] = this.validity.badInput ? "无效" : this.value;
					onChange(changes());
					updateTotals();
				}).appendTo($cell);
		}

		function draw() {
			$host.empty();
			const $view = $("<div>", { class: "tgy-meal-portions" }).appendTo($host);
			$("<h5>").text("本餐食材用量").appendTo($view);
			const $table = $("<table>", { class: showDetails ? "tgy-portion-expanded" : "tgy-portion-compact", "aria-label": "本餐食材用量" })
				.appendTo($("<div>", { class: "tgy-portion-scroll" }).appendTo($view));
			const $heading = $("<tr>").appendTo($("<thead>").appendTo($table));
			const columns = ["食材", unit ? `每人毛重（${unit}）` : "每人毛重"];
			if (showDetails) columns.push("标准每人毛重", "每人可食净量");
			for (const label of columns) {
				$("<th>", { scope: "col" }).text(label).appendTo($heading);
			}
			$totalHeading = $("<th>", { scope: "col" }).appendTo($heading);
			const $body = $("<tbody>").appendTo($table);
			totals = rows.map((row) => {
				const current = values.get(row.row);
				const $line = $("<tr>").appendTo($body);
				const $name = $("<th>", { scope: "row" }).text(row.name).appendTo($line);
				if (!unit) $("<small>").text(row.uom).appendTo($name);
				const $gross = $("<td>").appendTo($line);
				if (editable) addInput($gross, row, "gross", "本餐每人毛重");
				else $gross.text(amount(current.gross));
				if (showDetails) {
					const $standard = $("<td>").text(amount(row.standard_gross)).appendTo($line);
					if (row.standard_net) $("<small>").text(`净 ${amount(row.standard_net)}`).appendTo($standard);
					const $net = $("<td>").appendTo($line);
					if (editable) addInput($net, row, "net", "每人可食净量");
					else $net.text(amount(current.net));
				}
				return { row, $cell: $("<td>").appendTo($line) };
			});
			updateTotals();
			const $actions = $("<div>", { class: "tgy-portion-actions" }).appendTo($view);
			let $restore;
			if (editable) {
				$restore = $("<button>", { type: "button", class: "tgy-portion-link" }).text("恢复标准用量").on("click", () => {
					for (const row of rows) values.set(row.row, { gross: row.standard_gross, net: row.standard_net });
					onChange([]);
					draw().restore.trigger("focus");
				}).appendTo($actions);
			}
			const $more = $("<button>", { type: "button", class: "tgy-portion-link tgy-portion-more", "aria-expanded": String(showDetails) })
				.text(showDetails ? "收起标准用量与净量" : "标准用量与净量").on("click", () => {
					showDetails = !showDetails;
					draw().more.trigger("focus");
				}).appendTo($actions);
			return { restore: $restore, more: $more };
		}

		draw();
		return updateTotals;
	}

	window.tjyMealPortions = { stylesheet, load, render };
})();
