frappe.pages['weekly-orders'].on_page_load = function(wrapper) {
  const page = frappe.ui.make_app_page({parent: wrapper, title: '一周采购订单', single_column: true});
  const root = $('<div style="padding:24px;max-width:1400px;margin:auto"></div>').appendTo(page.main);
  const esc = value => frappe.utils.escape_html(String(value ?? ''));
  const controls = {};
  root.append('<h3>食谱采购订单</h3><p class="text-muted">按食谱日期查看每天采购。当前指今天及以后；历史补录仍按原食谱日期归类。</p>');
  const filters = $('<div style="display:flex;gap:12px;flex-wrap:wrap;align-items:end"></div>').appendTo(root);
  for (const [name, label, type, options] of [['scope','查看范围','Select','当前\n历史\n全部'],['start','食谱开始日期','Date'],['end','食谱结束日期','Date'],['status','订单状态','Select','全部\n草稿\n已提交\n已取消'],['keyword','订单号 / 供应商','Data']]) {
    const holder = $('<div style="min-width:170px;flex:1"></div>').appendTo(filters);
    controls[name] = frappe.ui.form.make_control({parent:holder,df:{fieldname:name,label,fieldtype:type,options},render_input:true});
  }
  controls.scope.set_value('全部'); controls.status.set_value('全部');
  const actions = $('<div style="display:flex;gap:8px;margin:12px 0"></div>').appendTo(root);
  const search = $('<button class="btn btn-primary">检索</button>').appendTo(actions);
  const reset = $('<button class="btn btn-default">重置</button>').appendTo(actions);
  const submit = $('<button class="btn btn-default">提交选中草稿</button>').appendTo(actions);
  const list = $('<div></div>').appendTo(root);
  const pager = $('<div style="display:flex;gap:12px;margin-top:16px"></div>').appendTo(root);
  let offset=0, generation=0;
  async function load() {
    const token=++generation; list.html('<p>正在加载采购订单…</p>'); pager.empty();
    try {
      const response=await frappe.call({method:'tongjianyun.purchase_browser.search',args:{scope:({'当前':'current','历史':'history','全部':'all'})[controls.scope.get_value()] || 'all',start_date:controls.start.get_value(),end_date:controls.end.get_value(),status:({'草稿':'0','已提交':'1','已取消':'2'})[controls.status.get_value()] || '',keyword:controls.keyword.get_value(),offset}});
      if(token!==generation)return;
      const rows=response.message.orders; list.empty();
      if(!rows.length)list.html('<div class="text-muted" style="padding:40px;text-align:center">没有符合条件的食谱采购订单，请调整筛选条件。</div>');
      let date='';
      rows.forEach(r=>{
        if(date!==r.recipe_date){date=r.recipe_date;list.append(`<h4 style="margin-top:24px">${esc(date)} · 食谱采购</h4>`);}
        const card=$(`<section style="border:1px solid var(--border-color);border-radius:10px;padding:18px;margin:10px 0;background:var(--card-bg)"><div style="display:flex;gap:14px;align-items:center;flex-wrap:wrap"><input type="checkbox" class="order-check" value="${esc(r.name)}" ${r.docstatus!==0?'disabled':''}><strong>${esc(r.supplier_name||r.supplier)}</strong><span class="indicator-pill ${['orange','green','gray'][r.docstatus]}">${['草稿','已提交','已取消'][r.docstatus]}</span><a href="/desk/purchase-order/${encodeURIComponent(r.name)}">${esc(r.name)}</a><span>${esc(r.currency)} ${esc(r.grand_total)}</span><button class="btn btn-xs btn-default items">查看食材明细</button></div><small class="text-muted">订单日期：${esc(r.transaction_date)} · 食谱日期：${esc(r.recipe_date)}</small><div class="detail" style="margin-top:12px"></div></section>`).appendTo(list);
        card.find('.items').on('click',async function(){
          const box=card.find('.detail'); if(box.children().length){box.toggle();return;}
          $(this).prop('disabled',true);
          try{const data=await frappe.call({method:'tongjianyun.purchase_browser.details',args:{name:r.name}});box.html('<div style="overflow:auto"><table class="table table-bordered"><thead><tr><th>食材名称</th><th>数量</th><th>单位</th><th>单价</th><th>金额</th></tr></thead><tbody>'+data.message.items.map(i=>`<tr><td>${esc(i.item_name)}</td><td>${esc(i.qty)}</td><td>${esc(i.uom)}</td><td>${esc(i.rate)}</td><td>${esc(i.amount)}</td></tr>`).join('')+'</tbody></table></div>');}finally{$(this).prop('disabled',false);}
        });
      });
      if(offset>0)$('<button class="btn btn-default">上一页</button>').appendTo(pager).on('click',()=>{offset-=20;load();});
      pager.append(`<span>第 ${offset/20+1} 页 · 本页 ${rows.length} 张</span>`);
      if(response.message.has_more)$('<button class="btn btn-default">下一页</button>').appendTo(pager).on('click',()=>{offset+=20;load();});
    }catch(error){if(token===generation)list.html('<p class="text-danger">加载失败，请调整条件或点击检索重试。</p>');}
  }
  search.on('click',()=>{offset=0;load();});
  reset.on('click',()=>{Object.values(controls).forEach(c=>c.set_value(''));controls.scope.set_value('全部');controls.status.set_value('全部');offset=0;load();});
  submit.on('click',()=>{const names=list.find('.order-check:checked').map((_,e)=>e.value).get();if(!names.length)return frappe.msgprint('请选择草稿订单。');if(names.length>7)return frappe.msgprint('每次最多提交 7 张订单。');frappe.confirm(`确认提交选中的 ${names.length} 张采购订单？`,async()=>{submit.prop('disabled',true);try{await frappe.call({method:'tongjianyun.recipe_procurement.submit_weekly_purchase_orders',args:{names:JSON.stringify(names)},freeze:true});await load();}finally{submit.prop('disabled',false);}});});
  load();
};
