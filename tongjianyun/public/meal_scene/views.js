// Registered components only. Model messages, HTML and executable code are never rendered here.
const $=id=>document.getElementById(id);
const validViews=new Set(['students','class_students','meal_counts','recipe_week','recipe_nutrition',
  'business_catalog','business_list','business_record','stock','ingredient_nutrition','classroom_day','weekly_orders',
  'project_catalog','frappe_catalog','frappe_doctype','frappe_document','frappe_report','frappe_page','frappe_workspace']);
let request,current=null,ticket=0;
const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=String(text??'—');if(cls)el.className=cls;return el;};
function notice(text,error=false){$('view-status').textContent=text;$('view-status').hidden=!text;$('view-status').classList.toggle('error',error);}
export function currentViewContext(){return current||{view:'recipe_week',day:$('day').value,meal:$('meal').value};}
export function initializeViews(options){
  request=options.request;
  // Each page load starts on the weekly recipe, independently of chat history.
  showCalendar();
  $('view-back').addEventListener('click',()=>showCalendar());
  $('refresh').addEventListener('click',()=>{if(current&&current.view!=='recipe_week')showBusinessView(current);});
  for(const id of ['day','meal'])$(id).addEventListener('change',()=>{
    if(current?.view==='meal_counts')showBusinessView({...current,day:$('day').value,meal:$('meal').value});
    if(current?.view==='recipe_nutrition'){
      if(id==='day'){const {recipe,...choice}=current;showBusinessView({...choice,day:$('day').value,meal:$('meal').value});}
      else current={...current,meal:$('meal').value}; // A whole-week analysis is not a single meal.
    }
    if(current&&['business_catalog','business_list','classroom_day','weekly_orders'].includes(current.view)){
      if(id==='day')showBusinessView({...current,day:$('day').value,offset:current.view!=='business_catalog'?0:undefined});
      else current={...current,meal:$('meal').value};
    }
    if(current?.view==='ingredient_nutrition'&&id==='day'){
      const {recipe,...choice}=current;showBusinessView({...choice,day:$('day').value,offset:0});
    }
  });
}
function calendarContext(choice){
  if(!choice?.day||!choice?.meal)return;
  const changed=$('day').value!==choice.day||$('meal').value!==choice.meal;
  $('day').value=choice.day;$('meal').value=choice.meal;
  if(changed)$('refresh').click();
}
function showCalendar(choice){
  ++ticket;current=null;notice('');$('business-view').hidden=true;$('recipe-workspace').hidden=false;
  $('business-canvas').setAttribute('aria-label','本周膳食总览');
  calendarContext(choice);
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
function renderFrappeFrame(block){
  // Routes come from permission-checked site metadata, never model supplied URLs.
  if(typeof block.route!=='string'||!block.route.startsWith('/desk/')||/[\\?#\r\n]/.test(block.route)||block.route.includes('//')||block.route.includes('..'))throw Error('原生业务地址无效。');
  const section=node('section',undefined,'view-native');
  const link=node('a','在独立页面打开 ↗','view-action');link.href=block.route;link.target='_blank';link.rel='noopener noreferrer';
  const frame=node('iframe');frame.src=block.route;frame.title=block.title||'Frappe 业务';frame.referrerPolicy='same-origin';
  section.append(link,frame);return section;
}
const renderers={stats:renderStats,table:renderTable,bars:renderBars,notice:renderNotice,frappe_frame:renderFrappeFrame};
export function buildComponents(data){
  if(data?.version!==1||!validViews.has(data.selection?.view)||!Array.isArray(data.components)||data.components.length>12)throw Error('展示结果格式不受支持，已保留当前页面。');
  const content=document.createDocumentFragment();
  for(const block of data.components){if(!Object.hasOwn(renderers,block.type))throw Error('此结果需要更新页面组件，已保留当前内容。');content.append(renderers[block.type](block));}
  return content;
}
export async function showBusinessView(choice){
  if(!choice||!validViews.has(choice.view)||!request)return;
  const turn=++ticket;notice('正在读取业务数据…');
  try{
    const result=await request('/api/method/tongjianyun.meal_views.get_view?'+new URLSearchParams({selection_json:JSON.stringify(choice)}));
    if(turn!==ticket)return;
    if(result.version!==1||!validViews.has(result.selection?.view))throw Error('展示结果格式无效。');
    if(result.selection.view==='recipe_week'){showCalendar(result.selection);return;}
    const fragment=buildComponents(result);
    $('view-title').textContent=result.title;$('view-subtitle').textContent=result.subtitle;
    $('view-content').replaceChildren(fragment);$('view-actions').replaceChildren(...(result.actions||[]).map(actionButton));
    $('view-source').textContent=`来源：${result.source} · 更新于 ${result.generated_at}`;
    current=result.selection;
    $('recipe-workspace').hidden=true;$('business-view').hidden=false;$('business-canvas').setAttribute('aria-label',result.title);
    notice('');if(['meal_counts','business_list','business_catalog','ingredient_nutrition','classroom_day','weekly_orders'].includes(current.view))calendarContext(current);
  }catch(error){if(turn===ticket)notice(error.message||'数据读取失败，已保留上一次结果。',true);}
}
