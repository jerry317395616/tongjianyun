(() => {
	const type = "Tongjianyun Canteen Receiving";
	const icon = name => frappe.utils.icon(name, "sm");
	const canScan = list => list.can_create && !frappe.boot.read_only;

	async function receive(list, code) {
		code = String(code || "").trim();
		if (!code || list._receivingScanBusy || !canScan(list)) return;
		list._receivingScanBusy = true;
		try {
			const {message} = await frappe.call({
				method:"tongjianyun.canteen_ops.purchasing.receiving_from_code", type:"POST",
				args:{code}, freeze:true, freeze_message:"正在读取随货批次"
			});
			if (message) await frappe.set_route("Form", type, message);
		} finally {
			list._receivingScanBusy = false;
		}
	}
	function enterCode(list) {
		frappe.prompt([{fieldname:"code", fieldtype:"Data", label:"随货二维码内容",
			description:"粘贴二维码中的完整随货码。", reqd:1}],
			values => receive(list, values.code), "录入随货码", "打开验收单");
	}
	function scan(list) {
		if (!navigator.mediaDevices?.getUserMedia) return enterCode(list);
		new frappe.ui.Scanner({dialog:true, multiple:false, on_scan: result => {
			if (result?.decodedText) receive(list, result.decodedText);
		}});
	}
	function draw(list) {
		const main = list.page.main;
		let header = main.children(".tjy-receive-entry");
		if (!header.length) header = $('<section class="tjy-receive-entry" aria-label="到货验收"></section>').prependTo(main);
		const create = canScan(list);
		header.html(`<div class="tr-entry-hero"><div class="tr-entry-copy">
			<h2>${create ? "食材到货，扫码验收" : "食材验收记录"}</h2>
			<p>核对随货批次，记录实收与拒收数量。复核提交后，合格食材入库。</p>
			${create ? `<div class="tr-actions"><button type="button" class="tr-primary" data-start="scan">${icon("scan")} 扫码验收</button>
			<button type="button" class="tr-alternate" data-start="code">录入随货码</button></div>` : ""}
			</div></div>
			<div class="tr-flow" aria-label="验收流程">
			<div>${icon("scan")}<span><strong>扫随货码</strong><small>一次带入整批食材</small></span></div>
			<div>${icon("clipboard")}<span><strong>核对实物</strong><small>登记数量、票证与照片</small></span></div>
			<div>${icon("package")}<span><strong>复核入库</strong><small>按合格数量生成收货单</small></span></div></div>
			<h3 class="tr-list-title">验收记录</h3>`);
		header.off(".receiptEntry").on("click.receiptEntry","[data-start]", e => {
			if (canScan(list)) e.currentTarget.dataset.start === "scan" ? scan(list) : enterCode(list);
		});
	}
	frappe.listview_settings[type] = {
		onload(list) {
			if (canScan(list)) {
				list.make_new_doc = () => scan(list);
				list.set_primary_action = () => list.page.set_primary_action("扫码验收", () => scan(list), "scan");
				list.set_primary_action();
			}
			draw(list);
		},
		refresh: draw,
	};
})();
