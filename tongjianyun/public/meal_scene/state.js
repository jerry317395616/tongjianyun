// One ordered capability index: geometry, labels, search, keyboard and fallback.
export const VERSION='meal-flow-20260923-1';
export const STEPS=Object.freeze([
  {id:'recipe',number:1,title:'食谱与营养',subtitle:'编制周食谱 · 核对供给',color:'#459aca',point:[-10,3.65,-5.8],cap:'recipe'},
  {id:'purchase',number:2,title:'食材采购',subtitle:'核人数 → 预览 → 需求草稿',color:'#d19a50',point:[-3.35,3.65,-5.8],cap:'order'},
  {id:'receipt',number:3,title:'到货与入库',subtitle:'按原收货单核对实际到货',color:'#4caa87',point:[3.35,3.65,-5.8],cap:'receipt'},
  {id:'stock',number:4,title:'仓储管理',subtitle:'当前账面库存 · 按仓库查看',color:'#528fb2',point:[10,3.65,-5.8],cap:'stock'},
  {id:'kitchen',number:5,title:'厨房备餐',subtitle:'食谱配方与带量参考',color:'#d4a35c',point:[10,3.55,4.5],cap:'recipe'},
  {id:'dispatch',number:6,title:'班级配餐',subtitle:'预计人数 · 非配送签收',color:'#579fac',point:[3.35,3.55,4.5],cap:'meals'},
  {id:'dining',number:7,title:'实际用餐确认',subtitle:'预计 ≠ 实际 · 逐生核对',color:'#58a982',point:[-3.35,3.55,4.5],cap:'meals'},
  {id:'trace',number:8,title:'追溯与报表',subtitle:'业务单据关联 · 分清未接入',color:'#9383bc',point:[-10,3.55,4.5],cap:null},
]);
export const MEALS=[['breakfast','早餐'],['morning_snack','早点'],['lunch','午餐'],['afternoon_snack','午点'],['dinner','晚餐']];
export const SLOTS={breakfast:'breakfast',morning_snack:'morningSnack',lunch:'lunch',afternoon_snack:'snack',dinner:'dinner'};
export const stepFor=id=>STEPS.find(s=>s.id===id)||null;
export const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const number=v=>v===null||v===undefined?'待核对':Number.isFinite(Number(v))?new Intl.NumberFormat('zh-CN',{maximumFractionDigits:3}).format(Number(v)):'—';
export function stepBadge(id,data){
  if(!data)return '正在读取';
  const s=stepFor(id);if(s?.cap&&!data.capabilities[s.cap]&&!(id==='purchase'&&data.capabilities.procurement))return '按权限开放';
  if(id==='recipe')return data.recipes.rows.length?`${data.recipes.rows.length}${data.recipes.has_more?'＋':''} 份覆盖所选日期`:'该日期暂无食谱';
  if(id==='purchase')return `${data.orders.rows.length}${data.orders.has_more?'＋':''} 条近七日订单`;
  if(id==='receipt')return `${data.receipts.rows.length}${data.receipts.has_more?'＋':''} 条近七日收货单`;
  if(id==='stock')return '查看当前账面数量';
  if(id==='kitchen')return '配方参考 · 执行未接入';
  if(id==='dispatch')return '配餐参考 · 签收未接入';
  if(id==='dining'){const c=data.plans.summary;return c?`${c.confirmed_groups} / ${c.visible_groups} 可见班已确认`:'暂无可见确认数据';}
  return '现有业务关联与分析';
}
export function factCards(data){
  const c=data.plans.summary;
  return [
    {label:'可见班级 · 已保存预计',value:c?`${c.planned_groups} / ${c.visible_groups}`:'—',note:'未保存的班级不按零人处理'},
    {label:'所选餐次 · 预计人数',value:c?number(c.expected):'—',note:'仅完整可见计划可汇总'},
    {label:'所选餐次 · 已确认实际',value:c?number(c.actual):'—',note:'未全部确认时不冒充实际总数'},
  ];
}
// Strict same-origin professional modules. No dynamic URL or "next" provided by server data.
const DESK={recipe:'/desk/tongjianyun-recipe-workbench',nutrition:'/desk/weekly-recipe-nutrition-sheet',
  orders:'/desk/weekly-orders',requests:'/desk/material-request',receipts:'/desk/purchase-receipt',
  stock:'/desk/query-report/Stock%20Balance',items:'/desk/item',warehouses:'/desk/warehouse',suppliers:'/desk/supplier',
  adjustments:'/desk/tongjianyun-daily-meal-adjustment'};
export function professionalRoute(key,name=''){
  const roots={order:'/desk/purchase-order',receipt:'/desk/purchase-receipt',request:'/desk/material-request'};
  if(roots[key])return name?roots[key]+'/'+encodeURIComponent(name):null;
  return DESK[key]||null;
}
export function mealDraft(row){
  return {student:row.student,student_name:row.student_name,...Object.fromEntries(MEALS.map(([m])=>[
    m,row[m]==='已就餐'?'就餐':row[m]==='未就餐'?'不就餐':row[m]==='不供餐'?'不供餐':row[m+'_expected']?'就餐':'不就餐'
  ]))};
}
export function draftTotals(rows){return Object.fromEntries(MEALS.map(([m])=>[m,rows.filter(r=>r[m]==='就餐').length]));}
