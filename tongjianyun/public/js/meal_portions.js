(() => {
	const stylesheet = "/assets/tongjianyun/css/weekly_menu_editor.css?v=meal-ingredient-quantities.css";
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
		let editing = false;
		let totals = [];
		let $netNotice;

		function changes() {
			return rows.flatMap((row) => {
				const { gross, net } = values.get(row.row);
				return Number(gross) === Number(row.standard_gross) && normalizedNet(net) === normalizedNet(row.standard_net)
					? [] : [{ row: row.row, gross, net }];
			});
		}

		function updateTotals() {
			const count = headcount();
			for (const { row, $cell } of totals) {
				const gross = Number(values.get(row.row).gross);
				const total = count == null || !Number.isFinite(gross) || gross <= 0 ? null : gross * count;
				const kg = total >= 1000 && ["g", "克"].includes(row.uom);
				$cell.text(total == null ? "—" : `${amount(kg ? total / 1000 : total)} ${kg ? "kg" : row.uom}`);
			}
			$netNotice?.text(rows.some((row) => !normalizedNet(values.get(row.row).net)) ? "待补可食净量" : "");
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
			$("<strong>").text("本餐食材用量").appendTo($view);
			const $table = $("<table>", { "aria-label": "本餐食材用量" })
				.appendTo($("<div>", { class: "tgy-portion-scroll" }).appendTo($view));
			const $heading = $("<tr>").appendTo($("<thead>").appendTo($table));
			for (const label of ["食材 / 单位", "标准每人毛重", "本餐每人毛重", "每人可食净量", "本餐毛重合计"]) {
				$("<th>", { scope: "col" }).text(label).appendTo($heading);
			}
			const $body = $("<tbody>").appendTo($table);
			totals = rows.map((row) => {
				const current = values.get(row.row);
				const $line = $("<tr>").appendTo($body);
				const $name = $("<th>", { scope: "row" }).text(row.name).appendTo($line);
				$("<small>").text(row.uom).appendTo($name);
				const $standard = $("<td>").text(amount(row.standard_gross)).appendTo($line);
				if (row.standard_net) $("<small>").text(`净 ${amount(row.standard_net)}`).appendTo($standard);
				const $gross = $("<td>").appendTo($line);
				const $net = $("<td>").appendTo($line);
				if (editing) {
					addInput($gross, row, "gross", "本餐每人毛重");
					addInput($net, row, "net", "每人可食净量");
				} else {
					$gross.text(amount(current.gross));
					$net.text(amount(current.net));
				}
				return { row, $cell: $("<td>").appendTo($line) };
			});
			$netNotice = $("<div>", { class: "tgy-portion-note", role: "status" }).appendTo($view);
			updateTotals();
			if (!editable) return;
			const $actions = $("<div>", { class: "tgy-portion-actions" }).appendTo($view);
			const $toggle = $("<button>", { type: "button", class: "btn btn-xs btn-default" })
				.text(editing ? "完成编辑" : "调整本餐食材用量").on("click", () => {
					editing = !editing;
					const $nextToggle = draw();
					(editing ? $host.find("input").first() : $nextToggle)?.trigger("focus");
				}).appendTo($actions);
			$("<button>", { type: "button", class: "btn btn-xs btn-default" }).text("恢复标准用量").on("click", () => {
				for (const row of rows) values.set(row.row, { gross: row.standard_gross, net: row.standard_net });
				onChange([]);
				draw()?.trigger("focus");
			}).appendTo($actions);
			return $toggle;
		}

		draw();
		return updateTotals;
	}

	window.tjyMealPortions = { stylesheet, load, render };
})();
