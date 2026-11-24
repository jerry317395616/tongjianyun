/* Frappe supplies root_element inside this Workspace block. */
(function mealHome(){
"use strict";
const root = root_element.querySelector(".tjy-food-home");
// Frappe's default workspace width is 900px. Scope the wider canvas to this mounted block.
root_element.host.dataset.tjyMealHome = "1";
if (!document.getElementById("tjy-meal-home-canvas")) {
  const sheet=document.createElement("style");
  sheet.id="tjy-meal-home-canvas";
  sheet.textContent="#page-Workspaces .layout-main:has([data-tjy-meal-home]){width:100%;max-width:1620px} #page-Workspaces .custom-block-widget-box:has([data-tjy-meal-home]){background:transparent;box-shadow:none}";
  document.head.append(sheet);
}
const pref = `tjy-meal-home/${frappe.session.user}`;
const icons = {
  school:'<path d="m3 9 9-6 9 6M5 10v10h14V10M10 20v-5h4v5M9 10h.01M15 10h.01"/>',
  kitchen:'<path d="M4 15a8 8 0 0 1 16 0M2.5 17h19M5 20h14M12 5V3"/>',
  calendar:'<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M7.5 3v4M16.5 3v4M4 10h16"/>',
  spoon:'<path d="M5 3v6a3 3 0 0 0 6 0V3M8 3v18M18 3c-3 3-4 7-3 10h3m0-10v18"/>',
  checklist:'<path d="M9 4H6a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2h-3"/><rect x="9" y="2.5" width="6" height="4" rx="1.5"/><path d="m8 14 2.5 2.5 5.5-6"/>',
  arrow:'<path d="M4 12h15m-5-5 5 5-5 5"/>', chevron:'<path d="m9 5 7 7-7 7"/>', down:'<path d="m6 9 6 6 6-6"/>',
  refresh:'<path d="M20 10a8 8 0 1 0 0 5M20 4v6h-6"/>',
  check:'<path d="m5 12 4.5 4.5L19 7"/>', clock:'<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3 2"/>',
  sunrise:'<path d="M3 17h18M6 14a6 6 0 0 1 12 0M12 3v3M3 9l2 1M21 9l-2 1M5 20h14"/>',
  apple:'<path d="M12 7c-3-3-8-1-8 4 0 4 3 10 6 9l2-.6 2 .6c3 1 6-5 6-9 0-5-5-7-8-4Zm0 0c0-2 1-4 4-5"/>',
  sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l2 2m10 10 2 2M5 19l2-2M17 7l2-2"/>',
  cup:'<path d="M4 8h13v5a6 6 0 0 1-6 6H10a6 6 0 0 1-6-6Zm13 1h2a2.5 2.5 0 1 1-2 4M3 21h16M8 3v2m4-2v2"/>',
  moon:'<path d="M20.5 14a8.6 8.6 0 0 1-10.7-11A9.1 9.1 0 1 0 20.5 14Z"/>'
};
const slotIcons = {"早餐":"sunrise","早点":"apple","午餐":"sun","午点":"cup","晚餐":"moon"};
const icon = key => `<svg class="mh-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[key] || ""}</svg>`;
const esc = value => frappe.utils.escape_html(String(value ?? ""));
const dayLabels = ["周一","周二","周三","周四","周五","周六","周日"];
const dateLabel = day => day ? `${Number(day.slice(5,7))}月${Number(day.slice(8,10))}日` : "";
const stateTone = state => ({"已确认":"good","已日结":"good","已接收":"good","已确认零供餐":"good","供餐中":"current","已编排":"planned","待交接":"amber","待确认":"amber","待编排":"amber","待核对":"risk","已拒收":"risk","部分拒收":"risk"})[state] || "quiet";
const pill = state => `<span class="mh-pill mh-${stateTone(state)}"><i></i>${esc(state)}</span>`;
let model, requestId=0, expanded=false, actions=[];
function actionButton(action, style="mh-link", prefix="",suffix="") {
  if (!action) return '<span class="mh-dash">—</span>';
  const id=actions.push(action)-1;
  return `<button type="button" class="${style}" data-action="${id}">${prefix}${esc(action.label)}${suffix}</button>`;
}
function option(v,label,current) {
  return `<option value="${esc(v)}"${current===v ? " selected" : ""}>${esc(label)}</option>`;
}
function filters() {
  const companies=[...new Set(model.sites.map(s=>s.company))];
  const selector=(key,label,ico,html)=>`<label class="mh-control">${icon(ico)}<select data-field="${key}" aria-label="${label}">${html}</select>${icon("down")}</label>`;
  return `<div class="mh-toolbar">${selector("company","选择园所","school",companies.map(c=>option(c,c,model.company)).join(""))}
    ${selector("canteen","选择食堂","kitchen",model.sites.filter(s=>s.company===model.company).map(s=>option(s.name,s.canteen_name,model.canteen)).join(""))}
    <div class="mh-date-tools"><label class="mh-control mh-date">${icon("calendar")}<span>${esc(model.date.slice(0,4))}年${dateLabel(model.date)}　${dayLabels[model.days.findIndex(d=>d.date===model.date)]||""}</span><input type="date" data-field="date" aria-label="供餐日期" value="${esc(model.date)}"></label>
    <button type="button" class="mh-today" data-cmd="today">今天</button></div></div>`;
}
function meals() {
  const rows=model.rows.map(r=>{
    const stopped=r.status==="已停供";
    const value=(n,pending=false)=>stopped||n==null ? `<span class="mh-dash">${!stopped&&pending ? "待确认":"—"}</span>` : esc(n);
    return `<tr class="${stopped?"mh-stopped":""}"><th scope="row"><span class="mh-slot">${icon(slotIcons[r.slot])}${esc(r.slot)}</span></th>
      <td class="mh-dish">${esc(r.menu || (r.status==="未编排"?"—":"尚未选菜"))}</td>${model.external ? "" : `<td class="mh-num" data-label="计划人数">${value(r.planned)}</td>`}
      <td class="mh-num" data-label="${model.external?"到园份数":"实供人数"}">${value(r.actual,!model.external&&r.status==="待确认")}</td><td class="mh-progress">${pill(r.status)}</td><td class="mh-rowaction">${actionButton(r.action)}</td></tr>`;
  }).join("");
  return `<section class="mh-panel mh-meals"><div class="mh-panel-head"><h2>${icon("spoon")}${model.date===model.today?"今日供餐":"当日供餐"}</h2><span class="mh-meta">${dateLabel(model.date)}</span></div>
    ${rows?`<div class="mh-scroll" tabindex="0" aria-label="餐次和供餐明细"><table><thead><tr><th>餐次</th><th>今日菜品</th>${model.external?"":"<th class='mh-num'>计划人数</th>"}<th class="mh-num">${model.external?"到园份数":"实供人数"}</th><th>进度</th><th class="mh-rowaction">操作</th></tr></thead><tbody>${rows}</tbody></table></div>`:
    `<div class="mh-empty">${icon("kitchen")}<strong>${esc(model.note || "当天暂无供餐安排")}</strong>${model.menu?actionButton(model.menu):""}</div>`}</section>`;
}
function todos() {
  const all=model.todos;
  const show=expanded?all:all.slice(0,4);
  const html=show.map(t=>{
    const late=t.date<model.today;
    return `<li><div class="mh-task-main"><span class="mh-flag ${late?"mh-late":""}">${late?"逾期":"今天"}</span><span class="mh-task-title">${esc(t.title)}</span></div><div class="mh-task-foot"><span>${icon("clock")}${dateLabel(t.date)}</span>${actionButton(t.action,"mh-link","",icon("chevron"))}</div></li>`;
  }).join("");
  return `<section class="mh-panel mh-todos"><div class="mh-panel-head"><h2>${icon("checklist")}待我处理 <span class="mh-count">${all.length}</span></h2>${model.date<model.today?'<span class="mh-meta">截至'+dateLabel(model.date)+'</span>':""}</div>
    ${html?`<ul class="mh-task-list">${html}</ul>`:`<div class="mh-empty"><span class="mh-clear">${icon("check")}</span><strong>暂无待处理事项</strong></div>`}
    ${all.length>4?`<button type="button" class="mh-more" data-cmd="expand" aria-expanded="${expanded}">${expanded?"收起待办":`查看全部 ${all.length} 项`}${icon("down")}</button>`:""}</section>`;
}
function calendar() {
  if (!model.days.length) return "";
  const tiles=model.days.map((d,i)=>`<button type="button" data-date="${esc(d.date)}" class="mh-day ${d.date===model.date?"mh-selected":""}" aria-pressed="${d.date===model.date}" aria-label="${esc(d.date+" "+dayLabels[i]+" "+d.status)}"><span class="mh-day-name">${dayLabels[i]}${d.date===model.today?'<b class="mh-now">今</b>':""}</span><span class="mh-day-date">${d.date.slice(5).replace("-",".")}</span>${pill(d.status)}</button>`).join("");
  return `<section class="mh-panel mh-week"><div class="mh-panel-head"><h2>${icon("calendar")}本周供餐 <span class="mh-meta">${dateLabel(model.days[0].date)} – ${dateLabel(model.days[6].date)}</span></h2>${model.menu?actionButton(model.menu,"mh-link","",icon("arrow")):""}</div>
    <div class="mh-days">${tiles}</div></section>`;
}
function render() {
  actions=[];
  root.innerHTML=`<header class="mh-header"><div class="mh-title-line"><h1>食堂工作台</h1><button class="mh-refresh" type="button" data-cmd="refresh" title="刷新工作台" aria-label="刷新工作台">${icon("refresh")}</button></div>${model.sites.length?filters():""}</header>
    <div class="mh-grid" aria-live="polite">${meals()}${todos()}${calendar()}</div>`;
  const week=root.querySelector(".mh-days"), selected=week?.querySelector(".mh-selected");
  if(selected && week.scrollWidth>week.clientWidth) week.scrollLeft=Math.max(0,selected.getBoundingClientRect().right-week.getBoundingClientRect().right+8);
}
async function load(args={},restore=false,focus=null) {
  const version=++requestId;
  root.setAttribute("aria-busy","true");
  try {
    const res=await frappe.call({method:"tongjianyun.canteen_ops.home.dashboard", type:"GET", args});
    if (version!==requestId || !root.isConnected) return;
    model=res.message;
    if (restore) {
      let stored;
      try { stored=JSON.parse(sessionStorage.getItem(pref)); } catch {}
      if (stored && model.sites.some(s=>s.name===stored.canteen && s.company===stored.company) && model.canteen!==stored.canteen)
        return await load({company:stored.company,canteen:stored.canteen,service_date:model.date});
    }
    try { sessionStorage.setItem(pref,JSON.stringify({company:model.company,canteen:model.canteen})); } catch {}
    expanded=false;
    render();
    if (focus) root.querySelector(focus)?.focus({preventScroll:true});
  } catch {
    if (version===requestId && root.isConnected) root.innerHTML='<div class="mh-error" role="alert"><strong>供餐工作台加载失败</strong><button type="button" class="mh-link" data-cmd="retry">重新加载</button></div>';
  } finally {
    if(version===requestId) root.removeAttribute("aria-busy");
  }
}
function choose(date,focus) {
  return load({company:model.company,canteen:model.canteen,service_date:date},false,focus);
}
async function act(a) {
  if(a.kind==="form") return frappe.set_route("Form",a.doctype,a.name);
  if(a.kind==="reason") return frappe.msgprint({title:"停供原因",message:esc(a.reason)});
  if(a.kind==="kitchen") {
    const res=await frappe.call({method:"ione_core.meal_kitchen.get_kitchen_day",type:"POST",args:{week_name:a.week,meal_date:a.date},freeze:true});
    return frappe.set_route("Form","Meal Kitchen Day",res.message.name);
  }
  if(a.kind==="receive") {
    const receive=async code=>{
      const r=await frappe.call({method:"tongjianyun.canteen_ops.purchasing.receiving_from_code",type:"POST",args:{code,expected_delivery:a.delivery},freeze:true});
      await frappe.set_route("Form","Tongjianyun Canteen Receiving",r.message);
    };
    const d=new frappe.ui.Dialog({title:"核对随货二维码",fields:[{fieldname:"code",fieldtype:"Data",label:"随货码",reqd:1}],
      primary_action_label:"打开验收单",primary_action:async v=>{await receive(v.code);d.hide();}});
    d.set_secondary_action(()=>{new frappe.ui.Scanner({dialog:true,multiple:false,on_scan:async r=>{if(r.decodedText){await receive(r.decodedText);d.hide();}}});});
    d.set_secondary_action_label("扫码");
    return d.show();
  }
  if(a.kind==="handover") return frappe.new_doc("Tongjianyun Meal Delivery Handover",{company:model.company,canteen:model.canteen,publication:a.publication,service_date:a.date,meal_type:a.slot});
  if(a.kind==="handovers") {
    frappe.route_options={company:model.company,canteen:model.canteen,publication:a.publication,service_date:a.date,meal_type:a.slot};
    return frappe.set_route("List","Tongjianyun Meal Delivery Handover");
  }
}
root.addEventListener("change",event=>{
  const field=event.target.dataset.field;
  if(!field || !event.target.value) return;
  const args={company:model.company,canteen:model.canteen,service_date:model.date};
  if(field==="company") {args.company=event.target.value;delete args.canteen;}
  if(field==="canteen") args.canteen=event.target.value;
  if(field==="date") args.service_date=event.target.value;
  load(args,false,`[data-field="${field}"]`);
});
root.addEventListener("click",event=>{
  if (event.target.matches("input[type=date]") && event.target.showPicker) {
    try { event.target.showPicker(); } catch {}
    return;
  }
  const el=event.target.closest("button");
  if(!el || root.getAttribute("aria-busy")==="true") return;
  if(el.dataset.action!==undefined) return act(actions[Number(el.dataset.action)]);
  if(el.dataset.date) return choose(el.dataset.date,`[data-date="${el.dataset.date}"]`);
  switch(el.dataset.cmd){
    case "today": return choose(model.today,'[data-cmd="today"]');
    case "refresh": return choose(model.date,'[data-cmd="refresh"]');
    case "retry": return load({},true);
    case "expand": expanded=!expanded;render();root.querySelector('[data-cmd="expand"]')?.focus({preventScroll:true});break;
  }
});
let hasAppeared=false, wasHidden=false;
const visibility=new IntersectionObserver(([entry])=>{
  if (!entry.isIntersecting) { wasHidden=hasAppeared; return; }
  if (wasHidden && model && !root.hasAttribute("aria-busy")) {
    load({company:model.company,canteen:model.canteen,service_date:model.date===model.today?undefined:model.date});
  }
  hasAppeared=true;
  wasHidden=false;
});
visibility.observe(root);
load({},true);
})();
