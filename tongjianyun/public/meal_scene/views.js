// Registered components only. Model messages, HTML and executable code are never rendered here.
import {mealContext,setMealContext,refreshMealData,readRecipeCalendar} from './state.js?v=meal-calendar-read-20260926-2';
const $=id=>document.getElementById(id);
const validViews=new Set(['students','class_students','meal_counts','recipe_week','recipe_nutrition',
  'business_catalog','business_list','business_record','stock','ingredient_nutrition','classroom_day','weekly_orders',
  'project_catalog','frappe_catalog','frappe_doctype','frappe_document','frappe_new','frappe_report','frappe_page','frappe_workspace','business_blueprint','business_proposal','business_proposal_inbox','business_proposal_handoff','stock_reconciliation']);
let request,current=null,ticket=0,nativeSession=null,registerSession=null,loadingTicket=0;
let sceneHome={view:'recipe_week'},sceneRecipeAllowed=true,sceneGroup=null,sceneNavigation=null;
const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=String(text??'—');if(cls)el.className=cls;return el;};
function notice(text,error=false){$('view-status').textContent=text;$('view-status').hidden=!text;$('view-status').classList.toggle('error',error);}
export function currentViewContext(){if(nativeSession)syncNativeContext(nativeSession);return current||sceneChoice(sceneHome);}
function outcome(status,selection,message=''){
  const result={status,...(selection?{selection}:{}),...(message?{message}:{})};
  document.dispatchEvent(new CustomEvent('meal-scene:view-status',{detail:result}));return result;
}
function nativeDirty(){
  if(!nativeSession)return false;
  try{const win=nativeSession.frame.contentWindow,form=win?.cur_frm,route=win?.frappe?.get_route?.();if((!route||route[0]==='Form')&&typeof form?.is_dirty==='function')return !!form.is_dirty();}catch(_){}
  return nativeSession.dirty;
}
function viewDirty(){return nativeDirty()||!!registerSession&&(registerSession.dirty||['saving','uncertain'].includes(registerSession.state));}
function editRevision(){return [nativeSession?.revision||0,registerSession?.editRevision||0].join(':');}
function mayLeaveNative(origin){
  if(registerSession?.state==='saving')return origin==='saved';
  if(origin==='verify'&&['saved','uncertain'].includes(registerSession?.state))return true;
  if(!viewDirty())return true;
  if(origin==='refresh')return false;
  return typeof window!=='undefined'&&window.confirm('当前业务有未保存或待核对的修改。确认离开并切换吗？');
}
function disposeNative(){
  if(!nativeSession)return;
  if(nativeSession.timer!==null)clearInterval(nativeSession.timer);
  nativeSession.unbind?.();nativeSession=null;
}
export function initializeViews(options){
  request=options.request;
  const bootstrap=options.bootstrap;
  sceneRecipeAllowed=bootstrap?bootstrap.recipe_calendar===true:true;
  sceneHome=bootstrap?.default_view||{view:'recipe_week'};sceneGroup=bootstrap?.scope?.selected_group||null;
  if(bootstrap){setMealContext(bootstrap);document.dispatchEvent(new CustomEvent('meal-scene:context',{detail:{...mealContext(),group:sceneGroup}}));}
  $('view-back').textContent=sceneRecipeAllowed?'← 回到食谱':'← 场景首页';
  $('view-back').addEventListener('click',showSceneHome);
  if(bootstrap&&!bootstrap.chat?.allowed)buildSceneNavigation(bootstrap.navigation||[]);
  document.addEventListener('meal-scene:refresh',event=>{if(!event.detail?.calendarOnly&&current&&current.view!=='recipe_week')showBusinessView(current,{origin:'refresh'});});
  document.addEventListener('meal-scene:view-change',syncSceneNavigation);
  if(typeof window!=='undefined'){
    window.addEventListener('beforeunload',event=>{if(viewDirty()){event.preventDefault();event.returnValue='';}});
    window.addEventListener('pagehide',disposeNative);
  }
  // Chat history never chooses the homepage. Administrators retain weekly recipes;
  // other accounts start from their permission-checked bootstrap selection.
  return showSceneHome();
}
function sceneChoice(choice){
  if(['business_proposal','business_proposal_inbox','business_proposal_handoff','stock_reconciliation'].includes(choice?.view))return {...choice};
  const selected={...choice,...mealContext()};
  if(sceneGroup&&['classroom_day','meal_counts','class_students'].includes(selected.view))selected.group=sceneGroup;
  return selected;
}
function showSceneHome(){
  const choice=sceneChoice(sceneHome);
  return choice.view==='recipe_week'?showCalendar(choice):showBusinessView(choice);
}
function syncSceneNavigation(){
  if(!sceneNavigation)return;
  const selected=currentViewContext();
  const changedGroup=!!selected.group&&selected.group!==sceneGroup;
  if(selected.group)sceneGroup=selected.group;
  if(selected.day&&selected.meal){
    const changed=setMealContext(selected);
    if(changed||changedGroup)document.dispatchEvent(new CustomEvent('meal-scene:context',{detail:{...mealContext(),group:sceneGroup}}));
  }
  sceneNavigation.day.value=selected.day||mealContext().day;
  sceneNavigation.meal.value=selected.meal||mealContext().meal;
  for(const item of sceneNavigation.buttons)item.button.setAttribute('aria-pressed',String(item.selection.view===selected.view));
}
function buildSceneNavigation(actions){
  const bar=node('nav',undefined,'view-actions'),dateLabel=node('label','日期 '),date=node('input'),mealLabel=node('label','餐次 '),meal=node('select');
  bar.setAttribute('aria-label','场景业务导航');bar.classList.toggle('view-register',true);date.type='date';date.setAttribute('aria-label','业务视图日期');meal.setAttribute('aria-label','业务视图餐次');
  for(const [value,label] of [['breakfast','早餐'],['morning_snack','早点'],['lunch','午餐'],['afternoon_snack','午点'],['dinner','晚餐']]){const option=node('option',label);option.value=value;meal.append(option);}
  dateLabel.append(date);mealLabel.append(meal);bar.append(dateLabel,mealLabel);
  sceneNavigation={day:date,meal,buttons:[]};
  for(const action of actions){
    if(!action||!validViews.has(action.selection?.view))continue;
    const button=node('button',action.label,'view-back');button.type='button';
    button.addEventListener('click',()=>showBusinessView(sceneChoice(action.selection)));
    sceneNavigation.buttons.push({button,selection:action.selection});bar.append(button);
  }
  const change=async()=>{
    const previous=mealContext();
    if(!/^\d{4}-\d{2}-\d{2}$/.test(date.value)){date.value=previous.day;return;}
    const desired={day:date.value,meal:meal.value};
    const timeless=['business_proposal','business_proposal_inbox','business_proposal_handoff','stock_reconciliation'].includes((current||sceneHome).view);
    const result=await showBusinessView(timeless?sceneChoice(current||sceneHome):{...sceneChoice(current||sceneHome),...desired});
    if(result.status==='rendered'){
      // Students are all-date master data and their canonical server selection
      // intentionally drops day/meal. Keep the user's chosen scene context for
      // the next attendance/meal view, without claiming students were date-filtered.
      const selected={day:result.selection?.day||desired.day,meal:result.selection?.meal||desired.meal};
      if(setMealContext(selected))document.dispatchEvent(new CustomEvent('meal-scene:context',{detail:{...mealContext(),group:sceneGroup}}));
    }
    syncSceneNavigation();
  };
  date.addEventListener('change',change);meal.addEventListener('change',change);
  $('business-canvas').insertBefore(bar,$('view-status'));syncSceneNavigation();
}
function calendarContext(choice,{refresh=true}={}){
  if(!choice?.day||!choice?.meal)return;
  const changed=setMealContext(choice);if(choice.group)sceneGroup=choice.group;
  document.dispatchEvent(new CustomEvent('meal-scene:context',{detail:{...mealContext(),group:sceneGroup}}));
  syncSceneNavigation();if(refresh&&changed&&sceneRecipeAllowed)refreshMealData({calendarOnly:true});
}
function showCalendar(choice,options={}){
  if(!sceneRecipeAllowed)return outcome('blocked',currentViewContext(),'当前账号没有食谱读取权限，请使用场景首页中的可用业务。');
  if(!options.checked&&!mayLeaveNative(options.origin))return outcome('blocked',currentViewContext(),'当前业务有未保存的修改，已保留原页面。');
  const turn=++ticket;loadingTicket=turn;disposeNative();registerSession=null;current=null;notice('正在读取周历…');$('business-view').hidden=true;$('recipe-workspace').hidden=false;
  $('business-view').classList.toggle('has-native',false);
  $('business-canvas').setAttribute('aria-label','本周膳食总览');
  document.dispatchEvent(new CustomEvent('meal-scene:view-change',{detail:{view:'recipe_week'}}));
  calendarContext(choice,{refresh:false});
  const context=mealContext(),selection={view:'recipe_week',...context};
  return readRecipeCalendar(context).then(result=>{
    if(turn!==ticket||mealContext().day!==context.day||mealContext().meal!==context.meal)return outcome('superseded');
    if(result.status!=='rendered'){const text=result.message||'周历尚未读取完成，请重试。';notice(text,true);return outcome(result.status,selection,text);}
    notice('');return outcome('rendered',selection);
  }).finally(()=>{if(loadingTicket===turn)loadingTicket=0;});
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
  const enabled=value=>value===true||value===1||value==='1',tables=block.tables??[],calculations=block.calculations??[],workflow=block.workflow??null;
  const fieldMap=fields=>{
    if(!Array.isArray(fields)||fields.some(field=>!field||typeof field.fieldname!=='string'||!field.fieldname||typeof field.fieldtype!=='string'||!field.fieldtype))throw Error('业务字段预览格式无效。');
    const map=new Map(fields.map(field=>[field.fieldname,field]));
    if(map.size!==fields.length)throw Error('业务字段预览存在重复字段。');
    return map;
  };
  const parentFields=fieldMap(block.fields),tableFields=new Map(),tableNames=new Map();
  if(!Array.isArray(tables)||tables.length>2||!Array.isArray(calculations))throw Error('明细表或计算预览格式无效。');
  for(const table of tables){
    if(!table||typeof table.fieldname!=='string'||parentFields.get(table.fieldname)?.fieldtype!=='Table'||tableFields.has(table.fieldname)||!Array.isArray(table.fields)||!table.fields.length||table.fields.length>12)throw Error('明细表预览格式无效。');
    tableFields.set(table.fieldname,fieldMap(table.fields));tableNames.set(table.fieldname,table.label||parentFields.get(table.fieldname).label||table.fieldname);
  }
  if(block.fields.some(field=>field.fieldtype==='Table'&&!tableFields.has(field.fieldname)))throw Error('明细表字段预览缺失，请重新读取方案。');
  const fieldLabel=(fields,key)=>{const field=fields.get(key);if(!field)throw Error('固定公式引用的字段不存在。');return field.label||field.fieldname;};
  const formulaRows=calculations.map(calculation=>{
    if(!calculation||!['multiply','sum'].includes(calculation.op))throw Error('不支持的固定公式，请重新读取方案。');
    const childFields=calculation.table?tableFields.get(calculation.table):null;
    if(calculation.table&&!childFields)throw Error('固定公式引用的明细表不存在。');
    if(calculation.op==='multiply'){
      if(!Array.isArray(calculation.sources)||calculation.sources.length!==2)throw Error('乘法公式预览格式无效。');
      const fields=childFields||parentFields;
      return {cells:[childFields?`${tableNames.get(calculation.table)} · 每行`:'主表',`${fieldLabel(fields,calculation.target)} = ${calculation.sources.map(source=>fieldLabel(fields,source)).join(' × ')}`,'服务端重新计算，不能手工覆盖']};
    }
    if(!childFields||typeof calculation.source!=='string')throw Error('合计公式预览格式无效。');
    return {cells:['主表',`${fieldLabel(parentFields,calculation.target)} = ${tableNames.get(calculation.table)} · ${fieldLabel(childFields,calculation.source)} 的合计`,'服务端重新计算，不能手工覆盖']};
  });
  if(workflow!==null){
    if(typeof workflow!=='object'||Array.isArray(workflow)||workflow.template!=='review'||!Array.isArray(workflow.states)||!workflow.states.length||!Array.isArray(workflow.transitions)||!workflow.transitions.length)throw Error('复核流程预览格式无效。');
    const states=new Set();
    for(const state of workflow.states){
      if(!state||typeof state.state!=='string'||!state.state||states.has(state.state)||!['0','1','2'].includes(String(state.doc_status))||typeof state.allow_edit!=='string'||!state.allow_edit)throw Error('复核状态预览格式无效。');
      states.add(state.state);
    }
    for(const transition of workflow.transitions){
      if(!transition||!states.has(transition.state)||!states.has(transition.next_state)||typeof transition.action!=='string'||!transition.action||typeof transition.allowed!=='string'||!transition.allowed||![true,false,0,1,'0','1'].includes(transition.allow_self_approval))throw Error('复核流转预览格式无效。');
    }
  }
  const fieldTable=(title,fields)=>renderTable({title,columns:['字段','类型','必填','选项 / 关联业务','填写方式'],rows:fields.map(field=>({cells:[field.label||field.fieldname,field.fieldtype,enabled(field.reqd)?'是':'否',field.options||'—',enabled(field.read_only)?'只读 / 系统维护':'按业务权限填写']}))});
  const section=node('section',undefined,'view-blueprint');section.append(node('h2',block.title),node('p',block.description,'view-note'));
  section.append(fieldTable('业务字段预览（主表）',block.fields));
  for(const table of tables)section.append(fieldTable(`明细表：${tableNames.get(table.fieldname)}`,table.fields));
  if(formulaRows.length)section.append(renderTable({title:'固定计算规则',columns:['计算位置','公式','执行方式'],rows:formulaRows}));
  if(workflow){
    const documentStates={'0':'草稿（0）','1':'已提交（1）','2':'已撤销（2）'};
    section.append(renderTable({title:'原生复核流程 · 状态',columns:['业务状态','单据状态','可编辑角色'],rows:workflow.states.map(state=>({cells:[state.state,documentStates[String(state.doc_status)],state.allow_edit]}))}));
    section.append(renderTable({title:'原生复核流程 · 操作',columns:['当前状态','操作','进入状态','操作角色','允许本人复核'],rows:workflow.transitions.map(transition=>({cells:[transition.state,transition.action,transition.next_state,transition.allowed,enabled(transition.allow_self_approval)?'允许':'不允许（Administrator 例外）']}))}));
    section.append(node('p','使用 Frappe 原生复核流程，操作仍需具备相应角色与单据权限。禁止本人复核的操作对 Administrator 存在原生例外，不代表已经实现双人复核；此处不会新增或授予角色。','view-note'));
  }
  for(const warning of block.warnings)section.append(node('p',warning,'view-note warning'));
  const impact=`启用会新增 1 张主表${tables.length?` + ${tables.length} 张明细表`:''}${workflow?'，并建立上述原生复核流程':''}，默认仅 System Manager 可使用；不会自动创建真实业务记录，也不会执行库存或财务操作。已有专业业务仍使用原流程。`;
  section.append(node('p',impact,'view-note'));
  const status=node('p',block.state==='active'?'这项业务已经启用。':block.state==='conflict'?'方案存在冲突，当前不能启用。':'当前仅为方案预览，尚未新增业务数据表。','view-blueprint-status');status.setAttribute('role','status');section.append(status);
  if(block.state==='proposed'&&block.can_activate===true){
    if(typeof block.proposal_id!=='string'||!block.proposal_id||block.proposal_id.length>140||!/^[a-f0-9]{64}$/i.test(block.revision||'')||typeof block.doctype!=='string'||!/^Tongjianyun (Extension|Advanced) .+/.test(block.doctype)||block.doctype.length>140)throw Error('业务方案版本或目标无效，请重新预览。');
    const session={dirty:false,state:'ready',editRevision:0,kind:'blueprint',confirming:false};section.registerSession=session;
    const button=node('button','确认启用这项业务','view-blueprint-activate'),confirmation=node('div',undefined,'view-blueprint-confirm'),confirm=node('button','确认创建以上业务结构','view-blueprint-activate'),cancel=node('button','暂不启用','view-back'),verify=node('button','重新读取方案核对','view-action');
    button.type=confirm.type=cancel.type=verify.type='button';confirmation.hidden=verify.hidden=true;confirmation.setAttribute('role','group');confirmation.setAttribute('aria-label','确认新业务结构');
    confirmation.append(node('h3','确认启用：'+block.title),node('p',impact),cancel,confirm);section.append(button,confirmation,verify);
    Object.assign(session,{button,confirmation,confirm,cancel,verify,status});
    const target={view:'business_blueprint',proposal_id:block.proposal_id};
    const resetConfirmation=()=>{if(registerSession!==session||session.state!=='ready')return;session.confirming=false;confirmation.hidden=true;button.hidden=false;button.focus?.();};
    cancel.addEventListener('click',resetConfirmation);
    confirmation.addEventListener('keydown',event=>{if(event.key==='Escape'&&session.state==='ready'){event.preventDefault();resetConfirmation();}});
    button.addEventListener('click',()=>{if(registerSession!==session||button.disabled||session.state!=='ready')return;session.confirming=true;confirmation.hidden=false;button.hidden=true;cancel.focus?.();});
    async function readBack(origin){
      verify.disabled=true;
      const result=await showBusinessView(target,{origin});
      if(result.status!=='rendered'&&registerSession===session){status.textContent='启用结果尚未完成回读核对，请重新读取方案，不要直接重复提交。';verify.hidden=false;verify.disabled=false;}
    }
    verify.addEventListener('click',()=>{if(registerSession===session&&!verify.disabled&&['saved','uncertain'].includes(session.state))return readBack('verify');});
    confirm.addEventListener('click',async()=>{
      if(registerSession!==session||!session.confirming||confirm.disabled||session.state!=='ready')return;
      session.state='saving';button.disabled=confirm.disabled=cancel.disabled=true;verify.disabled=true;status.textContent='正在启用，请勿重复提交…';
      try{
        const result=await request('/api/method/tongjianyun.business_blueprints.activate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({proposal_id:block.proposal_id,revision:block.revision})});
        if(result?.state!=='active'||result.doctype!==block.doctype||result.proposal_id!==block.proposal_id||result.revision!==block.revision)throw Error('启用回执与当前方案不一致。');
        if(registerSession!==session)return;
        session.state='saved';status.textContent='已收到启用回执，正在重新核对实际业务结构…';verify.hidden=false;
        await readBack('saved');
      }catch(error){if(registerSession!==session)return;session.state='uncertain';status.textContent=`${error.message||'启用结果未知。'} 请重新读取方案核对，不要直接重复提交。`;verify.hidden=false;verify.disabled=false;}
    });
  }
  return section;
}
const attendanceLabels={Unknown:'待登记',Present:'到园',Absent:'缺勤',Leave:'请假'};
function renderProposal(block){
  // Ordinary users preview their own versioned drafts. This component cannot
  // inherit the separate administrator blueprint's activation action.
  if(block.state!=='proposed'||typeof block.proposal_id!=='string'||!/^[a-f0-9]{64}$/.test(block.revision||''))throw Error('个人业务方案版本不完整。');
  const section=renderBlueprint({...block,can_activate:false});
  section.append(node('p','需要修改时，直接在右侧说明，例如“增加数量字段”。当前是方案草稿，不代表业务已经启用。','view-note'));
  if(block.can_handoff===true){
    if(!proposalUUID(block.proposal_id))throw Error('个人业务方案版本不完整。');
    const session={dirty:false,state:'ready',editRevision:0,kind:'proposal-handoff'};section.registerSession=session;
    const box=node('div',undefined,'view-proposal-handoff'),label=node('label','交给负责人'),recipient=node('input'),button=node('button','交给负责人','view-register-save');
    recipient.type='text';recipient.maxLength=140;recipient.autocomplete='off';recipient.placeholder='填写负责人完整账号';recipient.setAttribute('aria-label','负责人完整账号');button.type='button';button.disabled=true;
    const status=node('p','仅交接当前版本，不会自动启用业务。','view-register-status'),verify=node('button','查看交接记录核对','view-action');status.setAttribute('role','status');verify.type='button';verify.hidden=true;
    label.append(recipient);box.append(label,button,status,verify);section.append(box);
    Object.assign(session,{recipient,button,status,verify});
    const validRecipient=()=>typeof recipient.value==='string'&&recipient.value.trim().length>0&&recipient.value.trim().length<=140&&!/[\x00-\x1f]/.test(recipient.value)&&recipient.value.trim()!=='Guest';
    recipient.addEventListener('input',()=>{if(session.state!=='ready')return;session.editRevision++;session.dirty=!!recipient.value;button.disabled=!validRecipient();});
    const target={view:'business_proposal_inbox',folder:'sent',state:'all'};
    async function readBack(origin){
      verify.disabled=true;const result=await showBusinessView(target,{origin});
      if(result.status!=='rendered'&&registerSession===session){status.textContent='交接记录尚未读取成功，请重新查询核对，不要重复交接。';verify.hidden=false;verify.disabled=false;}
    }
    verify.addEventListener('click',()=>{if(registerSession===session&&!verify.disabled&&['saved','uncertain'].includes(session.state))return readBack('verify');});
    button.addEventListener('click',async()=>{
      if(registerSession!==session||session.state!=='ready'||button.disabled||!validRecipient())return;
      const body={proposal_id:block.proposal_id,revision:block.revision,recipient:recipient.value.trim()};
      session.state='saving';button.disabled=recipient.disabled=true;status.textContent='正在核对负责人和方案版本…';let submitted=false;
      const post=method=>request('/api/method/tongjianyun.business_proposal_api.'+method,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      try{
        const check=await post('check_recipient');
        if(registerSession!==session)return;
        if(check?.eligible!==true||check.recipient!==body.recipient||check.proposal_id!==body.proposal_id||check.revision!==body.revision){
          session.state='ready';recipient.disabled=false;button.disabled=!validRecipient();status.textContent='未交接。请核对负责人完整账号及接收权限。';return;
        }
        submitted=true;status.textContent='正在交接当前方案，请勿重复提交…';const result=await post('handoff');
        if(!proposalUUID(result?.handoff_id)||result.proposal_id!==body.proposal_id||result.revision!==body.revision||result.enabled!==false||!['pending','copying','uncertain','accepted'].includes(result.state))throw Error('交接回执与当前方案不一致。');
        if(registerSession!==session)return;
        session.state='saved';session.dirty=false;status.textContent='已收到交接记录回执，正在读取记录；不代表业务已启用。';verify.hidden=false;
        await readBack('saved');
      }catch(error){
        if(registerSession!==session)return;
        if(!submitted){session.state='ready';recipient.disabled=false;button.disabled=!validRecipient();status.textContent='未交接，暂时无法核对负责人。请稍后重新核对。';return;}
        session.state='uncertain';status.textContent='交接结果暂未确认。请查看交接记录，不要重复提交。';verify.hidden=false;verify.disabled=false;
      }
    });
  }
  return section;
}
function proposalUUID(value){return typeof value==='string'&&/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value);}
function renderProposalHandoff(block){
  const state=block.handoff_state;
  if(!proposalUUID(block.handoff_id)||!proposalUUID(block.proposal_id)||!/^[a-f0-9]{64}$/.test(block.revision||'')||!['pending','copying','uncertain','accepted','stale'].includes(state)||typeof block.sender!=='string'||!block.sender||block.sender.length>140)throw Error('交接方案版本不完整。');
  const section=renderBlueprint({...block,can_activate:false});
  section.append(node('p','提出人：'+block.sender,'view-note'));
  const status=Array.from(section.children).find(child=>child.className==='view-blueprint-status');
  status.textContent=state==='pending'?'以上为交接的固定版本；接收后再核对是否启用。':state==='accepted'?'已接收方案。业务是否已启用，需要打开负责人方案重新核验。':state==='stale'?'方案已修改，本次交接已失效，请提出人重新交接。':'接收结果尚待核实，请勿再次接收或要求重复交接。';
  if(state==='accepted'){
    const target=block.accepted_selection;
    if(target?.view!=='business_blueprint'||typeof target.proposal_id!=='string'||!target.proposal_id||target.proposal_id.length>140||/[\x00-\x1f]/.test(target.proposal_id)||Object.keys(target).length!==2)throw Error('接收结果尚未核实。');
    section.append(actionButton({label:'查看并核验负责人方案',selection:target}));return section;
  }
  if(state==='stale')return section;
  const session={dirty:false,state:state==='pending'?'ready':'uncertain',editRevision:0,kind:'proposal-accept'};section.registerSession=session;
  const button=node('button','接收方案','view-register-save'),verify=node('button','重新读取接收结果','view-action');button.type=verify.type='button';button.disabled=state!=='pending'||block.can_accept!==true;button.hidden=state!=='pending';verify.hidden=state==='pending';section.append(button,verify);Object.assign(session,{button,status,verify});
  const target={view:'business_proposal_handoff',handoff_id:block.handoff_id};
  async function readBack(origin){
    verify.disabled=true;const result=await showBusinessView(target,{origin});
    if(result.status!=='rendered'&&registerSession===session){status.textContent='接收结果未完成核对。请重新查询，不要再次接收。';verify.hidden=false;verify.disabled=false;}
  }
  verify.addEventListener('click',()=>{if(registerSession===session&&!verify.disabled&&['saved','uncertain'].includes(session.state))return readBack('verify');});
  button.addEventListener('click',async()=>{
    if(registerSession!==session||session.state!=='ready'||button.disabled)return;
    session.state='saving';button.disabled=true;status.textContent='正在接收方案；此操作不会启用业务…';
    try{
      const result=await request('/api/method/tongjianyun.business_proposal_api.accept_handoff',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({handoff_id:block.handoff_id})});
      if(result?.state!=='accepted'||result.enabled!==false||result.revision!==block.revision||typeof result.proposal_id!=='string'||!result.proposal_id||result.proposal_id.length>140||result.selection?.view!=='business_blueprint'||result.selection.proposal_id!==result.proposal_id)throw Error('接收回执尚未核实。');
      if(registerSession!==session)return;
      session.state='saved';status.textContent='接收回执已收到，正在重新读取核对…';verify.hidden=false;await readBack('saved');
    }catch(error){if(registerSession!==session)return;session.state='uncertain';status.textContent='接收结果暂未确认，请重新查询；不要重复接收。';verify.hidden=false;verify.disabled=false;}
  });
  return section;
}
function renderAttendance(block){
  return renderRegister(block,'attendance');
}
function renderMealRegister(block){
  return renderRegister(block,'meal');
}
function renderRegister(block,kind){
  const meal=kind==='meal',labels=meal?{'未确认':'未确认','就餐':'就餐','不就餐':'不就餐','不供餐':'不供餐'}:attendanceLabels;
  const hasPlan=block.has_plan===undefined?!!block.confirmed:block.has_plan===true;
  const requiresReason=meal&&(block.requires_change_reason===true||!!block.confirmed);
  if(typeof block.student_group!=='string'||!block.student_group||!/^\d{4}-\d{2}-\d{2}$/.test(block.day||'')||typeof block.revision!=='string'||!meal&&!block.revision||!Array.isArray(block.rows)||block.rows.length>500)throw Error('登记表日期、班级或版本不完整，已保留原页面。');
  if(meal&&!['breakfast','morning_snack','lunch','afternoon_snack','dinner'].includes(block.meal))throw Error('餐次无效，不能办理本餐确认。');
  const ids=new Set();
  for(const row of block.rows){if(typeof row.student!=='string'||!row.student||ids.has(row.student)||!Object.hasOwn(labels,meal?row.value:row.status))throw Error('登记名单格式无效，不能保存。');ids.add(row.student);}
  const section=node('section',undefined,'view-section view-register'),session={dirty:false,state:'ready',editRevision:0,fields:[],kind};section.registerSession=session;
  const title=meal?'本餐实际就餐确认':'班级点名';section.append(node('h2',title),node('p',`${block.group_label||block.student_group} · ${block.day}${meal?' · '+(block.meal_label||block.meal):''}`,'view-register-context'));
  section.append(node('p',meal?'预计人数仅作参考，不会自动当成实际。填写草稿后请核对本餐情况；不会修改其他餐次或学生考勤。':'只保存你明确修改的学生。待登记不算到园或缺勤；已有请假请在原流程撤销或标记返校。','view-note'));
  if(!block.editable)section.append(node('p',block.reason||'当前账号、日期或业务状态不允许编辑。','view-note warning'));
  const fillAll=meal&&block.editable===true?node('button','本班本餐全部就餐','view-register-fill'):null;
  if(fillAll){fillAll.type='button';const quick=node('div',undefined,'view-register-quick');quick.append(fillAll,node('span','只填写待核对草稿，可再修改个别学生；最后点击“确认本餐”才保存。'));section.append(quick);}
  const wrapper=node('div',undefined,'view-table-wrap'),table=node('table'),head=node('thead'),header=node('tr');
  table.setAttribute('aria-label',title);(meal?['学生','预计安排（非实际）','本餐实际情况']:['学生','原登记 / 来源','本次点名','请假原因']).forEach(text=>header.append(node('th',text)));head.append(header);table.append(head);
  const body=node('tbody');
  for(const row of block.rows){
    const tr=node('tr'),original=meal?(hasPlan?row.value:'未确认'):row.status,select=node('select'),locked=!meal&&!!row.leave_record;
    select.setAttribute('aria-label',`${row.student_name||row.student}${meal?'本餐实际情况':'出勤状态'}`);
    for(const [value,label] of Object.entries(labels)){const option=node('option',label);option.value=value;option.selected=value===original;option.disabled=locked&&value!==original||(meal?value==='未确认'&&original!=='未确认':value==='Unknown'&&original!=='Unknown');select.append(option);}select.value=original;
    const reason=node('input');reason.type='text';reason.maxLength=1000;reason.value='';reason.placeholder=row.leave_record?'已有请假，请使用原请假流程':'新请假时必填';reason.setAttribute('aria-label',`${row.student_name||row.student}请假原因`);
    const name=node('td',row.student_name||row.student),baseline=node('td',meal?(row.expected===true?'预计就餐':row.expected===false?'预计不就餐':'未提供预计'):labels[row.status]+(row.source?' · '+row.source:'')),value=node('td');value.append(select);tr.append(name,baseline,value);
    if(locked)value.append(node('small','已有生效请假，请先在原请假流程撤销或标记返校。','view-register-row-hint'));
    if(!meal){const cell=node('td');cell.append(reason);tr.append(cell);}body.append(tr);
    const field={row,original,select,reason,locked};session.fields.push(field);
    select.addEventListener('change',()=>{session.editRevision++;update();});reason.addEventListener('input',()=>{session.editRevision++;update();});
  }
  table.append(body);wrapper.append(table);section.append(wrapper);
  if(!block.rows.length)section.append(node('p','当前可见范围没有可登记学生，不会按零人完成确认。','view-empty'));
  const changeReason=node('textarea');changeReason.maxLength=1000;changeReason.rows=2;changeReason.value='';changeReason.setAttribute('aria-label','修改已确认本餐的原因');
  if(requiresReason){const label=node('label',undefined,'view-register-reason');label.append(node('span','修改已有实际就餐记录的原因（必填）'),changeReason);section.append(label);changeReason.addEventListener('input',()=>{session.editRevision++;update();});}
  const footer=node('div',undefined,'view-register-footer'),status=node('p','暂无变更','view-register-status'),save=node('button',meal?'确认本餐':'保存点名变更','view-register-save'),verify=node('button','重新读取并核对','view-action');
  status.setAttribute('role','status');save.type=verify.type='button';verify.hidden=true;footer.append(status,verify,save);section.append(footer);
  Object.assign(session,{status,save,verify,changeReason,fillAll});
  const changes=()=>session.fields.filter(field=>!field.locked&&(field.select.value!==field.original||!meal&&field.select.value==='Leave'&&!field.row.leave_record&&field.reason.value.trim())).map(field=>({student:field.row.student,status:field.select.value,leave_reason:field.reason.value.trim()}));
  const target=()=>({...current,view:meal?'meal_counts':'classroom_day',group:block.student_group,day:block.day,...(meal?{meal:block.meal}:{offset:Number.isInteger(block.offset)?block.offset:current?.offset||0})});
  function update(){
    const changed=changes();session.dirty=changed.length>0;
    const editing=block.editable===true&&session.state==='ready';
    for(const field of session.fields){field.select.disabled=!editing||field.locked;field.reason.disabled=!editing||field.select.value!=='Leave'||field.locked;}
    if(fillAll)fillAll.disabled=!editing||!block.rows.length;
    changeReason.disabled=!editing;
    const remaining=meal?session.fields.filter(field=>field.select.value==='未确认').length:0;
    save.disabled=!editing||!changed.length||!block.rows.length||!!remaining||requiresReason&&!changeReason.value.trim();
    if(session.state==='ready')status.textContent=meal&&remaining?`还有 ${remaining} 名学生未确认。`:changed.length?`待保存 ${changed.length} 条变更${meal?'，只办理本餐':'，仅本页明确修改的学生'}。`:'暂无变更';
  }
  fillAll?.addEventListener('click',()=>{
    if(registerSession!==session||fillAll.disabled||session.state!=='ready')return;
    for(const field of session.fields)field.select.value='就餐';
    session.editRevision++;update();
    status.textContent=session.dirty?'已填为“就餐”草稿，可修改个别学生；核对后点击“确认本餐”才会保存。':'当前本餐均为“就餐”，未新增变更。';
  });
  async function readBack(origin){
    verify.disabled=true;
    const result=await showBusinessView(target(),{origin});
    if(result.status!=='rendered'&&registerSession===session){status.textContent=(session.state==='saved'?'保存已返回成功，但最新记录回读未完成。':'保存结果尚未核实。')+'请重新读取核对，不要重复提交。';verify.hidden=false;verify.disabled=false;}
  }
  verify.addEventListener('click',()=>{if(registerSession===session&&!verify.disabled)readBack('verify');});
  save.addEventListener('click',async()=>{
    if(registerSession!==session||save.disabled||session.state!=='ready')return;
    const changed=changes();
    if(!meal){
      const invalid=session.fields.find(field=>changed.some(change=>change.student===field.row.student)&&field.select.value==='Leave'&&!field.reason.value.trim());
      if(invalid){status.textContent='请填写新请假的原因后再保存。';invalid.reason.focus?.();return;}
    }
    session.state='saving';update();status.textContent='正在保存，请勿重复提交…';
    try{
      const args={student_group:block.student_group,day:block.day,revision:block.revision,...(meal?{meal:block.meal,students:session.fields.map(field=>({student:field.row.student,value:field.select.value})),confirm:1,change_reason:changeReason.value.trim()}:{changes:changed})};
      const result=await request('/api/method/tongjianyun.classroom.'+(meal?'save_meal':'save_attendance'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(args)});
      if(!result||(meal?result.saved!==true:result.saved!==changed.length))throw Error('保存返回结果不完整，需要回读核对。');
      session.state='saved';session.dirty=false;status.textContent='保存已返回成功，正在读取最新记录…';verify.hidden=false;
      await readBack('saved');
    }catch(error){session.state='uncertain';status.textContent=(error.message||'保存结果未知。')+' 请重新读取并核对，不要直接重复提交。';verify.hidden=false;verify.disabled=false;}
  });
  update();return section;
}
function renderStockRepair(block){
  const validStatus=['not_posted','pending','mismatch','consistent','blocked'];
  const validId=value=>typeof value==='string'&&!!value&&value===value.trim()&&value.length<=140&&!/[\u0000-\u001f]/.test(value);
  if(!['Purchase Receipt','Stock Entry'].includes(block.source_doctype)||!validId(block.source_name)||!/^[a-f0-9]{64}$/.test(block.revision||'')||!validStatus.includes(block.status)||typeof block.can_repair!=='boolean'||!Array.isArray(block.targets)||block.targets.length>20)throw Error('库存核对凭据不完整，不能执行修复。');
  const keys=new Set(),targets=block.targets.map(row=>{
    if(!row||Object.keys(row).some(key=>!['item_code','warehouse'].includes(key))||!validId(row.item_code)||!validId(row.warehouse))throw Error('库存核对目标无效。');
    const key=JSON.stringify([row.item_code,row.warehouse]);if(keys.has(key))throw Error('库存核对目标重复。');keys.add(key);return {item_code:row.item_code,warehouse:row.warehouse};
  });
  if(block.can_repair&&(!['mismatch','blocked'].includes(block.status)||!targets.length))throw Error('库存修复状态不一致，请重新核对。');
  const section=node('section',undefined,'view-section view-register'),session={dirty:false,state:'ready',editRevision:0,kind:'stock'};section.registerSession=session;
  section.append(node('h2','核对后处理'),node('p','调用原生库存汇总重算，同时更新现存数量、价值以及计划、订购、预留、预计等派生数量；不修改原单据、库存流水或估值规则。存在未完成重估时不可执行。','view-note'));
  const footer=node('div',undefined,'view-register-footer'),status=node('p',block.status==='consistent'?'本次读取一致，无需修复。':block.can_repair?`有 ${targets.length} 组差异可申请原生重算，请先核对上表。`:'当前条件不允许修复，请先查看上方核对说明。','view-register-status');
  status.setAttribute('role','status');
  const save=node('button','核对并修复库存汇总','view-register-save'),verify=node('button','重新读取并核对','view-action');save.type=verify.type='button';save.hidden=!block.can_repair;save.disabled=!block.can_repair;
  footer.append(status,verify,save);section.append(footer);Object.assign(session,{status,save,verify});
  const target={view:'stock_reconciliation',source_doctype:block.source_doctype,source_name:block.source_name};
  async function readBack(origin){
    verify.disabled=true;
    const result=await showBusinessView(target,{origin});
    if(result.status!=='rendered'&&registerSession===session){status.textContent='最新核对结果未读取成功，请重新读取。不要重复提交修复。';verify.disabled=false;}
  }
  verify.addEventListener('click',()=>{if(registerSession===session&&!verify.disabled)return readBack('verify');});
  save.addEventListener('click',async()=>{
    if(registerSession!==session||save.disabled||session.state!=='ready')return;
    if(!window.confirm(`确认对来源单 ${block.source_name} 涉及的 ${targets.length} 组差异执行原生库存汇总重算？同时更新现存、价值、计划、订购、预留及预计汇总，不修改来源单或库存流水。`))return;
    session.state='saving';save.disabled=true;verify.disabled=true;status.textContent='正在核验版本并执行原生重算，请勿重复提交…';
    try{
      const result=await request('/api/method/tongjianyun.stock_operations.repair_stock',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({source_doctype:block.source_doctype,source_name:block.source_name,targets,revision:block.revision,confirm:'recalculate'})});
      const returned=Array.isArray(result?.targets)?result.targets:[],returnedKeys=returned.map(row=>JSON.stringify([row?.item_code,row?.warehouse]));
      if(result?.status!=='recalculated'||result.before_revision!==block.revision||returned.length!==targets.length||new Set(returnedKeys).size!==keys.size||returnedKeys.some(key=>!keys.has(key))||!result.inspection||result.inspection.source_doctype!==block.source_doctype||result.inspection.source_name!==block.source_name)throw Error('修复返回结果不完整。');
      session.state='saved';status.textContent='重算已返回，正在重新读取库存与流水核对…';await readBack('saved');
    }catch(error){session.state='uncertain';status.textContent=(error.message||'修复结果未知。')+' 请重新读取并核对，不要直接重复修复。';verify.disabled=false;}
  });
  return section;
}
const renderers={stats:renderStats,table:renderTable,bars:renderBars,notice:renderNotice,frappe_frame:renderFrappeFrame,business_blueprint:renderBlueprint,business_proposal:renderProposal,business_proposal_handoff:renderProposalHandoff,attendance_register:renderAttendance,meal_register:renderMealRegister,stock_repair:renderStockRepair};
export function buildComponents(data){
  if(data?.version!==1||!validViews.has(data.selection?.view)||!Array.isArray(data.components)||data.components.length>12)throw Error('展示结果格式不受支持，已保留当前页面。');
  const content=document.createDocumentFragment();
  for(const block of data.components){if(!Object.hasOwn(renderers,block.type))throw Error('此结果需要更新页面组件，已保留当前内容。');const rendered=renderers[block.type](block);if(rendered.nativeSession||rendered.registerSession){if(content.nativeSession||content.registerSession)throw Error('同一业务视图只能打开一个业务编辑器。');content.nativeSession=rendered.nativeSession;content.registerSession=rendered.registerSession;}content.append(rendered);}
  return content;
}
export async function showBusinessView(choice,options={}){
  if(!choice||!validViews.has(choice.view)||!request)return outcome('failed',undefined,'暂不支持该业务视图。');
  if(options.origin==='refresh'&&loadingTicket)return outcome('blocked',currentViewContext(),'正在切换业务，已跳过自动刷新。');
  // A task finishing is a data refresh, never permission to discard a native form.
  if(nativeSession&&options.origin==='refresh')return outcome('rendered',currentViewContext(),'当前原生页面已保留，未自动重载。');
  if(!mayLeaveNative(options.origin))return outcome('blocked',currentViewContext(),'当前业务有未保存的修改，已保留原页面。');
  const leavingDirty=viewDirty(),leavingRevision=editRevision();
  const turn=++ticket;loadingTicket=turn;notice('正在读取业务数据…');
  try{
    const result=await request('/api/method/tongjianyun.meal_views.get_view?'+new URLSearchParams({selection_json:JSON.stringify(choice)}));
    if(turn!==ticket)return outcome('superseded');
    if(result.version!==1||!validViews.has(result.selection?.view))throw Error('展示结果格式无效。');
    if(registerSession?.state==='saving'&&options.origin!=='saved'){notice('业务正在保存，已保留当前页面。');return outcome('blocked',currentViewContext(),'业务正在保存，请等待读取最新结果。');}
    // An edit made while loading also needs consent, even if the form was clean at the start.
    if(viewDirty()&&(!leavingDirty||editRevision()!==leavingRevision)&&!mayLeaveNative(options.origin)){notice('已保留未保存的业务页面。');return outcome('blocked',currentViewContext(),'当前业务有未保存的修改，已保留原页面。');}
    if(result.selection.view==='recipe_week')return showCalendar(result.selection,{checked:true});
    const fragment=buildComponents(result);
    const actions=(result.actions||[]).map(actionButton);
    disposeNative();nativeSession=fragment.nativeSession||null;registerSession=fragment.registerSession||null;
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
