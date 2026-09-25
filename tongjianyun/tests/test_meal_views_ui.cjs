const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
class Element{
  constructor(){this.children=[];this.textContent='';this.style={};this.attrs={};this.listeners={};this.classList={toggle(){}};this.hidden=false;this.value='';}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,v){this.listeners[k]=v;}
  click(){}
}
function setup(){
  const nodes=new Map(),storage=new Map();
  const events=new Map();
  const document={getElementById(id){assert(!['day','meal','refresh'].includes(id),'removed header control requested: '+id);if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},createElement:tag=>Object.assign(new Element(),{tag}),createDocumentFragment:()=>new Element(),addEventListener:(type,handler)=>events.set(type,handler),dispatchEvent:event=>events.get(event.type)?.(event)};
  const context=vm.createContext({document,URLSearchParams,CustomEvent:class{constructor(type,options={}){this.type=type;this.detail=options.detail;}},sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../public/meal_scene/state.js'),'utf8').replace(/export /g,''),context);
  const source=fs.readFileSync(path.join(__dirname,'../public/meal_scene/views.js'),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/export /g,'');
  vm.runInContext(source,context);
  return {nodes,context,storage,run:code=>vm.runInContext(code,context)};
}
const data={version:1,selection:{view:'students'},title:'在园学生',subtitle:'scope',source:'Student',generated_at:'now',components:[{type:'stats',items:[{label:'人数',value:12,unit:'人'}]}]};
test('view uses text nodes instead of executing model or record HTML',()=>{
  const {run,context}=setup();context.data={...data,components:[{type:'notice',text:'<img src=x onerror=alert(1)>'}]};
  const result=run('buildComponents(data)');assert.equal(result.children[0].textContent,'<img src=x onerror=alert(1)>');assert.equal(result.children[0].children.length,0);
});
test('unregistered components fail before replacing current page',()=>{
  const {run,context}=setup();context.data={...data,components:[{type:'html',html:'<script>'}]};
  assert.throws(()=>run('buildComponents(data)'),/组件/);
});
test('slow old response cannot overwrite the newest view',async()=>{
  const {run,context,nodes}=setup();let resolveOld;context.fetcher=()=>new Promise(resolve=>resolveOld=resolve);context.newData=data;
  run("initializeViews({request:fetcher,user:'user'});");
  const old=run("showBusinessView({view:'meal_counts'})");
  run('request=async()=>newData');await run("showBusinessView({view:'students'})");
  resolveOld({...data,title:'old result',selection:{view:'meal_counts'}});await old;
  assert.equal(nodes.get('view-title').textContent,'在园学生');
});
test('failed query leaves successful data visible and does not set zero',async()=>{
  const {run,context,nodes}=setup();context.newData=data;
  run("initializeViews({request:async()=>newData,user:'user'});");await run("showBusinessView({view:'students'})");
  run("request=async()=>{throw Error('没有权限')}");await run("showBusinessView({view:'class_students',group:'secret'})");
  assert.equal(nodes.get('view-title').textContent,'在园学生');assert.equal(nodes.get('view-status').textContent,'没有权限');
});
test('returning to calendar beats pending requests',async()=>{
  const {run,context,nodes}=setup();let resolve;context.fetcher=()=>new Promise(r=>resolve=r);
  run("initializeViews({request:fetcher,user:'user'})");const pending=run("showBusinessView({view:'students'})");run('showCalendar()');resolve(data);await pending;
  assert.equal(nodes.get('recipe-workspace').hidden,false);assert.equal(nodes.get('business-view').hidden,true);
});
test('page initialization defaults to weekly recipe despite legacy saved view and preserves date and meal',()=>{
  const {run,context,nodes,storage}=setup();let requests=0;context.fetcher=()=>{requests++;};
  storage.set('meal-business-view:user',JSON.stringify({view:'students'}));
  run("setMealContext({day:'2026-09-24',meal:'lunch'});initializeViews({request:fetcher,user:'user'})");
  assert.equal(requests,0);assert.equal(nodes.get('recipe-workspace').hidden,false);assert.equal(nodes.get('business-view').hidden,true);
  assert.equal(nodes.get('business-canvas').attrs['aria-label'],'本周膳食总览');
  assert.deepEqual(JSON.parse(run('JSON.stringify(currentViewContext())')),{view:'recipe_week',day:'2026-09-24',meal:'lunch'});
});
test('data refresh keeps an explicitly selected business view',async()=>{
  const {run,context,nodes}=setup();let requests=0;context.fetcher=async()=>{requests++;return data;};
  run('initializeViews({request:fetcher})');await run("showBusinessView({view:'students'})");
  run('refreshMealData()');await Promise.resolve();
  assert.equal(requests,2);assert.equal(nodes.get('recipe-workspace').hidden,true);assert.equal(nodes.get('business-view').hidden,false);
});
test('nutrition tables support folded details and safe evaluation labels',()=>{
  const {run,context}=setup();context.data={version:1,selection:{view:'recipe_nutrition'},components:[{type:'table',title:'食材明细',collapsed:true,columns:['食材','评价'],rows:[{cells:['<script>','偏高'],evaluation:'偏高'}]}]};
  const block=run('buildComponents(data)').children[0];
  assert.equal(block.tag,'details');assert.equal(block.children[0].tag,'summary');
  const row=block.children[1].children[0].children[1].children[0];
  assert.equal(row.children[0].textContent,'<script>');assert.equal(row.children[1].className,'view-evaluation warn');
});
test('assistant can select another week without header date controls',async()=>{
  const {run,context,nodes}=setup();context.requests=[];
  context.fetcher=async url=>{const choice=JSON.parse(new URL(url,'http://local').searchParams.get('selection_json'));context.requests.push(choice);return {...data,selection:choice};};
  run('initializeViews({request:fetcher})');await run("showBusinessView({view:'recipe_nutrition',recipe:'R1',day:'2026-09-24',meal:'lunch',garden_ratio:80})");
  await run("showBusinessView({view:'recipe_nutrition',day:'2026-10-01',meal:'lunch',garden_ratio:80})");
  assert.equal(context.requests[1].day,'2026-10-01');assert.equal(context.requests[1].recipe,undefined);
  assert.equal(context.requests.length,2);assert.equal(run('currentViewContext().garden_ratio'),80);
});
test('registered business views render data and safe clickable details',async()=>{
  const {run,context,nodes}=setup();context.requests=[];
  context.fetcher=async url=>{const choice=JSON.parse(new URL(url,'http://local').searchParams.get('selection_json'));context.requests.push(choice);return {...data,selection:choice,title:'采购订单'};};
  run('initializeViews({request:fetcher})');
  await run("showBusinessView({view:'business_list',entity:'purchase_orders',day:'2026-09-24',meal:'lunch',period:'week',offset:30})");
  assert.equal(nodes.get('view-title').textContent,'采购订单');
  await run("showBusinessView({view:'business_list',entity:'purchase_orders',day:'2026-10-01',period:'week',offset:0})");
  assert.equal(context.requests[1].offset,0);assert.equal(context.requests[1].day,'2026-10-01');
  context.data={version:1,selection:{view:'business_list'},components:[{type:'table',title:'采购',columns:['单据'],rows:[{cells:['<script>'],action:{label:'打开',selection:{view:'business_record',entity:'purchase_orders',record:'PO1'}}}]}]};
  const section=run('buildComponents(data)').children[0];
  const button=section.children[1].children[0].children[1].children[0].children[0].children[0];
  assert.equal(button.tag,'button');assert.equal(button.textContent,'<script>');
  button.listeners.click();await Promise.resolve();
  assert.equal(context.requests[2].view,'business_record');assert.equal(context.requests[2].record,'PO1');
});
test('calendar result updates shared conversation context without a refresh button',()=>{
  const {run,context}=setup();context.refreshes=0;
  run("document.addEventListener('meal-scene:refresh',()=>refreshes++);showCalendar({day:'2026-10-01',meal:'dinner'})");
  assert.equal(run('refreshes'),1);
  assert.deepEqual(JSON.parse(run('JSON.stringify(currentViewContext())')),{view:'recipe_week',day:'2026-10-01',meal:'dinner'});
  run("calendarContext({day:'2026-10-01',meal:'dinner'})");assert.equal(run('refreshes'),1);
});
test('catalog, stock, classroom and ingredient views accept registered safe components',()=>{
  const {run,context}=setup();
  for(const view of ['business_catalog','business_record','stock','classroom_day','weekly_orders','ingredient_nutrition']){
    context.data={version:1,selection:{view},components:[{type:'notice',text:'无记录不是零'}]};
    assert.equal(run('buildComponents(data)').children.length,1);
  }
});
test('native Frappe frame accepts only internal Desk routes and uses text labels',()=>{
  const {run,context}=setup();
  context.data={version:1,selection:{view:'frappe_doctype'},components:[{type:'frappe_frame',route:'/desk/sales-invoice',title:'<script>'}]};
  const block=run('buildComponents(data)').children[0];
  assert.equal(block.children[1].tag,'iframe');assert.equal(block.children[1].src,'/desk/sales-invoice');
  assert.equal(block.children[1].title,'<script>');assert.equal(block.children[0].rel,'noopener noreferrer');
  for(const route of ['https://evil.test','//evil.test','javascript:alert(1)','/desk/../api','/desk/x?code=1','/desk/\\evil']){
    context.data.components[0].route=route;assert.throws(()=>run('buildComponents(data)'),/地址无效/);
  }
});
