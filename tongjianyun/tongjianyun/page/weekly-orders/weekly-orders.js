frappe.pages['weekly-purchase-orders'].on_page_load = function (wrapper) {
  const page = frappe.ui.make_app_page({ parent: wrapper, title: '一周采购订单', single_column: true });
  const body = $(wrapper).find('.layout-main-section').html('<div class="tjy-weekly-orders"><p>正在加载本周订单…</p></div>');
  const call = method => frappe.call({ method: `tongjianyun.recipe_procurement.${method}` });
  async function render() {
    const result = await call('weekly_purchase_orders'); const rows = result.message.orders || [];
    const html = rows.length ? rows.map(r => `<label class="list-row"><input type="checkbox" value="${frappe.utils.escape_html(r.name)}" ${r.docstatus ? 'disabled' : ''}> <b>${frappe.utils.escape_html(r.transaction_date)}</b>　${frappe.utils.escape_html(r.supplier_name || r.supplier)}　${r.status_label}　<a href="/app/purchase-order/${encodeURIComponent(r.name)}">${frappe.utils.escape_html(r.name)}</a></label>`).join('') : '<p>本周暂无采购订单。</p>';
    body.find('.tjy-weekly-orders').html(`<div class="mb-3"><button class="btn btn-primary submit-selected">提交选中订单</button> <button class="btn btn-default refresh">刷新</button></div>${html}`);
    body.find('.submit-selected').on('click', async () => { const names = body.find('input:checked').map((_, el) => el.value).get(); if (!names.length) return frappe.msgprint('请选择草稿订单。'); await frappe.call({method:'tongjianyun.recipe_procurement.submit_weekly_purchase_orders', args:{names: JSON.stringify(names)}, freeze:true, freeze_message:'正在提交订单…'}); frappe.show_alert({message:'选中订单已提交', indicator:'green'}); render(); });
    body.find('.refresh').on('click', render);
  }
  render();
};
