import {STEPS,MEALS,SLOTS,stepFor,stepBadge,professionalRoute,mealDraft,draftTotals,esc as h,number as n} from './state.js?v=meal-flow-20260923-1';

const $=id=>document.getElementById(id),panel=$('panel');
let data=null,scene=null,scenePromise=null,active=null,selectedRecipe=null,recipeCalendarState=null,weekPayload=null,draftState=null,dirty=false,writing=false,ready=false,embedded=false,sequence=0,loadSequence=0,toastTimer,mobileWeekDay=null;
const notify=(text,error=false)=>{clearTimeout(toastTimer);$('toast').textContent=text;$('toast').hidden=false;$('toast').style.background=error?'#a56554':'';toastTimer=setTimeout(()=>$('toast').hidden=true,error?10000:5000);};
const note=(text,kind='')=>`<div class="note ${kind}">${h(text)}</div>`;
const empty=text=>`<div class="empty">${h(text)}</div>`;
const button=(label,key,name='')=>`<button class="secondary" data-native="${key}" ${name?`data-doc="${h(name)}"`:''}>${h(label)} ↗</button>`;
const status=v=>`<span class="tag ${['待确认','草稿','尚未保存预计'].includes(v)?'warning':''}">${h(v)}</span>`;
const getContext=()=>({day:data.day,meal:data.meal});
function failure(error){return String(error?.message||'业务读取失败，请刷新后重新核对。').slice(0,500);}
async function api(method,args={},write=false){
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),30000);
  try{
    const params=Object.fromEntries(Object.entries(args).map(([k,v])=>[k,typeof v==='object'?JSON.stringify(v):v]));
    const r=await fetch('/api/method/tongjianyun.meal_scene.'+method+(write?'':'?'+new URLSearchParams(params)),{
      method:write?'POST':'GET',credentials:'same-origin',cache:'no-store',signal:controller.signal,
      headers:{Accept:'application/json',...(write?{'Content-Type':'application/json','X-Frappe-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content}:{})},...(write?{body:JSON.stringify(args)}:{})});
    const body=await r.json().catch(()=>({}));
    if(!r.ok||body.exc){
      let message=r.status===403?'当前账号没有该业务权限或登录已失效。':'操作未完成，请刷新并核对原业务记录。';
      try{const row=JSON.parse(body._server_messages||'[]')[0];const item=typeof row==='string'?JSON.parse(row):row;if(item?.message)message=new DOMParser().parseFromString(item.message,'text/html').body.textContent;}catch(_){}
      throw Error(message);
    }
    return body.message;
  }catch(error){if(error.name==='AbortError'||error instanceof TypeError)throw Error(write?'网络中断，保存结果未知。先刷新并查看原单，不要直接重复提交。':'网络中断，当前显示的旧数据不可作为最新状态。');throw error;}
  finally{clearTimeout(timeout);}
}
function message(text='',error=false){$('message').textContent=text;$('message').hidden=!text;$('message').classList.toggle('error',error);}
function leaveDraft(){if(writing)return false;if((dirty||embedded)&&!window.confirm(embedded?'离开原业务面板前，请确认已保存其中的修改。继续吗？':'有未保存的食谱修改，确认放弃并切换吗？'))return false;const hadDraft=!!draftState;dirty=false;draftState=null;embedded=false;panel.classList.remove('embedded-open');if(hadDraft)renderWeekOverview();return true;}
function closePanel(){if(!leaveDraft())return false;++sequence;active=null;panelBody(empty('请选择周历餐次或下方其他业务。'));scene?.focus(null);return true;}
function panelBody(content){$('panel-body').innerHTML=content;$('panel-body').scrollTop=0;}
function revealPanel(){if(window.matchMedia('(max-width:950px)').matches)panel.scrollIntoView({behavior:'smooth',block:'start'});}
function fallback(){ $('render-status').hidden=true;$('fallback').hidden=false;$('labels').hidden=true;scene?.dispose();scene=null; }
function ensureScene(){
  if(scenePromise||!$('scene-preview').open)return;
  scenePromise=import('./scene.js?v=meal-flow-20260923-1').then(({MealScene})=>{
    scene=new MealScene($('canvas'),$('labels'),{onSelect:openStep,onFailure:fallback});
    if(data)scene.setData(data);
    if(active)scene.focus(active);
    $('render-status').hidden=true;
  }).catch(()=>fallback());
}
async function load(automatic=false){
  if(writing||(automatic&&(panel.open||document.hidden)))return;
  const ticket=++loadSequence;ready=false;if(!automatic)message('正在读取所选日期与餐次的业务记录…');$('refresh').disabled=true;
  try{
    const result=await api('get_overview',{day:$('day').value||'',meal:$('meal').value});if(ticket!==loadSequence)return;
    data=result;ready=true;$('day').value=data.day;$('meal').value=data.meal;$('user-label').textContent=data.user_label;
    $('sync').textContent='业务读取 '+String(data.generated_at).slice(11,19);
    document.querySelectorAll('#flow-nav button').forEach(el=>el.title=stepBadge(el.dataset.step,data));
    renderWorklist();renderWeekOverview();scene?.setData(data);message();history.replaceState(null,'','/tongjianyun-meal-scene?'+new URLSearchParams(getContext()));
    if($('scene-preview').open)ensureScene();
    if(!active)await openStep('recipe');
  }catch(error){if(ticket!==loadSequence)return;message(failure(error),true);$('render-status').hidden=true;}
  finally{if(ticket===loadSequence)$('refresh').disabled=false;}
}
$('flow-nav').innerHTML=STEPS.map(s=>`<button data-step="${s.id}" style="--tint:${s.color}" aria-label="${h(s.title)}"><span class="step-num">${s.number}</span><span><strong>${h(s.title)}</strong></span></button>`).join('');
async function openStep(id){
  const step=stepFor(id);if(!step||!ready){notify('请先等待读取成功，或刷新后再操作。');return false;}if(!leaveDraft())return false;
  const ticket=++sequence;active=id;scene?.focus(id);$('panel-title').textContent=step.title;$('panel-number').textContent=step.number;$('panel-subtitle').textContent=step.subtitle;
  panel.style.setProperty('--active-color',step.color);$('panel-context').textContent=`${data.day} · ${MEALS.find(([m])=>m===data.meal)?.[1]} · 仅当前账号可见范围`;
  $('previous-step').disabled=step.number===1;$('next-step').disabled=step.number===8;$('step-position').textContent=step.number+' / 8';
  panel.classList.remove('expanded','embedded-open');if(!panel.open)panel.show();
  document.querySelectorAll('#flow-nav button').forEach(el=>{el.classList.toggle('active',el.dataset.step===id);el.setAttribute('aria-current',el.dataset.step===id?'step':'false');});
  panelBody(empty('正在读取原业务记录…'));
  try{
    if(step.cap&&!data.capabilities[step.cap]&&!(id==='purchase'&&data.capabilities.procurement)){panelBody(note('当前账号没有本环节所需业务权限。不会以空表或零值伪装正常，也不会因进入工作台自动授权。','warning'));return false;}
    if(id==='recipe')await recipesView(ticket);
    else if(id==='purchase')await purchaseView(ticket);
    else if(id==='receipt')await documentView(ticket,'receipt');
    else if(id==='stock')await stockView(ticket);
    else if(id==='kitchen')await kitchenView(ticket);
    else if(id==='dispatch'||id==='dining')plansView(id);
    else await traceView(ticket);
  }catch(error){if(ticket===sequence&&panel.open)panelBody(note(failure(error),'error'));return false;}
  return true;
}
function live(ticket){return ticket===sequence&&panel.open;}
function recipeCreateActions(){return data.capabilities.recipe_create?'<button class="primary" data-sub="recipe-new">新建本周草稿</button><button class="secondary" data-sub="recipe-import">导入 Excel 食谱</button>':note('当前账号没有新建或导入食谱的权限。','warning');}
async function recipesView(ticket,offset=0,all=false){
  if(selectedRecipe&&!all)return recipeView(ticket,selectedRecipe);
  const result=all?await api('get_recipes',{offset}):data.recipes;if(!live(ticket))return;
  if(!all&&result.rows.length===1){selectedRecipe=result.rows[0].name;return recipeView(ticket,selectedRecipe);}
  if(!all&&!result.rows.length){renderEmptyRecipeCalendar();return;}
  panelBody(note(all?'当前账号可见食谱库；食谱日期与当前业务日期不同会单独提示。':'仅显示覆盖所选日期的食谱。草稿不是已发布食谱，存在多份时请明确选择。')+
    `<div class="recipe-list">${result.rows.map(r=>`<button class="recipe-item" data-recipe="${h(r.name)}"><div><b>${h(r.title||r.name)}</b><small>${h(r.week_start)} — ${h(r.week_end)}</small></div>${status(r.workflow_status)}</button>`).join('')||empty('当前范围没有食谱')}</div><div class="buttons"><button class="secondary" id="all-recipes">全部可见食谱</button>${offset?'<button class="secondary" id="previous-recipes">上一页</button>':''}${result.has_more?'<button class="secondary" id="more-recipes">下一页</button>':''}${recipeCreateActions()}</div>`);
  const page=start=>{const next=++sequence;recipesView(next,start,true).catch(e=>live(next)&&panelBody(note(failure(e),'error')));};
  $('all-recipes').onclick=()=>page(0);if($('more-recipes'))$('more-recipes').onclick=()=>page(offset+20);if($('previous-recipes'))$('previous-recipes').onclick=()=>page(Math.max(0,offset-20));
}
function businessWeekDates(day){
  const date=new Date(`${day}T00:00:00Z`),oneDay=86400000,weekday=date.getUTCDay(),monday=date.getTime()-((weekday+6)%7)*oneDay;
  return Array.from({length:5},(_,index)=>new Date(monday+index*oneDay).toISOString().slice(0,10));
}
function renderWorklist(){
  if(!data)return;
  const items=[],summary=data.plans?.summary;
  if(data.capabilities.recipe&&data.recipes.rows.length===0)items.push([data.capabilities.recipe_create?'draft':'recipe',data.capabilities.recipe_create?'开始编排本周食谱':'选择本周食谱','当前日期还没有选定覆盖食谱']);
  if(summary&&summary.visible_groups>summary.planned_groups)items.push(['dispatch','核对预计用餐人数',`${summary.planned_groups} / ${summary.visible_groups} 个可见班已保存预计`]);
  if(summary&&data.day<=data.today&&summary.visible_groups>summary.confirmed_groups)items.push(['dining','确认实际用餐人数',`${summary.confirmed_groups} / ${summary.visible_groups} 个可见班已确认`]);
  const first=items[0]||['recipe','查看本周食谱','当前没有可从已接入数据判定的待办'];
  $('worklist-items').innerHTML=`<button type="button" class="worklist-item" ${first[0]==='draft'?'data-start-draft="1"':`data-step="${first[0]}"`}><span><strong>${h(first[1])}</strong><small>${h(first[2])}</small></span><span aria-hidden="true">→</span></button>${items.length>1?`<p class="worklist-rest">还有 ${items.length-1} 项需核对，可在“其他业务”中查看。</p>`:''}`;
}
function renderWeekOverview(){
  if(!data)return;
  const editing=draftState?.kind==='draft';
  const payload=editing?draftState.payload:weekPayload?.payload||null,recipe=payload?.recipe;
  const dates=editing?recipeWeekDates(recipe,payload.days):businessWeekDates(data.day);
  const covering=editing||!!payload&&dates.some(date=>payload.days.some(day=>day.date===date));
  if(!mobileWeekDay||!dates.includes(mobileWeekDay))mobileWeekDay=dates.includes(data.day)?data.day:dates[0];
  $('week-title').textContent=`${dates[0]} — ${dates.at(-1)}`;
  $('week-caption').textContent=editing?'正在编排草稿；点选周历格子，在右侧修改该餐次，保存前不会写入业务记录。':covering?`${recipe.title||weekPayload.name} · ${recipe.workflowStatus||'状态待核'}；未发布食谱不能作为采购依据。`:weekPayload?'所选食谱不覆盖本周；请选择本周食谱，不能将空白当作未供餐。':'尚未选定本周食谱；空白格不代表该日没有供餐。';
  $('week-selection').textContent=editing?`正在编辑：${draftState.day} · ${MEALS.find(([key])=>SLOTS[key]===draftState.slot)?.[1]||draftState.slot}`:`当前业务：${data.day} · ${MEALS.find(([key])=>key===data.meal)?.[1]||data.meal}`;
  $('week-new').hidden=!data.capabilities.recipe_create;$('week-import').hidden=!data.capabilities.recipe_create;
  $('week-other-recipes').hidden=!data.capabilities.recipe;
  $('week-mobile-day').innerHTML=dates.map(date=>`<option value="${date}" ${date===mobileWeekDay?'selected':''}>${recipeWeekday(date)} · ${date.slice(5)}</option>`).join('');
  $('workbench-week').style.setProperty('--workbench-days',String(dates.length));
  const headers=dates.map(date=>`<div class="workbench-week-day ${date===data.day?'business-day':''} ${date===mobileWeekDay?'mobile-day':''}" data-week-date="${date}"><b>${h(recipeWeekday(date))}</b><span>${h(date.slice(5))}</span></div>`).join('');
  const cells=MEALS.map(([meal,label])=>`<div class="workbench-week-meal">${h(label)}</div>`+dates.map(date=>{
    const portion=covering?recipePortion(payload,date,SLOTS[meal]):null,dishes=portion?.dishes||[];
    const current=editing?date===draftState.day&&SLOTS[meal]===draftState.slot:date===data.day&&meal===data.meal;
    const text=dishes.length?dishes.slice(0,2).join(' · '):covering?'未编排':'待选择食谱';
    return `<button type="button" class="workbench-week-cell ${current?'selected':''} ${date===mobileWeekDay?'mobile-day':''} ${dishes.length?'':'unplanned'}" data-workbench-date="${date}" data-workbench-meal="${meal}" aria-pressed="${current}" aria-label="${h(date+' '+label+'：'+(dishes.join('、')||text))}"><b>${h(text)}</b>${dishes.length>2?`<small>另有 ${dishes.length-2} 道菜</small>`:''}</button>`;
  }).join('')).join('');
  $('workbench-week').innerHTML='<div class="workbench-week-axis">餐次</div>'+headers+cells;
}
function renderEmptyRecipeCalendar(){
  const dates=businessWeekDates(data.day),grid=`<div class="recipe-week-scroll"><div class="recipe-week-grid" style="--week-columns:5;min-width:512px" role="group" aria-label="尚未选择食谱的五餐周历"><div class="recipe-week-axis">餐次</div>${dates.map(date=>`<div class="recipe-week-day ${date===data.day?'business-day':''}"><b>${h(recipeWeekday(date))}</b><span>${h(date.slice(5))}</span></div>`).join('')}${MEALS.map(([key,label])=>`<div class="recipe-week-meal">${h(label)}</div>${dates.map(date=>`<div class="recipe-week-cell unplanned ${date===data.day&&key===data.meal?'business-current':''}" aria-label="${h(date+' '+label+'：未选择食谱')}"><b>未选择食谱</b></div>`).join('')}`).join('')}</div></div>`;
  panelBody(`<div class="recipe-week-heading"><div><small>当前日期暂无覆盖食谱</small><h3>${h(dates[0])} — ${h(dates[4])}</h3><span>五天 × 五餐</span></div></div>`+note('所选日期没有覆盖食谱。以下是待选择的周历占位，不代表其他日期也未编排，不能作为供餐或采购依据。','warning')+grid+`<p class="recipe-week-swipe">左右滑动查看其余日期</p><section class="recipe-calendar-preview">可在周历中编排草稿，或导入 Excel 识别后校对；保存前不会创建食谱。</section><div class="recipe-week-actions"><button class="secondary" data-sub="recipe-library">查看已有食谱</button>${recipeCreateActions()}</div>`);
}
function beginRecipeDraft(){
  if(!data.capabilities.recipe_create)return notify('当前账号没有新建食谱权限。',true);
  if(!leaveDraft())return;
  const dates=businessWeekDates(data.day);
  draftState={kind:'draft',source:'new',payload:{recipe:{title:`${dates[0]} — ${dates[4]} 周食谱`,weekStart:dates[0],weekEnd:dates[4],workflowStatus:'草稿'},days:dates.map((date,index)=>({id:`DAY-${index+1}`,date,day:recipeWeekday(date),portions:[],version:1}))},day:dates.includes(data.day)?data.day:dates[0],slot:SLOTS[data.meal],warnings:[]};
  dirty=true;renderDraftEditor();
}
async function beginRecipeEdit(){
  if(!selectedRecipe||!data.capabilities.recipe_write)return notify('当前账号没有编辑食谱权限。',true);
  if(!leaveDraft())return;
  const ticket=sequence,name=selectedRecipe;
  try{
    const result=await api('get_recipe',{recipe:name});
    if(!live(ticket)||selectedRecipe!==name)return;
    if(!result.edit||result.edit.mode==='none')return notify(result.edit?.reason||'当前食谱不能在此编辑。',true);
    const payload=JSON.parse(JSON.stringify(result.payload));
    if(result.edit.mode==='copy')payload.recipe.title=(payload.recipe.title||name).slice(0,132)+' · 修订草稿';
    draftState={kind:'draft',source:'edit',editMode:result.edit.mode,recipe:name,revision:result.revision,
      payload,day:recipeCalendarState?.day,slot:recipeCalendarState?.slot||SLOTS[data.meal],warnings:[]};
    dirty=false;renderDraftEditor();
  }catch(error){if(live(ticket))notify(failure(error),true);}
}
function draftDay(date){
  let day=draftState.payload.days.find(item=>item.date===date);
  if(!day){day={id:`DAY-${draftState.payload.days.length+1}`,date,day:recipeWeekday(date),portions:[],version:1};draftState.payload.days.push(day);draftState.payload.days.sort((a,b)=>a.date.localeCompare(b.date));}
  if(!Array.isArray(day.portions))day.portions=[];
  return day;
}
function draftPortion(date,slot,create=false){
  const day=create?draftDay(date):draftState.payload.days.find(item=>item.date===date);
  if(!day)return null;
  let portion=(day.portions||[]).find(item=>item.slot===slot);
  if(!portion&&create){portion={slot,label:MEALS.find(([key])=>SLOTS[key]===slot)?.[1]||slot,dishes:[],dishIngredientRows:[]};day.portions.push(portion);}
  return portion||null;
}
function captureDraftEditor(){
  if(!draftState||draftState.kind!=='draft'||!$('draft-title'))return;
  draftState.payload.recipe.title=$('draft-title').value.trim();
  const portion=draftPortion(draftState.day,draftState.slot,true);
  portion.dishes=$('draft-dishes').value.split(/\r?\n/).map(value=>value.trim()).filter(Boolean);
  portion.dishIngredientRows=[...document.querySelectorAll('.draft-ingredient-row')].map(row=>({dishName:row.querySelector('[data-field="dish"]').value.trim(),ingredient:row.querySelector('[data-field="ingredient"]').value.trim(),amount:row.querySelector('[data-field="amount"]').value.trim(),unit:row.querySelector('[data-field="unit"]').value.trim()})).filter(row=>row.dishName||row.ingredient||row.amount);
}
function renderDraftEditor(){
  const {payload}=draftState,dates=recipeWeekDates(payload.recipe,payload.days);
  if(!dates.length){panelBody(note('识别结果没有可用日期，请重新导入。','error')+'<button class="secondary" data-sub="recipe-import">重新导入</button>');return;}
  payload.recipe.weekStart=payload.recipe.weekStart||dates[0];payload.recipe.weekEnd=payload.recipe.weekEnd||dates[dates.length-1];
  draftState.day=dates.includes(draftState.day)?draftState.day:dates.includes(data.day)?data.day:dates[0];
  draftState.slot=draftState.slot||SLOTS[data.meal];
  const portion=draftPortion(draftState.day,draftState.slot),dishes=portion?.dishes||[],rows=portion?.dishIngredientRows||[];
  const meal=MEALS.find(([key])=>SLOTS[key]===draftState.slot)?.[1]||draftState.slot;
  const grid=`<div class="recipe-week-scroll"><div class="recipe-week-grid" style="--week-columns:${dates.length};min-width:${52+dates.length*92}px" role="group" aria-label="编辑周食谱"><div class="recipe-week-axis">餐次</div>${dates.map(date=>`<div class="recipe-week-day ${date===data.day?'business-day':''}"><b>${h(recipeWeekday(date))}</b><span>${h(date.slice(5))}</span></div>`).join('')}${MEALS.map(([key,label])=>`<div class="recipe-week-meal">${h(label)}</div>${dates.map(date=>{const slot=SLOTS[key],names=draftPortion(date,slot)?.dishes||[],selected=date===draftState.day&&slot===draftState.slot;return `<button type="button" class="recipe-week-cell ${names.length?'':'unplanned'} ${selected?'selected':''}" data-draft-day="${h(date)}" data-draft-slot="${h(slot)}" aria-pressed="${selected}" aria-label="${h(date+' '+label+'：'+(names.join('、')||'待编排'))}"><b>${h(names.slice(0,2).join(' · ')||'待编排')}</b></button>`;}).join('')}`).join('')}</div></div>`;
  const ingredients=rows.map((row,index)=>`<div class="draft-ingredient-row"><input data-field="dish" aria-label="所属菜品" placeholder="所属菜品" value="${h(row.dishName||'')}"><input data-field="ingredient" aria-label="食材名称" placeholder="食材" value="${h(row.ingredient||'')}"><input data-field="amount" aria-label="每生用量" type="number" min="0" step="any" placeholder="用量" value="${h(row.amount??'')}"><input data-field="unit" aria-label="单位" placeholder="单位" value="${h(row.unit||'g')}"><button type="button" class="secondary" data-draft-remove="${index}" aria-label="移除此食材">移除</button></div>`).join('');
  const warnings=(draftState.warnings||[]).slice(0,20).map(item=>`<li>${h(String(item))}</li>`).join('');
  const editing=draftState.source==='edit',copy=editing&&draftState.editMode==='copy';
  const editorLabel=draftState.source==='import'?'Excel 识别结果 · 待校对':copy?'修订已有食谱 · 原记录不变':editing?'编辑已有草稿 · 尚未保存':'新建食谱 · 尚未保存';
  const saveLabel=copy?'另存为修订草稿':editing?'保存草稿修改':'保存为草稿';
  panelBody(`<section id="recipe-draft-editor" class="recipe-draft-editor"><div class="recipe-week-heading"><div><small>${editorLabel}</small><h3>${h(payload.recipe.weekStart)} — ${h(payload.recipe.weekEnd)}</h3><span>${copy?'保存后生成独立草稿，不覆盖原食谱':'保存后仅为草稿，不自动发布或采购'}</span></div></div>${editing?note(copy?'原食谱已发布、关联业务或含锁定日期。此次修改将创建新草稿；原食谱及其采购关联保持不变。':'只修改当前未关联业务的草稿。若他人已更新，保存时会提示刷新。',copy?'warning':''):''}${warnings?note(`导入有 ${draftState.warnings.length} 项提醒，请逐项核对。`,'warning')+`<details class="draft-warnings"><summary>查看导入提醒</summary><ul>${warnings}</ul></details>`:''}<label class="field"><span>食谱名称</span><input id="draft-title" maxlength="140" value="${h(payload.recipe.title||'')}"></label>${grid}<p class="recipe-week-swipe">左右滑动查看其余日期</p><section class="recipe-calendar-preview"><div class="recipe-preview-heading"><div><small>点选周历格子编辑</small><h3>${h(draftState.day)} ${h(recipeWeekday(draftState.day))} · ${h(meal)}</h3></div></div><label class="field"><span>菜品名称 · 每行一道</span><textarea id="draft-dishes" rows="5" placeholder="例如：米饭&#10;清炒时蔬">${h(dishes.join('\n'))}</textarea></label><h4>每生食材用量</h4><p class="muted">食材须填写所属菜品、名称、用量和单位；可先只编排菜品，稍后补充食材。</p><div id="draft-ingredients">${ingredients||'<p class="muted">暂无食材明细</p>'}</div><button type="button" class="secondary" id="draft-add-ingredient">＋ 添加食材</button></section><div class="recipe-week-actions"><button type="button" class="primary" id="draft-save">${saveLabel}</button><button type="button" class="secondary" data-sub="draft-cancel">取消</button></div>${note('保存草稿可能安排后台食材物料匹配；不会自动发布、创建采购需求或付款。')}</section>`);
  mobileWeekDay=draftState.day;renderWeekOverview();
  $('draft-add-ingredient').onclick=()=>{captureDraftEditor();const selected=draftPortion(draftState.day,draftState.slot,true);selected.dishIngredientRows.push({dishName:selected.dishes[0]||'',ingredient:'',amount:'',unit:'g'});dirty=true;const top=$('panel-body').scrollTop;renderDraftEditor();$('panel-body').scrollTop=top;};
  $('draft-save').onclick=saveRecipeDraft;
}
async function saveRecipeDraft(){
  if(!draftState||draftState.kind!=='draft')return;
  captureDraftEditor();
  if(!draftState.payload.recipe.title)return notify('请填写食谱名称。',true);
  const method=draftState.source==='edit'?'save_recipe_edit':'create_recipe_draft';
  const args=draftState.source==='edit'?{recipe:draftState.recipe,revision:draftState.revision,payload:draftState.payload}:{payload:draftState.payload,...(draftState.importId?{import_id:draftState.importId}:{})};
  const result=await save(method,args);
  if(!result?.name)return;
  draftState=null;selectedRecipe=result.name;recipeCalendarState=null;
  await load();
  const ticket=++sequence;
  try{await recipeView(ticket,result.name);}catch(error){if(live(ticket))panelBody(note(failure(error),'error'));}
}
async function uploadRecipeFile(file){
  const form=new FormData();form.append('file',file,file.name);form.append('is_private','1');
  const response=await fetch('/api/method/upload_file',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{Accept:'application/json','X-Frappe-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:form});
  const body=await response.json().catch(()=>({}));
  if(!response.ok||!body.message?.file_url)throw Error('上传未完成，请确认文件格式、大小和当前账号的文件权限。');
  return body.message.file_url;
}
function beginRecipeImport(){
  if(!data.capabilities.recipe_create)return notify('当前账号没有导入食谱权限。',true);
  if(!leaveDraft())return;
  draftState={kind:'import'};
  panelBody(`<div class="recipe-week-heading"><div><small>导入周食谱 · 工作台内校对</small><h3>选择 Excel 食谱</h3><span>仅支持 .xlsx，最大 10 MB</span></div></div>${note('上传后由现有识别服务提取菜品和每生带量。识别结果先在周历中校对；只有点击“保存为草稿”才创建食谱。','warning')}<label class="field"><span>食谱文件</span><input id="recipe-import-file" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"></label><div class="recipe-week-actions"><button class="primary" id="recipe-import-start">上传并识别</button><button class="secondary" data-sub="draft-cancel">取消</button></div><p id="recipe-import-status" role="status" aria-live="polite" class="muted">尚未上传文件</p>`);
  $('recipe-import-start').onclick=async()=>{
    const file=$('recipe-import-file').files?.[0];
    if(!file||!file.name.toLowerCase().endsWith('.xlsx')||file.size>10*1024*1024)return notify('请选择不超过 10 MB 的 .xlsx 食谱文件。',true);
    const current=draftState,ticket=sequence,button=$('recipe-import-start'),statusEl=$('recipe-import-status');button.disabled=true;$('recipe-import-file').disabled=true;
    try{
      statusEl.textContent='正在安全上传文件…';const fileUrl=await uploadRecipeFile(file);if(current!==draftState||ticket!==sequence)return;
      statusEl.textContent='正在创建识别任务…';const started=await api('start_recipe_import',{file_url:fileUrl},true);if(!started?.import_id)throw Error('识别任务未创建。');
      for(let attempt=0;attempt<240;attempt++){
        if(current!==draftState||ticket!==sequence)return;
        const state=await api('get_recipe_import_status',{import_id:started.import_id});
        if(current!==draftState||ticket!==sequence)return;
        statusEl.textContent=`${state.message||'正在识别…'} ${Number(state.progress||0)}%`;
        if(state.status==='failed')throw Error(state.message||'识别失败，请检查文件。');
        if(state.status==='completed'){
          const payload=state.result?.payload;if(!payload?.recipe||!Array.isArray(payload.days)||!payload.days.length)throw Error('识别结果没有可用食谱内容。');
          payload.recipe.workflowStatus='草稿';delete payload.recipe.recipeId;
          payload.days.forEach(day=>{day.portions=Array.isArray(day.portions)?day.portions:[];day.portions.forEach(portion=>{portion.dishes=Array.isArray(portion.dishes)?portion.dishes:[];portion.dishIngredientRows=Array.isArray(portion.dishIngredientRows)?portion.dishIngredientRows:[];});});
          draftState={kind:'draft',source:'import',importId:started.import_id,payload,day:null,slot:SLOTS[data.meal],warnings:Array.isArray(state.result?.warnings)?state.result.warnings:[]};dirty=true;renderDraftEditor();return;
        }
        await new Promise(resolve=>setTimeout(resolve,1500));
      }
      throw Error('识别仍在后台运行；请稍后重新导入或联系管理员查询任务。');
    }catch(error){if(current===draftState&&ticket===sequence){statusEl.textContent=failure(error);button.disabled=false;$('recipe-import-file').disabled=false;}}
  };
}
function recipeWeekDates(recipe,days){
  const start=Date.parse(`${recipe.weekStart}T00:00:00Z`),end=Date.parse(`${recipe.weekEnd}T00:00:00Z`),oneDay=86400000;
  if(Number.isFinite(start)&&Number.isFinite(end)&&end>=start&&end-start<=6*oneDay){
    return Array.from({length:Math.round((end-start)/oneDay)+1},(_,index)=>new Date(start+index*oneDay).toISOString().slice(0,10));
  }
  return [...new Set(days.map(day=>day.date).filter(Boolean))].sort();
}
function recipeWeekday(date){const day=new Date(`${date}T00:00:00Z`).getUTCDay();return ['周日','周一','周二','周三','周四','周五','周六'][day]||'';}
function recipePortion(payload,date,slot){return payload.days.find(day=>day.date===date)?.portions.find(portion=>portion.slot===slot)||null;}
function renderRecipePreview(){
  if(!recipeCalendarState||!$('recipe-calendar-preview'))return;
  const {payload,day,slot}=recipeCalendarState,meal=MEALS.find(([key])=>SLOTS[key]===slot)?.[1]||slot,portion=recipePortion(payload,day,slot);
  const current=day===data.day&&slot===SLOTS[data.meal];
  document.querySelectorAll('.recipe-week-cell').forEach(cell=>{const selected=cell.dataset.calendarDay===day&&cell.dataset.calendarSlot===slot;cell.classList.toggle('selected',selected);cell.setAttribute('aria-pressed',String(selected));});
  const ingredients=portion?.dishIngredientRows||[];
  $('recipe-calendar-preview').innerHTML=`<div class="recipe-preview-heading"><div><small>${current?'当前业务餐次':'周历预览 · 顶部业务日期/餐次不变'}</small><h3>${h(day)} ${h(recipeWeekday(day))} · ${h(meal)}</h3></div><span>${portion?.dishes.length||0} 道菜</span></div>`+
    (portion?.dishes.length?`<div class="recipe-preview-dishes">${portion.dishes.map(dish=>`<span>${h(dish)}</span>`).join('')}</div><details class="recipe-ingredients"><summary>查看食材明细 · ${ingredients.length} 项</summary>${ingredients.length?`<div class="table-wrap"><table><thead><tr><th>菜品</th><th>食材</th><th>每生用量</th></tr></thead><tbody>${ingredients.map(row=>`<tr><td>${h(row.dishName)}</td><td>${h(row.ingredient)}</td><td>${h(n(row.amount))} ${h(row.unit)}</td></tr>`).join('')}</tbody></table></div>`:note('该餐次尚无食材明细，可在本页编辑食谱时补充。','warning')}</details>`:note('该日期与餐次在所选食谱中尚未编排；不能用其他餐次代替。','warning'));
}
function renderRecipeCalendar(){
  const {payload}=recipeCalendarState,r=payload.recipe,dates=recipeWeekDates(r,payload.days);
  if(!dates.length){panelBody(note('该食谱尚无可见日期或菜品，请核对原食谱。','warning')+`<div class="buttons"><button class="secondary" data-sub="recipe-library">选择另一份食谱</button>${recipeCreateActions()}</div>`);return;}
  recipeCalendarState.day=dates.includes(recipeCalendarState.day)?recipeCalendarState.day:dates.includes(data.day)?data.day:dates[0];
  recipeCalendarState.slot=recipeCalendarState.slot||SLOTS[data.meal];
  const covering=dates.includes(data.day),published=r.workflowStatus==='已发布';
  const heading=`<div class="recipe-week-heading"><div><small>所选食谱 · ${h(r.workflowStatus||'状态待核')}</small><h3>${h(r.title||selectedRecipe)}</h3><span>${h(r.weekStart)} — ${h(r.weekEnd)}</span></div><button class="secondary" data-sub="recipe-library">更换食谱</button></div>`;
  const context=covering?'点选任一格预览菜品；不会改动顶部业务日期和餐次。':'这份食谱不覆盖顶部所选业务日期；周历仅供预览，不能直接作为该日餐次依据。';
  const grid=`<div class="recipe-week-scroll"><div class="recipe-week-grid" style="--week-columns:${dates.length};min-width:${52+dates.length*92}px" role="group" aria-label="按日期与餐次预览周食谱"><div class="recipe-week-axis">餐次</div>${dates.map(date=>`<div class="recipe-week-day ${date===data.day?'business-day':''}"><b>${h(recipeWeekday(date))}</b><span>${h(date.slice(5))}</span></div>`).join('')}${MEALS.map(([key,label])=>`<div class="recipe-week-meal">${h(label)}</div>${dates.map(date=>{const slot=SLOTS[key],portion=recipePortion(payload,date,slot),dishes=portion?.dishes||[],current=date===data.day&&slot===SLOTS[data.meal];return `<button type="button" class="recipe-week-cell ${dishes.length?'':'unplanned'} ${current?'business-current':''}" data-calendar-day="${h(date)}" data-calendar-slot="${h(slot)}" aria-pressed="false" aria-label="${h(date+' '+label+'：'+(dishes.join('、')||'未编排'))}"><b>${h(dishes.slice(0,2).join(' · ')||'未编排')}</b>${dishes.length>2?`<small>另有 ${dishes.length-2} 道</small>`:''}</button>`;}).join('')}`).join('')}</div></div>`;
  const edit=recipeCalendarState.edit,editAction=edit?.mode==='none'?note(edit.reason,'warning'):`<button class="secondary" data-sub="recipe-edit">${edit?.mode==='copy'?'以此生成修订草稿':'编辑当前草稿'}</button>`;
  panelBody(heading+note(context,covering?'':'warning')+(!published?note('该食谱尚未发布。可预览，但不能当作已发布采购依据。','warning'):'')+grid+`<p class="recipe-week-swipe">左右滑动查看其余日期</p><section id="recipe-calendar-preview" class="recipe-calendar-preview" aria-live="polite"></section>`+note('营养为按现有规则估算的周日均每生供给量，不是所选单餐的实测摄入。发布及采购结算仍须按原流程单独确认。')+`<div class="recipe-week-actions"><button class="primary" data-sub="nutrition">查看整周营养估算 →</button>${editAction}${recipeCreateActions()}</div>`);
  renderRecipePreview();
}
async function recipeView(ticket,name){
  const result=await api('get_recipe',{recipe:name});if(!live(ticket))return;selectedRecipe=name;
  const previous=recipeCalendarState?.name===name?recipeCalendarState:null;
  recipeCalendarState={name,payload:result.payload,revision:result.revision,edit:result.edit,day:previous?.day||null,slot:previous?.slot||null};
  weekPayload={name,payload:result.payload};renderWeekOverview();
  renderRecipeCalendar();
}
async function nutritionView(){
  if(!selectedRecipe)return chooseFirst('请先选择要分析的食谱。');
  const ticket=++sequence;panelBody(empty('正在按现有营养规则计算…'));
  try{const result=await api('nutrition',{recipe:selectedRecipe,garden_ratio:80});if(!live(ticket))return;
    const labels={energy:['能量','kcal'],protein:['蛋白质','g'],calcium:['钙','mg'],iron:['铁','mg'],zinc:['锌','mg'],vitamin_a:['维生素 A','μg'],vitamin_c:['维生素 C','mg']};
    panelBody(note(result.basis)+`<h3>${h(result.recipe.title)}</h3><p class="muted">整周营养估算 · ${h(result.standard_label)} · 园内供给目标 ${h(result.garden_ratio)}%</p><div class="metric-grid">${Object.entries(labels).map(([key,[label,unit]])=>{const e=result.evaluations[key];return `<div class="metric"><span>${label}</span><b>${h(n(result.nutrients[key]))} <small>${unit}</small></b><small>${e?h(e.status)+' · 目标 '+h(n(e.garden_target))+' '+unit:'未配置评价规则'}</small></div>`;}).join('')}</div>`+note(result.conclusion)+`<div class="buttons">${button('调整标准 / 导出分析报表','nutrition')}<button class="secondary" data-sub="recipe-back">返回周历</button></div>`);
  }catch(error){if(live(ticket))panelBody(note(failure(error),'error'));}
}
function chooseFirst(text){notify(text);selectedRecipe=null;recipeCalendarState=null;weekPayload=null;renderWeekOverview();openStep('recipe');}
async function documentView(ticket,kind,offset=0){
  const result=offset===0?(kind==='order'?data.orders:data.receipts):await api('get_documents',{day:data.day,kind,offset});if(!live(ticket))return;
  const prefix=kind==='order'?'<button class="primary" id="new-demand">从食谱预览采购需求</button>':'';
  panelBody(note(result.note)+`<p class="muted">${h(result.start)} — ${h(result.end)} · ${result.rows.length}${result.has_more?'＋':''} 条本页记录，非全量计数</p>`+
    `<div class="buttons">${prefix}${button(kind==='order'?'原采购订单 / 供应商':'原收货单 / 实际验收',kind==='order'?'orders':'receipts')}${kind==='order'?button('查看采购需求草稿','requests'):''}</div>`+
    (result.available?`<div class="table-wrap"><table><thead><tr><th>单据</th><th>日期</th><th>供应商</th><th>状态</th><th>金额</th><th></th></tr></thead><tbody>${result.rows.map(r=>`<tr><td>${h(r.name)}</td><td>${h(r[result.date_field])}</td><td>${h(r.supplier_name)}</td><td>${status((r.docstatus===0?'草稿 · ':'')+(r.status||''))}</td><td>${h(n(r.grand_total))} ${h(r.currency)}</td><td>${button('打开原单',kind,r.name)}</td></tr>`).join('')||'<tr><td colspan="6">该范围暂无可见单据</td></tr>'}</tbody></table></div>`:note('当前没有该单据的读取权限。','warning'))+
    `<div class="buttons">${offset?'<button class="secondary" id="doc-prev">上一页</button>':''}${result.has_more?'<button class="secondary" id="doc-next">下一页</button>':''}</div>`+
    (kind==='receipt'?note('新建、验收、部分收货、退货、提交与库存入账沿用原 ERPNext 单据。打开工作台不会自动登记到货或生成付款。','warning'):''));
  if($('new-demand'))$('new-demand').onclick=demandView;
  const page=start=>{const next=++sequence;documentView(next,kind,start).catch(e=>live(next)&&panelBody(note(failure(e),'error')));};
  if($('doc-prev'))$('doc-prev').onclick=()=>page(Math.max(0,offset-20));if($('doc-next'))$('doc-next').onclick=()=>page(offset+20);
}
async function purchaseView(ticket){return documentView(ticket,'order');}
async function demandView(){
  if(!data.capabilities.procurement)return notify('需要食谱和采购需求的现有权限。',true);
  if(!selectedRecipe)return chooseFirst('请先选择已发布的食谱，再到第 2 站生成需求。');
  if(!leaveDraft())return;const ticket=++sequence;panelBody(empty('正在读取食谱、默认仓库、人数和物料匹配…'));
  try{
    const result=await api('prepare_demand',{recipe:selectedRecipe});if(!live(ticket))return;
    if(result.impact.requests.length){panelBody(note(result.impact.message,'warning')+note('该食谱已有关联采购需求，不重复生成；请核对原单，必要时创建食谱修订版。')+`<div class="buttons">${result.impact.requests.map(r=>button(r.name,'request',r.name)).join('')}</div>`);return;}
    const prepared=result.prepared;
    panelBody(note('这里仅生成采购需求草稿。顺序为：核对预计人数 → 核对物料 / 毛料换算 → 预览 → 明确创建。不会自动提交订单、收货、发票或付款。')+
      `<p class="muted">${h(result.scope.company)} · ${h(result.scope.warehouse)} · 所选食谱 ${h(selectedRecipe)}</p><h3 class="section-title">每天 / 每餐预计备餐人数</h3><div class="table-wrap"><table><thead><tr><th>日期 / 餐次</th><th>人数</th><th>来源</th></tr></thead><tbody>${prepared.meals.map((r,i)=>`<tr><td>${h(r.date)} ${h(MEALS.find(([k])=>SLOTS[k]===r.slot)?.[1]||r.slot)}</td><td><input class="demand-count" data-i="${i}" type="number" min="0" step="1" value="${r.count==null?'':h(r.count)}" aria-label="${h(r.date+' '+r.slot)}预计人数"></td><td class="wrap">${h(r.basis)}</td></tr>`).join('')}</tbody></table></div>`+
      `<h3 class="section-title">食材与单位映射</h3><div class="table-wrap"><table><thead><tr><th>食材 / 来源单位</th><th>物料编号</th><th>库存单位</th><th>换算系数</th><th>依据</th></tr></thead><tbody>${prepared.ingredients.map((r,i)=>`<tr><td>${h(r.ingredient)} / ${h(r.source_uom)}</td><td><input class="demand-item" data-i="${i}" value="${h(r.item_code)}" aria-label="${h(r.ingredient)}物料编号"></td><td><input class="demand-uom" data-i="${i}" value="${h(r.uom)}" aria-label="${h(r.ingredient)}库存单位"></td><td><input class="demand-factor" data-i="${i}" type="number" min="0.000001" step="any" value="${r.factor==null?'':h(r.factor)}" aria-label="${h(r.ingredient)}毛料换算"></td><td>${h(r.basis)}</td></tr>`).join('')}</tbody></table></div>`+
      note('同名只是候选；无法确定自制 / 外购或单位关系时，请在原食谱模块处理。这里不会猜测、自动建物料、抵扣库存或补录历史日期。','warning')+
      `<div class="form-actions"><span class="muted">核对过的预计人数不代表已出餐或已就餐。</span>${button('专业物料匹配','recipe')}<button class="primary" id="preview-demand">预览需求草稿 →</button></div>`);
    $('panel-body').querySelectorAll('input').forEach(el=>el.oninput=()=>dirty=true);
    $('preview-demand').onclick=async()=>{
      const meals={},mappings={};
      for(const [i,r] of prepared.meals.entries()){const raw=panel.querySelector(`.demand-count[data-i="${i}"]`).value;if(raw===''||!Number.isInteger(Number(raw))||Number(raw)<0)return notify('请完整填写非负整数人数，零人可以保留。',true);meals[r.key]=Number(raw);}
      for(const [i,r] of prepared.ingredients.entries()){const val=cls=>panel.querySelector(`.${cls}[data-i="${i}"]`).value.trim();mappings[r.key]={item_code:val('demand-item'),uom:val('demand-uom'),factor:Number(val('demand-factor'))};if(!mappings[r.key].item_code||!mappings[r.key].uom||!Number.isFinite(mappings[r.key].factor)||mappings[r.key].factor<=0)return notify('请核对物料编号、库存单位与有效换算系数。',true);}
      $('preview-demand').disabled=true;
      try{const args={recipe:selectedRecipe,mappings,meals},preview=await api('preview_demand',args);if(!live(ticket))return;demandPreview(preview,args,ticket);}catch(error){notify(failure(error),true);if($('preview-demand'))$('preview-demand').disabled=false;}
    };
  }catch(error){if(live(ticket))panelBody(note(failure(error),'error')+`<div class="buttons">${button('核对原食谱状态与配置','recipe')}</div>`);}
}
function demandPreview(preview,args,ticket){
  panelBody(note('请复核以下草稿：不会扣减库存，不会创建订单、收货、发票或付款。提交前服务端会再次核对食谱、人数、单位及是否已有需求。','warning')+
    `<p class="muted">${h(preview.company)} · ${h(preview.warehouse)}</p><div class="table-wrap"><table><thead><tr><th>需求日期</th><th>食材</th><th>数量</th><th>单位</th><th>参考单价</th></tr></thead><tbody>${preview.lines.map(r=>`<tr><td>${h(r.schedule_date)}</td><td>${h(r.item_name)}</td><td>${h(n(r.qty))}</td><td>${h(r.uom)}</td><td>${h(n(r.rate))}</td></tr>`).join('')}</tbody></table></div>`+
    `<div class="form-actions"><span class="muted">缺少价格不展示成零价；价格与收货付款仍在原采购流程复核。</span><button class="secondary" id="demand-back">重新核对</button><button class="primary" id="create-demand">确认创建采购需求草稿</button></div>`);
  dirty=true;$('demand-back').onclick=demandView;
  $('create-demand').onclick=async()=>{if(!window.confirm('确认只创建本次采购需求草稿？不会下单、收货或付款。'))return;const result=await save('create_demand',{...args,token:preview.token,confirmed:1});if(!result||!live(ticket))return;panelBody(note('采购需求草稿已创建。请在原采购流程审核后继续；这不是采购完成或供餐完成。')+`<div class="buttons">${button('打开需求 '+result.name,'request',result.name)}</div>`);};
}
async function stockView(ticket,warehouse='',offset=0){
  const result=await api('get_stock',{warehouse,offset});if(!live(ticket))return;
  panelBody(note(result.basis||'暂无可见仓库')+`<label class="field"><span>仓库</span><select id="stock-warehouse">${result.warehouses.map(w=>`<option value="${h(w.name)}" ${w.name===result.warehouse?'selected':''}>${h(w.name)} · ${h(w.company)}</option>`).join('')}</select></label><p class="muted">当前账面读取：${h(result.generated_at||'—')}，不是 ${h(data.day)} 的历史库存。</p>`+
    `<div class="table-wrap"><table><thead><tr><th>物料</th><th>账面数量</th><th>预计数量</th><th>已订未入库</th><th>单位</th></tr></thead><tbody>${result.rows.map(r=>`<tr><td>${h(r.item_name||r.item_code)}</td><td>${h(n(r.actual_qty))}</td><td>${h(n(r.projected_qty))}</td><td>${h(n(r.ordered_qty))}</td><td>${h(r.stock_uom)}</td></tr>`).join('')||'<tr><td colspan="5">当前范围暂无库存行；不将缺少记录视为安全库存充足。</td></tr>'}</tbody></table></div>`+
    `<div class="buttons">${offset?'<button class="secondary" id="stock-prev">上一页</button>':''}${result.has_more?'<button class="secondary" id="stock-next">下一页</button>':''}${button('原库存余额报表','stock')}${button('物料与库存设置','items')}</div>`+note('本期没有虚构低库存阈值、保质期预警、冷库温度或检验合格率。','warning'));
  const page=(warehouse,start)=>{const next=++sequence;stockView(next,warehouse,start).catch(e=>live(next)&&panelBody(note(failure(e),'error')));};
  $('stock-warehouse').onchange=()=>page($('stock-warehouse').value,0);if($('stock-prev'))$('stock-prev').onclick=()=>page(result.warehouse,Math.max(0,offset-20));if($('stock-next'))$('stock-next').onclick=()=>page(result.warehouse,offset+20);
}
async function kitchenView(ticket){
  if(!selectedRecipe){panelBody(note('先在第 1 站选择食谱，然后在这里查看所选日期 / 餐次的配方带量。')+`<div class="buttons"><button class="primary" data-step="recipe">选择食谱 →</button></div>`+note('加工执行、温度、留样、消毒未接入。本场景不显示锅灶正在工作或留样合格的实时状态。','warning'));return;}
  const result=await api('get_recipe',{recipe:selectedRecipe});if(!live(ticket))return;const day=result.payload.days.find(d=>d.date===data.day),portion=day?.portions.find(p=>p.slot===SLOTS[data.meal]);
  panelBody(note('当前是备餐配方参考，不是加工执行记录。每生带量来自原食谱，不能仅按人物动作判断已经加工。')+`<h3>${h(result.payload.recipe.title)}</h3><p class="muted">${h(data.day)} · ${h(MEALS.find(([m])=>m===data.meal)?.[1])} · ${h(result.payload.recipe.workflowStatus)}</p>`+
    (portion?`<h3 class="section-title">${h(portion.dishes.join(' · '))}</h3><div class="table-wrap"><table><thead><tr><th>菜品</th><th>食材</th><th>每生用量</th><th>单位</th></tr></thead><tbody>${portion.dishIngredientRows.map(r=>`<tr><td>${h(r.dishName)}</td><td>${h(r.ingredient)}</td><td>${h(n(r.amount))}</td><td>${h(r.unit)}</td></tr>`).join('')}</tbody></table></div>`:empty('所选食谱未包含当前日期或餐次，请重新选择，不用别的餐次代替。'))+
    `<div class="buttons"><button class="secondary" data-step="dispatch">核对预计配餐人数</button><button class="secondary" data-print>打印配方参考</button><button class="secondary" data-step="recipe">返回周历编辑</button></div>`+note('仅核对本食谱适用范围后才能换算备餐总量；第 2 站提供基于原规则的毛料换算预览。加工执行、留样和消毒记录需后续单独设计。','warning'));
}
function plansView(id){
  const plans=data.plans,c=plans.summary;
  panelBody(note(id==='dispatch'?'这是班级预计配餐参考，数据来自各班已保存计划；不是餐车定位、已装车或送达签收。':'点击班级逐人核对现有五餐记录。前六站完成与否，不会替老师自动确认实际就餐。')+
    (c?`<p class="muted">${h(c.scope_label)}</p><div class="metric-grid"><div class="metric"><span>所选餐次预计人数</span><b>${h(n(c.expected))}</b><small>${c.planned_groups} / ${c.visible_groups} 可见班已保存预计</small></div><div class="metric"><span>所选餐次实际人数</span><b>${h(n(c.actual))}</b><small>${c.confirmed_groups} / ${c.visible_groups} 可见班已确认实际</small></div></div>`:'')+
    `<div class="table-wrap"><table><thead><tr><th>班级</th><th>预计</th><th>已确认实际</th><th>登记状态</th><th></th></tr></thead><tbody>${plans.rows.map(r=>`<tr><td>${h(r.label)}</td><td>${h(n(r.expected))}</td><td>${h(n(r.actual))}</td><td>${status(r.status)}</td><td><button class="secondary" data-meal-group="${h(r.group)}">核对原记录</button></td></tr>`).join('')||'<tr><td colspan="5">暂无可见班级餐次记录</td></tr>'}</tbody></table></div>`+
    `<div class="buttons"><button class="secondary" data-print>打印${id==='dispatch'?'配餐参考':'确认记录'}清单</button><button class="secondary" data-step="${id==='dispatch'?'dining':'dispatch'}">${id==='dispatch'?'前往实际确认':'查看预计配餐'}</button></div>`+
    note(id==='dispatch'?'未保存预计的班级显示“待核对”，不是零份。当前没有特殊餐执行清单、配送批次或签收模块，不能把餐车模型当作凭证。':'修改已确认记录必须填写原因。未来只能保存预计，未发生的餐次不可提前确认实际。','warning'));
}
async function editMeals(group){
  if(!leaveDraft())return;active='dining';scene?.focus('dining');$('panel-title').textContent='实际用餐确认';$('panel-number').textContent=7;$('panel-subtitle').textContent='逐生核对五餐';$('step-position').textContent='7 / 8';$('previous-step').disabled=false;$('next-step').disabled=false;
  const ticket=++sequence,day=data.day;panelBody(empty('读取班级已保存计划与实际状态…'));
  try{const result=await api('get_meals',{student_group:group,day});if(!live(ticket))return;
    const rows=result.record.students.map(mealDraft),editable=!!data.capabilities.meals_write&&result.editable!==false,future=day>data.today;
    panelBody(note(`${group} · ${day} · 五餐整体核对。下方未确认值按预计安排预填为草稿，只有明确确认后才是实际记录。`)+
      `<div class="buttons"><label><input id="select-all" type="checkbox">全选</label><select id="bulk-meal">${MEALS.map(([k,l])=>`<option value="${k}" ${k===data.meal?'selected':''}>${l}</option>`).join('')}</select><select id="bulk-state"><option>就餐</option><option>不就餐</option><option>不供餐</option></select><button class="secondary" id="bulk-apply" ${editable?'':'disabled'}>应用到选中学生</button></div>`+
      `<div class="table-wrap"><table><thead><tr><th>选</th><th>学生</th>${MEALS.map(([,l])=>`<th>${l}</th>`).join('')}</tr></thead><tbody>${rows.map((r,i)=>`<tr><td><input type="checkbox" class="meal-select" data-i="${i}"></td><td>${h(r.student_name)}</td>${MEALS.map(([m,l])=>`<td><select class="meal-value" data-i="${i}" data-meal="${m}" aria-label="${h(r.student_name+l)}" ${editable?'':'disabled'}>${['就餐','不就餐','不供餐'].map(v=>`<option ${r[m]===v?'selected':''}>${v}</option>`).join('')}</select></td>`).join('')}</tr>`).join('')}</tbody><tfoot><tr><td colspan="2">草稿就餐人数</td>${MEALS.map(([m])=>`<td id="total-${m}"></td>`).join('')}</tr></tfoot></table></div>`+
      `<label class="field"><span>修改原因（修改已确认记录时必填）</span><textarea id="meal-reason" rows="2" maxlength="1000" ${editable?'':'disabled'}></textarea></label>`+
      `<div class="form-actions"><span class="muted">${future?'未来日期只能保存预计安排。':''}保留原完整名单、版本冲突和锁定校验；不修改学生考勤。</span><button class="secondary" id="meal-plan" ${editable&&rows.length&&result.record.status!=='已确认'?'':'disabled'}>保存预计安排</button><button class="primary" id="meal-confirm" ${editable&&rows.length&&!future?'':'disabled'}>确认五餐实际情况</button></div>`);
    const totals=()=>{const c=draftTotals(rows);MEALS.forEach(([m])=>$('total-'+m).textContent=c[m]);};totals();
    panel.querySelectorAll('.meal-value').forEach(el=>el.onchange=()=>{rows[+el.dataset.i][el.dataset.meal]=el.value;dirty=true;totals();});
    $('meal-reason').oninput=()=>dirty=true;$('select-all').onchange=()=>panel.querySelectorAll('.meal-select').forEach(el=>el.checked=$('select-all').checked);
    $('bulk-apply').onclick=()=>{const selected=[...panel.querySelectorAll('.meal-select:checked')];if(!selected.length)return notify('请先选择学生。');const m=$('bulk-meal').value,v=$('bulk-state').value;selected.forEach(el=>{rows[+el.dataset.i][m]=v;panel.querySelector(`.meal-value[data-i="${el.dataset.i}"][data-meal="${m}"]`).value=v;});dirty=true;totals();};
    const commit=async confirm=>{const reason=$('meal-reason').value.trim();if(result.record.status==='已确认'&&!reason)return notify('请填写修改已确认记录的原因。',true);if(confirm&&!window.confirm('确认五个餐次均已逐人核实？尚未发生的餐次不能提前确认。'))return;const r=await save('save_meals',{student_group:group,day,students:rows,revision:result.revision,confirm:confirm?1:0,change_reason:reason});if(r){await load();if(live(ticket))plansView('dining');}};
    $('meal-plan').onclick=()=>commit(false);$('meal-confirm').onclick=()=>commit(true);
  }catch(error){if(live(ticket))panelBody(note(failure(error),'error'));}
}
async function traceView(ticket){
  let trace=null;if(selectedRecipe&&data.capabilities.recipe)trace=await api('recipe_trace',{recipe:selectedRecipe});if(!live(ticket))return;
  panelBody(note('本期追溯范围是食谱及其关联采购需求等业务单据。没有伪造产地、检验、批次、冷链或食品安全合格率。')+
    `<div class="buttons">${data.capabilities.recipe?button('营养分析与导出','nutrition'):''}${data.capabilities.order?button('采购订单报表','orders'):''}${data.capabilities.stock?button('库存余额报表','stock'):''}</div>`+
    (trace?`<h3 class="section-title">所选食谱关联</h3>${note(trace.note)}${trace.impact?note(trace.impact.message):note('当前无采购需求读取权限。')}<div class="buttons">${trace.impact?.requests.map(r=>button(r.name+' · '+(r.docstatus===0?'草稿':'已提交'),'request',r.name)).join('')||'<span class="muted">暂无可见关联采购需求</span>'}</div>`:`<div class="buttons"><button class="secondary" data-step="recipe">先选择食谱，查看关联原单</button></div>`)+
    `<h3 class="section-title">尚未接入，不显示“正常”</h3>${data.unconnected.map(s=>`<div class="help-card"><h3>${h(s)}</h3><p>无权威数据来源，场景仅示意；需另行明确业务模型、授权、记录与验收。</p></div>`).join('')}`);
}
async function save(method,args){
  if(writing)return null;writing=true;const controls=[...panel.querySelectorAll('button,input,select,textarea')].map(el=>[el,el.disabled]);controls.forEach(([el])=>el.disabled=true);
  try{const result=await api(method,args,true);dirty=false;notify(method==='create_demand'?'采购需求草稿已保存':method==='create_recipe_draft'?'食谱草稿已保存':method==='save_recipe_edit'?(result.mode==='copy'?'修订草稿已创建，原食谱未改变':'食谱草稿修改已保存'):'班级餐次记录已保存');return result;}
  catch(error){notify(failure(error),true);return null;}
  finally{writing=false;controls.forEach(([el,disabled])=>{if(el.isConnected)el.disabled=disabled;});}
}
function openNative(key,name=''){
  const route=professionalRoute(key,name);if(!route)return notify('不支持的专业入口。',true);if(!leaveDraft())return;
  ++sequence;embedded=true;panel.classList.add('expanded','embedded-open');
  panelBody(note('正在同一工作台内打开原 Frappe 专业模块，沿用其登录、权限、校验和提交规则。离开前请保存其中的修改。')+
    `<div class="buttons"><a class="secondary" href="${h(route)}" target="_blank" rel="noopener">在新页打开原模块 ↗</a><button class="secondary" id="native-back">返回本站业务</button></div><iframe class="professional" title="原 Frappe 专业业务模块" src="${h(route)}" referrerpolicy="same-origin"></iframe>`);
  $('native-back').onclick=()=>openStep(active);
}
document.addEventListener('click',async event=>{
  const weekCell=event.target.closest('[data-workbench-date][data-workbench-meal]');if(weekCell){
    const day=weekCell.dataset.workbenchDate,meal=weekCell.dataset.workbenchMeal;
    if(draftState?.kind==='draft'){
      captureDraftEditor();draftState.day=day;draftState.slot=SLOTS[meal];mobileWeekDay=day;renderDraftEditor();return;
    }
    if(day===data?.day&&meal===data?.meal)openStep('recipe');else contextChange(null,day,meal);
    revealPanel();
    return;
  }
  const startDraft=event.target.closest('[data-start-draft]');if(startDraft){if(await openStep('recipe')){beginRecipeDraft();revealPanel();}return;}
  const step=event.target.closest('[data-step]');if(step){$('search-results').hidden=true;openStep(step.dataset.step);revealPanel();return;}
  const native=event.target.closest('[data-native]');if(native){openNative(native.dataset.native,native.dataset.doc||'');return;}
  const draftCell=event.target.closest('[data-draft-day][data-draft-slot]');if(draftCell&&draftState?.kind==='draft'){captureDraftEditor();const top=$('panel-body').scrollTop,left=$('panel-body').querySelector('.recipe-week-scroll')?.scrollLeft||0;draftState.day=draftCell.dataset.draftDay;draftState.slot=draftCell.dataset.draftSlot;renderDraftEditor();$('panel-body').scrollTop=top;$('panel-body').querySelector('.recipe-week-scroll').scrollLeft=left;return;}
  const draftRemove=event.target.closest('[data-draft-remove]');if(draftRemove&&draftState?.kind==='draft'){captureDraftEditor();const portion=draftPortion(draftState.day,draftState.slot,true);portion.dishIngredientRows.splice(Number(draftRemove.dataset.draftRemove),1);dirty=true;const top=$('panel-body').scrollTop;renderDraftEditor();$('panel-body').scrollTop=top;return;}
  const calendarCell=event.target.closest('[data-calendar-day][data-calendar-slot]');if(calendarCell&&recipeCalendarState){recipeCalendarState.day=calendarCell.dataset.calendarDay;recipeCalendarState.slot=calendarCell.dataset.calendarSlot;renderRecipePreview();return;}
  const recipe=event.target.closest('[data-recipe]');if(recipe){selectedRecipe=recipe.dataset.recipe;const ticket=++sequence;recipeView(ticket,selectedRecipe).catch(error=>live(ticket)&&panelBody(note(failure(error),'error')));return;}
  const group=event.target.closest('[data-meal-group]');if(group){editMeals(group.dataset.mealGroup);return;}
  const sub=event.target.closest('[data-sub]');if(sub){if(sub.dataset.sub==='nutrition')nutritionView();else if(sub.dataset.sub==='recipe-library'){selectedRecipe=null;recipeCalendarState=null;weekPayload=null;renderWeekOverview();const ticket=++sequence;recipesView(ticket,0,true).catch(e=>live(ticket)&&panelBody(note(failure(e),'error')));}else if(sub.dataset.sub==='recipe-back'){const ticket=++sequence;recipeView(ticket,selectedRecipe).catch(e=>live(ticket)&&panelBody(note(failure(e),'error')));}else if(sub.dataset.sub==='recipe-new')beginRecipeDraft();else if(sub.dataset.sub==='recipe-import')beginRecipeImport();else if(sub.dataset.sub==='recipe-edit')beginRecipeEdit();else if(sub.dataset.sub==='draft-cancel')openStep('recipe');return;}
  const view=event.target.closest('[data-view]');if(view){scene?.setView(view.dataset.view);document.querySelectorAll('[data-view]').forEach(el=>{const on=el===view;el.classList.toggle('active',on);el.setAttribute('aria-pressed',String(on));});}
  if(event.target.closest('[data-print]'))window.print();
});
document.addEventListener('input',event=>{if(event.target.closest('#recipe-draft-editor'))dirty=true;});
$('close-panel').onclick=closePanel;panel.addEventListener('cancel',e=>{e.preventDefault();closePanel();});
$('expand-panel').onclick=()=>panel.classList.toggle('expanded');
$('previous-step').onclick=()=>{const step=stepFor(active);if(step.number>1)openStep(STEPS[step.number-2].id);};
$('next-step').onclick=()=>{const step=stepFor(active);if(step.number<8)openStep(STEPS[step.number].id);};
function contextChange(el,requestedDay=$('day').value,requestedMeal=$('meal').value){
  if(!leaveDraft()){if(data){$('day').value=data.day;$('meal').value=data.meal;}return;}
  if(panel.open)closePanel();
  $('day').value=requestedDay;$('meal').value=requestedMeal;
  const covers=weekPayload?.payload?.days.some(row=>row.date===requestedDay);
  if(!covers){selectedRecipe=null;recipeCalendarState=null;weekPayload=null;}
  else if(recipeCalendarState){recipeCalendarState.day=requestedDay;recipeCalendarState.slot=SLOTS[requestedMeal];}
  load();
}
$('day').onchange=()=>{if($('day').value)contextChange($('day'));};$('meal').onchange=()=>contextChange($('meal'));
$('refresh').onclick=()=>{if(!leaveDraft())return;if(panel.open)closePanel();load();};
$('week-mobile-day').onchange=()=>{mobileWeekDay=$('week-mobile-day').value;renderWeekOverview();};
$('scene-preview').addEventListener('toggle',()=>{if($('scene-preview').open)ensureScene();});
$('week-new').onclick=async()=>{if(await openStep('recipe'))beginRecipeDraft();};
$('week-import').onclick=async()=>{if(await openStep('recipe'))beginRecipeImport();};
$('week-other-recipes').onclick=async()=>{if(await openStep('recipe'))document.querySelector('[data-sub="recipe-library"]')?.click();};
$('labels-toggle').onclick=()=>{const hidden=document.body.classList.toggle('tags-off');$('labels-toggle').setAttribute('aria-pressed',String(!hidden));};
$('fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch(_){notify('浏览器未允许全屏，所有业务仍可使用。');}};
$('search').oninput=()=>{const q=$('search').value.trim();$('search-results').hidden=!q;$('search-results').innerHTML=STEPS.filter(s=>(s.title+s.subtitle).includes(q)).map(s=>`<button data-step="${s.id}">${h(s.title)}</button>`).join('')||'<p class="muted">没有匹配的业务</p>';};
document.addEventListener('keydown',e=>{const editing=/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)||e.target.isContentEditable;if(e.key==='Escape'){if(!$('search-results').hidden){$('search-results').hidden=true;return;}if(panel.open){e.preventDefault();closePanel();}}if(e.key==='/'&&!editing){e.preventDefault();$('more-work').open=true;$('search').focus();}if(!editing&&!e.ctrlKey&&!e.altKey&&!e.metaKey&&/^[1-8]$/.test(e.key))openStep(STEPS[Number(e.key)-1].id);});
window.addEventListener('beforeunload',e=>{if(dirty||writing||embedded){e.preventDefault();e.returnValue='';}});
const timer=setInterval(()=>load(true),60000);document.addEventListener('visibilitychange',()=>{if(!document.hidden)load(true);});
window.addEventListener('pagehide',()=>{clearInterval(timer);scene?.dispose();});window.addEventListener('pageshow',e=>{if(e.persisted)location.reload();});
const params=new URLSearchParams(location.search);if(/^\d{4}-\d{2}-\d{2}$/.test(params.get('day')||''))$('day').value=params.get('day');if(MEALS.some(([m])=>m===params.get('meal')))$('meal').value=params.get('meal');
load();
