// Registered components only. Model messages, HTML and executable code are never rendered here.
import {mealContext,setMealContext,refreshMealData} from './state.js?v=meal-header-20260925-1';
const $=id=>document.getElementById(id);
const validViews=new Set(['students','class_students','meal_counts','recipe_week','recipe_nutrition',
  'business_catalog','business_list','business_record','stock','ingredient_nutrition','classroom_day','weekly_orders',
  'project_catalog','frappe_catalog','frappe_doctype','frappe_document','frappe_new','frappe_report','frappe_page','frappe_workspace','business_blueprint']);
let request,current=null,ticket=0,nativeSession=null,loadingTicket=0;
const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=String(text??'—');if(cls)el.className=cls;return el;};
function notice(text,error=false){$('view-status').textContent=text;$('view-status').hidden=!text;$('view-status').classList.toggle('error',error);}
export function currentViewContext(){if(nativeSession)syncNativeContext(nativeSession);return current||{view:'recipe_week',...mealContext()};}
function outcome(status,selection,message=''){
  const result={status,...(selection?{selection}:{}),...(message?{message}:{})};
  document.dispatchEvent(new CustomEvent('meal-scene:view-status',{detail:result}));return result;
}
function nativeDirty(){
  if(!nativeSession)return false;
  try{const win=nativeSession.frame.contentWindow,form=win?.cur_frm,route=win?.frappe?.get_route?.();if((!route||route[0]==='Form')&&typeof form?.is_dirty==='function')return !!form.is_dirty();}catch(_){}
  return nativeSession.dirty;
}
function mayLeaveNative(origin){
  if(!nativeDirty())return true;
  if(origin==='refresh')return false;
  return typeof window!=='undefined'&&window.confirm('当前业务有未保存的修改。确认放弃这些修改并切换吗？');
}
function disposeNative(){
  if(!nativeSession)return;
  if(nativeSession.timer!==null)clearInterval(nativeSession.timer);
  nativeSession.unbind?.();nativeSession=null;
}
export function initializeViews(options){
  request=options.request;
  // Each page load starts on the weekly recipe, independently of chat history.
  showCalendar();
  $('view-back').addEventListener('click',()=>showCalendar());
  document.addEventListener('meal-scene:refresh',event=>{if(!event.detail?.calendarOnly&&current&&current.view!=='recipe_week')showBusinessView(current,{origin:'refresh'});});
  if(typeof window!=='undefined'){
    window.addEventListener('beforeunload',event=>{if(nativeDirty()){event.preventDefault();event.returnValue='';}});
    window.addEventListener('pagehide',disposeNative);
  }
}
function calendarContext(choice){
  if(!choice?.day||!choice?.meal)return;
  if(setMealContext(choice))refreshMealData({calendarOnly:true});
}
function showCalendar(choice,options={}){
  if(!options.checked&&!mayLeaveNative(options.origin))return outcome('blocked',currentViewContext(),'当前业务有未保存的修改，已保留原页面。');
  ++ticket;loadingTicket=0;disposeNative();current=null;notice('');$('business-view').hidden=true;$('recipe-workspace').hidden=false;
  $('business-view').classList.toggle('has-native',false);
  $('business-canvas').setAttribute('aria-label','本周膳食总览');
  document.dispatchEvent(new CustomEvent('meal-scene:view-change',{detail:{view:'recipe_week'}}));
  calendarContext(choice);
  return outcome('rendered',currentViewContext());
}
function actionButton(action){
  const button=node('button',action.label,'view-action');button.type='button';
  button.addEventListener('click',()=>showBusinessView(action.selection));return button;
}
function renderStats(block){
  const row=node('div',undefined,'view-stats');
  for(const item of block.items){const card=node('div');card.append(node('div',item.label,'view-stat-label'));
    const value=node('div',undefined,'view-stat-value');value.append(node('span',item.value),node('small',item.unit||''));card.append(value);
    if(item.note)card.append(node('div',item.note,'view-stat-note'));row.append(card);}
  return row;
}
function renderTable(block){
  const section=node(block.collapsed?'details':'section',undefined,block.collapsed?'view-section view-details':'view-section');
  section.append(node(block.collapsed?'summary':'h2',block.title));
  if(!block.rows.length){section.append(node('p','当前可见范围没有记录。','view-empty'));return section;}
  const wrapper=node('div',undefined,'view-table-wrap'),table=node('table'),head=node('thead'),header=node('tr');
  table.setAttribute('aria-label',block.title);block.columns.forEach(label=>header.append(node('th',label)));head.append(header);table.append(head);
  const body=node('tbody');
  for(const row of block.rows){const tr=node('tr');row.cells.forEach((value,index)=>{
    const cell=node('td');if(index===0&&row.action)cell.append(actionButton({...row.action,label:String(value??'—')}));else cell.textContent=String(value??'—');
    if(typeof value==='number')cell.className='view-numeric';
    if(index===row.cells.length-1&&['适宜','偏低','偏高','未评价'].includes(row.evaluation))cell.className='view-evaluation '+(row.evaluation==='适宜'?'good':row.evaluation==='未评价'?'unknown':'warn');
    tr.append(cell);
  });body.append(tr);}
  table.append(body);wrapper.append(table);section.append(wrapper);return section;
}
function renderBars(block){
  const section=node('section',undefined,'view-section');section.append(node('h2',block.title));
  const maximum=Math.max(1,...block.rows.map(row=>Number(row.value)||0));
  if(!block.rows.length)section.append(node('p','当前可见范围没有记录。','view-empty'));
  for(const row of block.rows){const item=node('div',undefined,'view-bar-row');
    item.append(row.action?actionButton({...row.action,label:row.label}):node('span',row.label));
    const track=node('div',undefined,'view-bar-track'),bar=node('div',undefined,'view-bar');
    track.setAttribute('role','img');track.setAttribute('aria-label',`${row.label} ${row.value} 人`);
    bar.style.width=(Math.max(0,Number(row.value)||0)/maximum*100)+'%';track.append(bar);item.append(track,node('span',`${row.value} 人`,'view-numeric'));section.append(item);
  }return section;
}
function renderNotice(block){return node('p',block.text,'view-note'+(block.warning?' warning':''));}
function safeDeskRoute(route){
  if(typeof route!=='string'||!route.startsWith('/desk/')||/[\\?#\r\n]/.test(route)||route.includes('//')||route.includes('..'))return false;
  try{return !route.split('/').some(part=>{const decoded=decodeURIComponent(part);return decoded==='.'||decoded==='..'||/[\\?#\r\n]/.test(decoded);});}catch(_){return false;}
}
function syncNativeContext(session){
  if(session!==nativeSession||!current)return;
  try{
    const win=session.frame.contentWindow,route=win?.frappe?.get_route?.();
    if(!Array.isArray(route)||!route.length)return;
    const text=value=>typeof value==='string'&&value.length>0&&value.length<=500&&!/[\x00-\x1f]/.test(value);
    let next=null;
    if(route[0]==='Form'&&text(route[1])&&text(route[2])){
      const isNew=!!win.cur_frm?.doc?.__islocal;
      next=isNew?{view:'frappe_new',doctype:route[1]}:{view:'frappe_document',doctype:route[1],document:route[2]};
    }else if(route[0]==='List'&&text(route[1]))next=route[2]==='Report'&&text(route[3])?{view:'frappe_report',report:route[3]}:{view:'frappe_doctype',doctype:route[1]};
    else if(route[0]==='query-report'&&text(route[1]))next={view:'frappe_report',report:route[1]};
    else if(route.length===1&&text(route[0])&&Object.hasOwn(win.frappe.pages||{},route[0]))next={view:'frappe_page',page:route[0]};
    // Never pass arbitrary URLs, query strings, form values or dirty state to the model.
    if(next)current={...next,...Object.fromEntries(['day','meal'].filter(key=>current[key]).map(key=>[key,current[key]]))};
  }catch(_){}
}
function bindNativeDocument(session){
  session.unbind?.();
  try{
    const doc=session.frame.contentDocument;if(!doc)return;
    const changed=()=>{session.dirty=true;session.revision++;};
    const clicked=event=>{
      const anchor=event.target?.closest?.('a[href]');if(!anchor)return;
      let url;try{url=new URL(anchor.href,session.frame.src);}catch(_){return;}
      // Ordinary same-site Desk navigation stays inside the canvas, not a new tab.
      if(url.origin===location.origin&&safeDeskRoute(url.pathname))anchor.target='_self';
    };
    doc.addEventListener('input',changed,true);doc.addEventListener('change',changed,true);doc.addEventListener('click',clicked,true);
    session.unbind=()=>{doc.removeEventListener('input',changed,true);doc.removeEventListener('change',changed,true);doc.removeEventListener('click',clicked,true);};
  }catch(_){}
}
function renderFrappeFrame(block){
  // Routes come from permission-checked site metadata, never model supplied URLs.
  if(!safeDeskRoute(block.route))throw Error('原生业务地址无效。');
  const section=node('section',undefined,'view-native');
  const link=node('a','在独立页面打开 ↗','view-action');link.href=block.route;link.target='_blank';link.rel='noopener noreferrer';
  const frame=node('iframe');frame.src=block.route;frame.title=block.title||'Frappe 业务';frame.referrerPolicy='same-origin';
  const status=node('p','已打开业务容器，正在等待原生页面加载；尚未执行任何业务操作。','view-native-status');status.setAttribute('role','status');
  const session={frame,status,dirty:false,revision:0,timer:null,unbind:null};section.nativeSession=session;
  frame.addEventListener('load',()=>{
    if(nativeSession!==session)return;
    try{
      const actual=frame.contentWindow?.location,title=frame.contentDocument?.title||'';
      if(!actual||actual.origin!==location.origin||!safeDeskRoute(actual.pathname)||/^(?:403|404|500|Not Permitted|Not Found|Permission Denied|Forbidden|Server Error|Login|登录|无权限|页面未找到)(?:\b|\s|$)/i.test(title))throw Error('unexpected page');
    }catch(_){status.textContent='尚未确认业务页面可用，请核对登录与权限。页面加载不代表业务操作已完成。';return;}
    status.textContent='页面已载入。请在原业务界面核对内容；页面载入不代表保存、审批或查询已完成。';
    bindNativeDocument(session);syncNativeContext(session);
  });
  frame.addEventListener('error',()=>{if(nativeSession===session)status.textContent='原生页面加载失败，当前业务尚未完成。可通过独立页面核对，或重新打开。';});
  section.append(link,frame,status);return section;
}
function renderBlueprint(block){
  if(!Array.isArray(block.fields)||!Array.isArray(block.warnings)||!['proposed','active','conflict'].includes(block.state))throw Error('业务方案格式无效。');
  const section=node('section',undefined,'view-blueprint');section.append(node('h2',block.title),node('p',block.description,'view-note'));
  section.append(renderTable({title:'业务字段预览',columns:['字段','类型','必填','选项 / 关联业务'],rows:block.fields.map(field=>({cells:[field.label||field.fieldname,field.fieldtype,field.reqd?'是':'否',field.options||'—']}))}));
  for(const warning of block.warnings)section.append(node('p',warning,'view-note warning'));
  section.append(node('p','启用会新增独立业务数据表，默认仅 System Manager 可使用；不会自动创建真实业务记录。','view-note'));
  const status=node('p',block.state==='active'?'这项业务已经启用。':block.state==='conflict'?'方案存在冲突，当前不能启用。':'当前仅为方案预览，尚未新增业务数据表。','view-blueprint-status');status.setAttribute('role','status');section.append(status);
  if(block.state==='proposed'&&block.can_activate===true){
    if(typeof block.proposal_id!=='string'||!/^[a-f0-9]{64}$/i.test(block.revision||''))throw Error('业务方案版本无效，请重新预览。');
    const button=node('button','确认启用这项业务','view-blueprint-activate');button.type='button';section.append(button);
    button.addEventListener('click',async()=>{
      if(button.disabled||!window.confirm('确认启用这项业务？将新增独立业务数据表，默认仅 System Manager 可使用，不会自动建立真实业务记录。'))return;
      const startingTicket=ticket;button.disabled=true;status.textContent='正在启用，请勿重复提交…';
      try{
        const result=await request('/api/method/tongjianyun.business_blueprints.activate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({proposal_id:block.proposal_id,revision:block.revision})});
        if(typeof result?.doctype!=='string'||!result.doctype)throw Error('启用结果需要核对，请重新打开方案，不要重复提交。');
        status.textContent='业务已经启用；尚未建立真实业务记录。';
        if(startingTicket===ticket)await showBusinessView({view:'frappe_doctype',doctype:result.doctype});
      }catch(error){status.textContent=error.message||'启用结果未知，请先重新读取方案核对，不要直接重复提交。';}
    });
  }
  return section;
}
const renderers={stats:renderStats,table:renderTable,bars:renderBars,notice:renderNotice,frappe_frame:renderFrappeFrame,business_blueprint:renderBlueprint};
export function buildComponents(data){
  if(data?.version!==1||!validViews.has(data.selection?.view)||!Array.isArray(data.components)||data.components.length>12)throw Error('展示结果格式不受支持，已保留当前页面。');
  const content=document.createDocumentFragment();
  for(const block of data.components){if(!Object.hasOwn(renderers,block.type))throw Error('此结果需要更新页面组件，已保留当前内容。');const rendered=renderers[block.type](block);if(rendered.nativeSession){if(content.nativeSession)throw Error('同一业务视图只能打开一个原生页面。');content.nativeSession=rendered.nativeSession;}content.append(rendered);}
  return content;
}
export async function showBusinessView(choice,options={}){
  if(!choice||!validViews.has(choice.view)||!request)return outcome('failed',undefined,'暂不支持该业务视图。');
  if(options.origin==='refresh'&&loadingTicket)return outcome('blocked',currentViewContext(),'正在切换业务，已跳过自动刷新。');
  // A task finishing is a data refresh, never permission to discard a native form.
  if(nativeSession&&options.origin==='refresh')return outcome('rendered',currentViewContext(),'当前原生页面已保留，未自动重载。');
  if(!mayLeaveNative(options.origin))return outcome('blocked',currentViewContext(),'当前业务有未保存的修改，已保留原页面。');
  const leavingDirty=nativeDirty(),leavingRevision=nativeSession?.revision;
  const turn=++ticket;loadingTicket=turn;notice('正在读取业务数据…');
  try{
    const result=await request('/api/method/tongjianyun.meal_views.get_view?'+new URLSearchParams({selection_json:JSON.stringify(choice)}));
    if(turn!==ticket)return outcome('superseded');
    if(result.version!==1||!validViews.has(result.selection?.view))throw Error('展示结果格式无效。');
    // An edit made while loading also needs consent, even if the form was clean at the start.
    if(nativeDirty()&&(!leavingDirty||nativeSession?.revision!==leavingRevision)&&!mayLeaveNative(options.origin)){notice('已保留未保存的业务页面。');return outcome('blocked',currentViewContext(),'当前业务有未保存的修改，已保留原页面。');}
    if(result.selection.view==='recipe_week')return showCalendar(result.selection,{checked:true});
    const fragment=buildComponents(result);
    const actions=(result.actions||[]).map(actionButton);
    disposeNative();nativeSession=fragment.nativeSession||null;
    $('view-title').textContent=result.title;$('view-subtitle').textContent=result.subtitle;
    $('view-content').replaceChildren(fragment);$('view-actions').replaceChildren(...actions);
    $('view-source').textContent=`来源：${result.source} · 更新于 ${result.generated_at}`;
    current=result.selection;
    $('business-view').classList.toggle('has-native',!!nativeSession);
    if(nativeSession&&typeof setInterval==='function'){const session=nativeSession;session.timer=setInterval(()=>syncNativeContext(session),750);}
    $('recipe-workspace').hidden=true;$('business-view').hidden=false;$('business-canvas').setAttribute('aria-label',result.title);
    document.dispatchEvent(new CustomEvent('meal-scene:view-change',{detail:{view:current.view}}));
    notice('');if(['meal_counts','business_list','business_catalog','ingredient_nutrition','classroom_day','weekly_orders'].includes(current.view))calendarContext(current);
    return outcome('rendered',current,nativeSession?'已打开业务容器，正在等待原生页面加载；不代表业务操作已完成。':'');
  }catch(error){if(turn!==ticket)return outcome('superseded');const message=error.message||'数据读取失败，已保留上一次结果。';notice(message,true);return outcome('failed',undefined,message);}
  finally{if(loadingTicket===turn)loadingTicket=0;}
}
