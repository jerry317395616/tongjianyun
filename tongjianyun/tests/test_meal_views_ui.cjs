const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
class Element{
  constructor(){this.children=[];this.textContent='';this.style={};this.attrs={};this.listeners={};this.classList={toggle(){}};this.hidden=false;this.value='';}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(k,v){this.attrs[k]=v;}
  addEventListener(k,v){this.listeners[k]=v;}
  removeEventListener(k){delete this.listeners[k];}
  click(){return this.listeners.click?.();}
}
function setup(){
  const nodes=new Map(),storage=new Map();
  const events=new Map(),windowEvents=new Map(),emitted=[];
  const document={getElementById(id){assert(!['day','meal','refresh'].includes(id),'removed header control requested: '+id);if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},createElement:tag=>Object.assign(new Element(),{tag}),createDocumentFragment:()=>new Element(),addEventListener:(type,handler)=>events.set(type,handler),dispatchEvent:event=>{emitted.push(event);return events.get(event.type)?.(event);}};
  const context=vm.createContext({document,URL,URLSearchParams,location:{origin:'https://test.local'},window:{confirm:()=>true,addEventListener:(type,handler)=>windowEvents.set(type,handler)},CustomEvent:class{constructor(type,options={}){this.type=type;this.detail=options.detail;}},sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../public/meal_scene/state.js'),'utf8').replace(/export /g,''),context);
  const source=fs.readFileSync(path.join(__dirname,'../public/meal_scene/views.js'),'utf8').replace(/^import .*;\r?\n/gm,'').replace(/export /g,'');
  vm.runInContext(source,context);
  return {nodes,context,storage,emitted,windowEvents,run:code=>vm.runInContext(code,context)};
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

const nativeData={...data,selection:{view:'frappe_doctype',doctype:'Sales Invoice',day:'2026-09-24',meal:'lunch'},components:[{type:'frappe_frame',route:'/desk/sales-invoice',title:'销售发票'}]};
async function nativeSetup(){
  const fixture=setup();fixture.context.nativeData=nativeData;fixture.context.requestCount=0;
  fixture.run('initializeViews({request:async()=>{requestCount++;return nativeData;}})');
  await fixture.run('showBusinessView(nativeData.selection)');
  return fixture;
}
const blueprint={type:'business_blueprint',proposal_id:'BP-1',revision:'a'.repeat(64),title:'新业务',description:'预览',fields:[{fieldname:'subject',label:'标题<script>',fieldtype:'Data',reqd:1},{fieldname:'status',label:'状态',fieldtype:'Select',reqd:0,options:'待处理\n已完成'}],state:'proposed',warnings:['尚未建立业务数据表'],can_activate:true};

test('view promise reports actual rendering and failures without replacing old content',async()=>{
  const {run,context,nodes,emitted}=setup();context.data=data;
  run('initializeViews({request:async()=>data})');assert.equal((await run('showBusinessView({view:"students"})')).status,'rendered');
  const original=nodes.get('view-content').children;
  run('request=async()=>{throw Error("无权限")};');
  assert.equal((await run('showBusinessView({view:"class_students",group:"secret"})')).status,'failed');
  assert.equal(nodes.get('view-content').children,original);assert.equal(emitted.at(-1).detail.message,'无权限');
  assert.equal((await run('showBusinessView({view:"not_registered"})')).status,'failed');
});

test('superseded views report superseded and task refresh cannot steal a pending selection',async()=>{
  const {run,context,nodes}=setup();context.data=data;let resolve;
  context.fetcher=()=>new Promise(r=>resolve=r);run('initializeViews({request:fetcher})');
  const pending=run('showBusinessView({view:"students"})');
  assert.equal((await run('showBusinessView({view:"recipe_week"},{origin:"refresh"})')).status,'blocked');
  resolve(data);assert.equal((await pending).status,'rendered');assert.equal(nodes.get('view-title').textContent,data.title);
  const old=run('showBusinessView({view:"students"})');run('showCalendar()');resolve(data);
  assert.equal((await old).status,'superseded');
});

test('terminal refresh preserves the exact native iframe without another request',async()=>{
  const {run}=await nativeSetup();const frame=run('nativeSession.frame');
  const result=await run('showBusinessView(current,{origin:"refresh"})');
  assert.equal(result.status,'rendered');assert.match(result.message,/未自动重载/);assert.equal(run('requestCount'),1);assert.equal(run('nativeSession.frame'),frame);
  run('refreshMealData()');assert.equal(run('nativeSession.frame'),frame);assert.equal(run('requestCount'),1);
});

test('unsaved native form blocks both assistant switches and return-to-calendar',async()=>{
  const {run,nodes}=await nativeSetup();run('nativeSession.frame.contentWindow={cur_frm:{is_dirty:()=>true}};window.confirm=()=>false;');
  const frame=run('nativeSession.frame');
  assert.equal((await run('showBusinessView({view:"students"},{origin:"assistant"})')).status,'blocked');
  assert.equal(run('showCalendar().status'),'blocked');assert.equal(run('nativeSession.frame'),frame);assert.equal(run('requestCount'),1);
  assert.equal(nodes.get('business-view').hidden,false);
});

test('confirmed native switch prompts once, and a failed target keeps the unsaved page',async()=>{
  const {run}=await nativeSetup();run('nativeSession.frame.contentWindow={cur_frm:{is_dirty:()=>true}};globalThis.prompts=0;window.confirm=()=>{prompts++;return true};request=async()=>{throw Error("目标不可用")};');
  const frame=run('nativeSession.frame');assert.equal((await run('showBusinessView({view:"students"})')).status,'failed');
  assert.equal(run('prompts'),1);assert.equal(run('nativeSession.frame'),frame);assert.equal(run('nativeDirty()'),true);
  run('request=async()=>nativeData');assert.equal((await run('showBusinessView({view:"frappe_doctype",doctype:"Sales Invoice"})')).status,'rendered');
  assert.equal(run('prompts'),2);
});

test('edits made while a different view is loading are protected before replacement',async()=>{
  const {run,context}=await nativeSetup();let resolve;context.fetcher=()=>new Promise(r=>resolve=r);context.data=data;run('request=fetcher;window.confirm=()=>false;');
  const frame=run('nativeSession.frame'),pending=run('showBusinessView({view:"students"})');
  run('nativeSession.dirty=true;nativeSession.revision++;');resolve(data);
  assert.equal((await pending).status,'blocked');assert.equal(run('nativeSession.frame'),frame);
});

test('native load status does not claim saved or completed business actions',async()=>{
  const {run}=await nativeSetup();const initial=run('nativeSession.status.textContent');assert.match(initial,/等待.*加载/);
  run('nativeSession.frame.contentWindow={location:{origin:"https://test.local",pathname:"/desk/sales-invoice"}}');
  run('nativeSession.frame.listeners.load()');assert.match(run('nativeSession.status.textContent'),/载入不代表保存、审批或查询已完成/);
  run('nativeSession.frame.listeners.error()');assert.match(run('nativeSession.status.textContent'),/加载失败/);
});

test('native route context follows only canonical allowed selection keys',async()=>{
  const {run}=await nativeSetup();
  run('nativeSession.frame.contentWindow={frappe:{get_route:()=>["Form","Sales Invoice","INV/0001"]},cur_frm:{doc:{__islocal:0}}};');
  assert.deepEqual(JSON.parse(run('JSON.stringify(currentViewContext())')),{view:'frappe_document',doctype:'Sales Invoice',document:'INV/0001',day:'2026-09-24',meal:'lunch'});
  run('nativeSession.frame.contentWindow.cur_frm.doc.__islocal=1');assert.equal(run('currentViewContext().view'),'frappe_new');assert.equal(run('currentViewContext().document'),undefined);
  run('nativeSession.frame.contentWindow.frappe.get_route=()=>["query-report","Stock Balance"];');assert.equal(run('currentViewContext().report'),'Stock Balance');assert.equal(run('currentViewContext().doctype'),undefined);
  run('nativeSession.frame.contentWindow.frappe.get_route=()=>["https://evil.test", "token"];');assert.equal(run('currentViewContext().view'),'frappe_report');
  assert.equal(run('currentViewContext().dirty'),undefined);assert.equal(run('currentViewContext().native_context'),undefined);
});

test('same-site Desk links stay in the frame and listeners are disposed on leaving',async()=>{
  const {run,context}=await nativeSetup();const doc=new Element();context.innerDoc=doc;
  run('nativeSession.frame.contentDocument=innerDoc;nativeSession.frame.contentWindow={location:{origin:"https://test.local",pathname:"/desk/sales-invoice"}};nativeSession.frame.src="https://test.local/desk/sales-invoice";nativeSession.frame.listeners.load();');
  const anchor={href:'https://test.local/desk/customer',target:'_blank'};
  doc.listeners.click({target:{closest:()=>anchor}});assert.equal(anchor.target,'_self');
  doc.listeners.input();assert.equal(run('nativeDirty()'),true);
  run('showCalendar()');assert.equal(Object.keys(doc.listeners).length,0);
});

test('parent unload warns for a dirty native form',async()=>{
  const {run,windowEvents}=await nativeSetup();run('nativeSession.dirty=true');let prevented=false;
  const event={preventDefault(){prevented=true;}};windowEvents.get('beforeunload')(event);
  assert.equal(prevented,true);assert.equal(event.returnValue,'');
});

test('blueprint is an escaped preview and activation is never automatic',()=>{
  const {run,context}=setup();context.block=blueprint;context.calls=[];run('request=(...args)=>calls.push(args)');
  const section=run('renderBlueprint(block)');assert.equal(context.calls.length,0);
  const table=section.children[2].children[1].children[0],rows=table.children[1].children;
  assert.equal(rows[0].children[0].textContent,'标题<script>');assert.equal(rows[1].children[3].textContent,'待处理\n已完成');
  for(const block of [{...blueprint,state:'conflict',can_activate:false},{...blueprint,can_activate:false},{...blueprint,state:'active',can_activate:false}]){
    context.block=block;assert(!run('renderBlueprint(block)').children.some(child=>child.tag==='button'));
  }
  context.block={...blueprint,revision:'bad'};assert.throws(()=>run('renderBlueprint(block)'),/版本无效/);
});

test('blueprint activation requires explicit second confirmation and binds the preview revision',async()=>{
  const {run,context}=setup();context.block=blueprint;context.calls=[];context.nativeData=nativeData;
  run('request=async(...args)=>{calls.push(args);return args[1]?.method==="POST"?{doctype:"Sales Invoice"}:nativeData};window.confirm=()=>false;');
  const section=run('renderBlueprint(block)'),button=section.children.at(-1);
  await button.click();assert.equal(context.calls.length,0);
  run('window.confirm=()=>true');await button.click();
  assert.equal(context.calls.length,2);assert.match(context.calls[0][0],/business_blueprints.activate$/);
  assert.equal(context.calls[0][1].method,'POST');assert.deepEqual(JSON.parse(context.calls[0][1].body),{proposal_id:'BP-1',revision:'a'.repeat(64)});
  assert.equal(run('current.view'),'frappe_doctype');await button.click();assert.equal(context.calls.length,2);
});

test('uncertain activation does not offer a blind duplicate submission',async()=>{
  const {run,context}=setup();context.block=blueprint;run('request=async()=>{throw Error("网络中断，结果需核对")};');
  const section=run('renderBlueprint(block)'),button=section.children.at(-1);await button.click();
  assert.equal(button.disabled,true);assert.match(section.children.at(-2).textContent,/结果需核对/);
});

test('activation completion does not steal a different business view',async()=>{
  const {run,context}=setup();let resolve;context.block=blueprint;context.fetcher=()=>new Promise(r=>resolve=r);run('request=fetcher');
  const button=run('renderBlueprint(block)').children.at(-1),pending=button.click();run('showCalendar()');resolve({doctype:'Sales Invoice'});await pending;
  assert.equal(run('current'),null);
});

test('new-document and blueprint views are registered and native size uses remaining space',()=>{
  const {run,context}=setup();context.data={...nativeData,selection:{view:'frappe_new'},components:[{type:'notice',text:'新建'}]};assert.equal(run('buildComponents(data)').children.length,1);
  context.data={...data,selection:{view:'business_blueprint'},components:[blueprint]};assert.equal(run('buildComponents(data)').children.length,1);
  const css=fs.readFileSync(path.join(__dirname,'../public/meal_scene/views.css'),'utf8');assert.doesNotMatch(css,/min-height:620px|100vh - 280px/);assert.match(css,/#business-view\.has-native/);
});

test('login, forbidden, blank and cross-origin frames do not claim a usable business page',async()=>{
  const {run,context}=await nativeSetup();
  for(const actual of [{origin:'https://test.local',pathname:'/login'},{origin:'https://other.test',pathname:'/desk/customer'},{origin:'null',pathname:'blank'},{origin:'https://test.local',pathname:'/desk/customer',title:'403 Forbidden'}]){
    context.actual=actual;run('nativeSession.frame.contentWindow={location:actual};nativeSession.frame.contentDocument={title:actual.title||""};nativeSession.frame.listeners.load();');
    assert.match(run('nativeSession.status.textContent'),/核对登录与权限/);assert.doesNotMatch(run('nativeSession.status.textContent'),/^页面已载入/);
  }
});

test('custom page edits use local dirty tracking rather than a stale saved cur_frm',async()=>{
  const {run}=await nativeSetup();run('nativeSession.dirty=true;nativeSession.frame.contentWindow={frappe:{pages:{"custom-page":{}},get_route:()=>["custom-page"]},cur_frm:{is_dirty:()=>false}};');
  assert.equal(run('nativeDirty()'),true);assert.equal(run('currentViewContext().view'),'frappe_page');assert.equal(run('currentViewContext().page'),'custom-page');assert.equal(run('currentViewContext().doctype'),undefined);
});

const attendanceBlock={type:'attendance_register',student_group:'CLASS-1',group_label:'测试班',day:'2026-09-25',revision:'attendance-rev',editable:true,offset:30,rows:[{student:'S1',student_name:'测试学生一',status:'Unknown',source:'尚无登记'},{student:'S2',student_name:'测试学生二',status:'Present',source:'考勤登记'}]};
const mealBlock={type:'meal_register',student_group:'CLASS-1',group_label:'测试班',day:'2026-09-25',meal:'lunch',meal_label:'午餐',revision:'',editable:true,confirmed:false,rows:[{student:'S1',student_name:'测试学生一',value:'未确认',expected:true},{student:'S2',student_name:'测试学生二',value:'未确认',expected:false}]};
async function registerSetup(block=attendanceBlock){
  const fixture=setup(),isMeal=block.type==='meal_register';fixture.context.responses={...data,selection:{view:isMeal?'meal_counts':'classroom_day',group:block.student_group,day:block.day,meal:'lunch',...(!isMeal?{offset:30}:{})},components:[block]};fixture.context.calls=[];
  fixture.run('initializeViews({request:async(url,options)=>{calls.push({url,options});return options?.method==="POST"?{saved:1}:responses;}})');
  await fixture.run('showBusinessView(responses.selection)');return fixture;
}
function setRegisterValue(fixture,index,value){const field=fixture.run('registerSession.fields')[index];field.select.value=value;field.select.listeners.change();return field;}

test('attendance keeps unknown explicit, uses accessible labels and never changes it automatically',async()=>{
  const fixture=await registerSetup(),session=fixture.run('registerSession');
  assert.equal(session.fields[0].select.value,'Unknown');assert.equal(session.fields[1].select.value,'Present');assert.equal(session.dirty,false);assert.equal(session.save.disabled,true);
  assert.match(session.fields[0].select.attrs['aria-label'],/测试学生一出勤状态/);assert.equal(session.fields[1].select.children.find(option=>option.value==='Unknown').disabled,true);
  assert.equal(fixture.context.calls.length,1);
});

test('attendance save sends only changed students with exact context/revision, no second confirmation, then reads back same page',async()=>{
  const fixture=await registerSetup();fixture.run('window.confirm=()=>{throw Error("normal save must not ask again")};');
  setRegisterValue(fixture,0,'Present');const session=fixture.run('registerSession');assert.equal(session.dirty,true);assert.equal(session.save.disabled,false);
  fixture.context.responses={...fixture.context.responses,components:[{...attendanceBlock,revision:'new-rev',rows:attendanceBlock.rows.map(row=>({...row,status:'Present'}))}]};
  await session.save.click();
  const call=fixture.context.calls[1];assert.match(call.url,/classroom.save_attendance$/);assert.equal(call.options.method,'POST');
  assert.deepEqual(JSON.parse(call.options.body),{student_group:'CLASS-1',day:'2026-09-25',revision:'attendance-rev',changes:[{student:'S1',status:'Present',leave_reason:''}]});
  const selected=JSON.parse(new URL(fixture.context.calls[2].url,'http://local').searchParams.get('selection_json'));assert.equal(selected.group,'CLASS-1');assert.equal(selected.day,'2026-09-25');assert.equal(selected.offset,30);
  assert.equal(fixture.run('registerSession.fields[0].select.value'),'Present');assert.equal(fixture.run('registerSession.dirty'),false);assert.equal(fixture.run('registerSession.state'),'ready');
});

test('new leave requires a reason before any request and cannot edit an existing leave reason',async()=>{
  const fixture=await registerSetup();const field=setRegisterValue(fixture,0,'Leave'),session=fixture.run('registerSession');
  await session.save.click();assert.equal(fixture.context.calls.length,1);assert.match(session.status.textContent,/请填写新请假/);
  field.reason.value='家长已说明';field.reason.listeners.input();await session.save.click();assert.equal(JSON.parse(fixture.context.calls[1].options.body).changes[0].leave_reason,'家长已说明');
  const second=await registerSetup({...attendanceBlock,rows:[{student:'S1',student_name:'测试',status:'Leave',leave_record:'LEAVE-1'}]});
  assert.equal(second.run('registerSession.fields[0].reason.disabled'),true);
});

test('readonly or locked attendance has no enabled save and displays the reason',async()=>{
  const fixture=await registerSetup({...attendanceBlock,editable:false,reason:'当日已锁定'}),session=fixture.run('registerSession');
  assert.equal(session.fields[0].select.disabled,true);assert.equal(session.save.disabled,true);await session.save.click();assert.equal(fixture.context.calls.length,1);
  assert(fixture.nodes.get('view-content').children[0].children[0].children.some(child=>child.textContent==='当日已锁定'));
});

test('dirty attendance survives background refresh and can cancel leaving the current business',async()=>{
  const fixture=await registerSetup();setRegisterValue(fixture,0,'Absent');const session=fixture.run('registerSession');fixture.run('window.confirm=()=>false');
  assert.equal((await fixture.run('showBusinessView(current,{origin:"refresh"})')).status,'blocked');
  assert.equal((await fixture.run('showBusinessView({view:"students"})')).status,'blocked');assert.equal(fixture.run('showCalendar().status'),'blocked');
  assert.equal(fixture.run('registerSession'),session);assert.equal(fixture.context.calls.length,1);
});

test('attendance in flight blocks switching and duplicate saves',async()=>{
  const fixture=await registerSetup();setRegisterValue(fixture,0,'Absent');let resolve;fixture.context.poster=()=>new Promise(r=>resolve=r);
  fixture.run('request=async(url,options)=>{calls.push({url,options});return options?.method==="POST"?poster():responses;};');
  const session=fixture.run('registerSession'),pending=session.save.click();assert.equal(session.state,'saving');await session.save.click();assert.equal(fixture.context.calls.length,2);
  assert.equal(fixture.run('showCalendar().status'),'blocked');resolve({saved:1});await pending;assert.equal(fixture.run('registerSession.state'),'ready');
});

test('lost attendance save response keeps draft and requires a read before any resubmission',async()=>{
  const fixture=await registerSetup();setRegisterValue(fixture,0,'Absent');fixture.run('request=async(url,options)=>{calls.push({url,options});if(options?.method==="POST")throw Error("网络中断");return responses;};');
  const session=fixture.run('registerSession');await session.save.click();assert.equal(session.state,'uncertain');assert.equal(session.fields[0].select.value,'Absent');assert.equal(session.save.disabled,true);assert.equal(session.verify.hidden,false);
  await session.save.click();assert.equal(fixture.context.calls.length,2);fixture.run('window.confirm=()=>{throw Error("explicit verification does not need another confirmation")};');await session.verify.click();
  assert.equal(fixture.context.calls.length,3);assert.equal(fixture.run('registerSession.state'),'ready');
});

test('successful save followed by failed readback cannot show old values as verified results',async()=>{
  const fixture=await registerSetup();setRegisterValue(fixture,0,'Absent');fixture.run('request=async(url,options)=>{calls.push({url,options});if(options?.method==="POST")return {saved:1};throw Error("回读失败")};');
  const session=fixture.run('registerSession');await session.save.click();assert.equal(session.state,'saved');assert.equal(session.dirty,false);assert.match(session.status.textContent,/保存已返回成功.*回读未完成/);assert.equal(session.verify.hidden,false);assert.equal(session.save.disabled,true);assert.equal(fixture.run('registerSession'),session);
});

test('attendance input validation rejects bad versions, duplicate ids and unsupported statuses',()=>{
  const {run,context}=setup();
  for(const block of [{...attendanceBlock,revision:''},{...attendanceBlock,student_group:''},{...attendanceBlock,rows:[attendanceBlock.rows[0],attendanceBlock.rows[0]]},{...attendanceBlock,rows:[{student:'S1',status:'bad'}]}]){
    context.block=block;assert.throws(()=>run('renderAttendance(block)'),/不完整|格式无效/);
  }
});

test('unconfirmed meals do not infer actual values from expected arrangements or unconfirmed stored values',async()=>{
  const fixture=await registerSetup({...mealBlock,rows:mealBlock.rows.map(row=>({...row,value:'就餐'}))}),session=fixture.run('registerSession');
  assert.equal(session.fields[0].select.value,'未确认');assert.equal(session.fields[1].select.value,'未确认');assert.equal(session.save.disabled,true);assert.match(session.status.textContent,/2 名学生未确认/);
  setRegisterValue(fixture,0,'就餐');assert.equal(session.save.disabled,true);setRegisterValue(fixture,1,'不供餐');assert.equal(session.save.disabled,false);
});

test('meal save submits the entire displayed roster for only the chosen meal and reads it back',async()=>{
  const fixture=await registerSetup(mealBlock);fixture.run('window.confirm=()=>{throw Error("normal meal save must not ask twice")};request=async(url,options)=>{calls.push({url,options});return options?.method==="POST"?{saved:true}:responses;};');
  setRegisterValue(fixture,0,'就餐');setRegisterValue(fixture,1,'不就餐');await fixture.run('registerSession.save').click();
  const call=fixture.context.calls[1];assert.match(call.url,/classroom.save_meal$/);
  assert.deepEqual(JSON.parse(call.options.body),{student_group:'CLASS-1',day:'2026-09-25',revision:'',meal:'lunch',students:[{student:'S1',value:'就餐'},{student:'S2',value:'不就餐'}],confirm:1,change_reason:''});
  const selected=JSON.parse(new URL(fixture.context.calls[2].url,'http://local').searchParams.get('selection_json'));assert.equal(selected.view,'meal_counts');assert.equal(selected.group,'CLASS-1');assert.equal(selected.meal,'lunch');
});

test('editing confirmed meal values requires a change reason and does not submit unchanged classmates as new attendance',async()=>{
  const fixture=await registerSetup({...mealBlock,confirmed:true,revision:'meal-rev',rows:mealBlock.rows.map(row=>({...row,value:'就餐'}))});fixture.run('request=async(url,options)=>{calls.push({url,options});return options?.method==="POST"?{saved:true}:responses;};');
  const session=fixture.run('registerSession');setRegisterValue(fixture,0,'不就餐');assert.equal(session.save.disabled,true);
  session.changeReason.value='老师重新核对';session.changeReason.listeners.input();assert.equal(session.save.disabled,false);await session.save.click();
  const body=JSON.parse(fixture.context.calls[1].options.body);assert.equal(body.change_reason,'老师重新核对');assert.equal(body.students.length,2);assert.equal(body.students[1].value,'就餐');assert.equal(body.revision,'meal-rev');assert.equal(body.changes,undefined);
});

test('meal errors retain draft, block resubmission and never claim confirmed',async()=>{
  const fixture=await registerSetup(mealBlock);fixture.run('request=async(url,options)=>{calls.push({url,options});throw Error("版本已过期")};');setRegisterValue(fixture,0,'就餐');setRegisterValue(fixture,1,'不就餐');const session=fixture.run('registerSession');await session.save.click();
  assert.equal(session.state,'uncertain');assert.equal(session.save.disabled,true);assert.match(session.status.textContent,/版本已过期.*不要直接重复提交/);assert.doesNotMatch(session.status.textContent,/确认成功/);
});

test('registers escape labels and allow neither an empty roster save nor competing edit components',async()=>{
  const fixture=await registerSetup({...attendanceBlock,group_label:'<script>',rows:[]});assert.equal(fixture.run('registerSession.save.disabled'),true);
  fixture.context.block={...attendanceBlock,group_label:'<script>'};const section=fixture.run('renderAttendance(block)');assert.match(section.children[1].textContent,/<script>/);assert.equal(section.children[1].children.length,0);
  fixture.context.malformed={...data,components:[attendanceBlock,mealBlock]};assert.throws(()=>fixture.run('buildComponents(malformed)'),/一个业务编辑器/);
});

test('a pending navigation cannot discard a register once saving has begun',async()=>{
  const fixture=await registerSetup();let resolveView,resolveSave;fixture.context.newView=data;
  fixture.context.readNext=()=>new Promise(resolve=>resolveView=resolve);fixture.context.postNext=()=>new Promise(resolve=>resolveSave=resolve);
  fixture.run('request=(url,options)=>options?.method==="POST"?postNext():readNext();');
  const switchView=fixture.run('showBusinessView({view:"students"})');setRegisterValue(fixture,0,'Absent');const session=fixture.run('registerSession'),saving=session.save.click();
  resolveView(data);assert.equal((await switchView).status,'blocked');assert.equal(fixture.run('registerSession'),session);
  fixture.run('request=async()=>responses');resolveSave({saved:1});await saving;assert.equal(fixture.run('registerSession.state'),'ready');
});

test('partial saved meals retain actual history but never promote expectations to actuals',async()=>{
  const fixture=await registerSetup({...mealBlock,has_plan:true,confirmed:false,revision:'partial-rev',requires_change_reason:true,rows:[{...mealBlock.rows[0],value:'就餐',expected:false},mealBlock.rows[1]]}),session=fixture.run('registerSession');
  assert.equal(session.fields[0].select.value,'就餐');assert.equal(session.fields[1].select.value,'未确认');assert.match(session.status.textContent,/1 名学生未确认/);
  setRegisterValue(fixture,0,'不就餐');setRegisterValue(fixture,1,'就餐');assert.equal(session.save.disabled,true);assert.equal(typeof session.changeReason.listeners.input,'function');
  session.changeReason.value='复核原实际记录';session.changeReason.listeners.input();assert.equal(session.save.disabled,false);
  fixture.run('request=async(url,options)=>{calls.push({url,options});return options?.method==="POST"?{saved:true}:responses;};');await session.save.click();
  const body=JSON.parse(fixture.context.calls[1].options.body);assert.equal(body.revision,'partial-rev');assert.equal(body.change_reason,'复核原实际记录');assert.deepEqual(body.students,[{student:'S1',value:'不就餐'},{student:'S2',value:'就餐'}]);
});

test('explicit missing meal plan overrides legacy-looking values and requires fresh choices',async()=>{
  const fixture=await registerSetup({...mealBlock,has_plan:false,confirmed:true,rows:mealBlock.rows.map(row=>({...row,value:'就餐'}))}),session=fixture.run('registerSession');
  assert.equal(session.fields[0].select.value,'未确认');assert.equal(session.fields[1].select.value,'未确认');assert.equal(session.save.disabled,true);
});

test('an effective leave locks attendance changes and points back to the original leave workflow',async()=>{
  const fixture=await registerSetup({...attendanceBlock,rows:[{student:'S1',student_name:'已有请假',status:'Leave',leave_record:'LEAVE-1'},attendanceBlock.rows[1]]}),session=fixture.run('registerSession'),field=session.fields[0];
  assert.equal(field.select.disabled,true);assert.equal(field.reason.disabled,true);
  for(const value of ['Present','Absent'])assert.equal(field.select.children.find(option=>option.value===value).disabled,true);
  const section=fixture.nodes.get('view-content').children[0].children[0],wrapper=section.children.find(child=>child.className==='view-table-wrap');
  assert.match(wrapper.children[0].children[1].children[0].children[2].children[1].textContent,/原请假流程撤销或标记返校/);
  // Even a stale event on a disabled row must not add it to the changed payload.
  field.select.value='Present';field.select.listeners.change();assert.equal(session.save.disabled,true);
  setRegisterValue(fixture,1,'Absent');await session.save.click();
  assert.deepEqual(JSON.parse(fixture.context.calls[1].options.body).changes,[{student:'S2',status:'Absent',leave_reason:''}]);
});

test('fill all meals is explicit local draft editing for the complete class, never an automatic request',async()=>{
  const rows=Array.from({length:108},(_,i)=>({student:'S'+i,student_name:'测试学生'+i,value:'未确认',expected:i%2===0}));
  const fixture=await registerSetup({...mealBlock,rows}),session=fixture.run('registerSession');
  assert.equal(session.fields.filter(field=>field.select.value==='未确认').length,108);assert.equal(session.fillAll.textContent,'本班本餐全部就餐');assert.equal(fixture.context.calls.length,1);
  await session.fillAll.click();assert.equal(session.fields.filter(field=>field.select.value==='就餐').length,108);assert.equal(session.dirty,true);assert.equal(session.save.disabled,false);assert.equal(fixture.context.calls.length,1);assert.match(session.status.textContent,/草稿.*才会保存/);
  setRegisterValue(fixture,0,'不就餐');setRegisterValue(fixture,107,'不供餐');assert.equal(fixture.context.calls.length,1);
  fixture.run('request=async(url,options)=>{calls.push({url,options});return options?.method==="POST"?{saved:true}:responses;};');await session.save.click();
  const body=JSON.parse(fixture.context.calls[1].options.body);assert.equal(body.students.length,108);assert.equal(body.meal,'lunch');assert.equal(body.students[0].value,'不就餐');assert.equal(body.students[107].value,'不供餐');assert.equal(body.students[1].value,'就餐');
});

test('fill all retains reason requirements for existing actual meal records',async()=>{
  const fixture=await registerSetup({...mealBlock,has_plan:true,confirmed:false,requires_change_reason:true,rows:[{...mealBlock.rows[0],value:'不就餐'},mealBlock.rows[1]]}),session=fixture.run('registerSession');
  await session.fillAll.click();assert.equal(session.fields[0].select.value,'就餐');assert.equal(session.save.disabled,true);assert.equal(fixture.context.calls.length,1);
  session.changeReason.value='重新核对后均实际就餐';session.changeReason.listeners.input();assert.equal(session.save.disabled,false);
});

test('fill all is unavailable for readonly, empty, attendance, saving or uncertain editors',async()=>{
  const readonly=await registerSetup({...mealBlock,editable:false});assert.equal(readonly.run('registerSession.fillAll'),null);
  const attendance=await registerSetup();assert.equal(attendance.run('registerSession.fillAll'),null);
  const empty=await registerSetup({...mealBlock,rows:[]});assert.equal(empty.run('registerSession.fillAll.disabled'),true);
  const fixture=await registerSetup(mealBlock),session=fixture.run('registerSession');await session.fillAll.click();setRegisterValue(fixture,0,'不就餐');
  let reject;fixture.context.poster=()=>new Promise((_,r)=>reject=r);fixture.run('request=()=>poster()');const saving=session.save.click();assert.equal(session.fillAll.disabled,true);await session.fillAll.click();assert.equal(session.fields[0].select.value,'不就餐');
  reject(Error('网络中断'));await saving;assert.equal(session.state,'uncertain');await session.fillAll.click();assert.equal(session.fields[0].select.value,'不就餐');assert.equal(session.fillAll.disabled,true);
});
