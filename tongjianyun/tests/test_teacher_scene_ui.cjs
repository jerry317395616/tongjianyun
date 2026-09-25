const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const read=file=>fs.readFileSync(path.join(__dirname,'../public/meal_scene',file),'utf8');
const plain=source=>source.replace(/^import .*;\r?\n/gm,'').replace(/export /g,'');
const flush=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const teacher={version:1,user:'teacher@example.invalid',user_label:'合成教师',day:'2026-09-23',meal:'lunch',recipe_calendar:false,
  chat:{allowed:false,mode:'unavailable',reason:'业务对话尚未开通，可先在左侧办理有权访问的业务。'},
  default_view:{view:'classroom_day',day:'2026-09-23',meal:'lunch',group:'QA Class A'},
  scope:{group_count:1,selected_group:'QA Class A'},phase:'views_only_for_non_admin',navigation:[
    {label:'点名',selection:{view:'classroom_day'}},{label:'核对用餐',selection:{view:'meal_counts'}},
    {label:'可用业务',selection:{view:'frappe_catalog'}}]};
class Element{
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.textContent='';this.style={};this.attrs={};this.dataset={};this.listeners={};this.classList={toggle(){},remove(){}};this.hidden=false;this.value='';this.open=false;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  insertBefore(node,anchor){const index=this.children.indexOf(anchor);if(index<0)this.children.push(node);else this.children.splice(index,0,node);}
  setAttribute(k,v){this.attrs[k]=String(v);}
  addEventListener(type,handler){(this.listeners[type]??=[]).push(handler);}
  click(){return this.listeners.click?.[0]();}
  change(){return this.listeners.change?.[0]();}
  focus(){}
}
function environment(){
  const nodes=new Map(),events=new Map(),calls=[],intervals=[],history=[];
  const document={hidden:false,getElementById(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},
    createElement:tag=>new Element(tag),createDocumentFragment:()=>new Element('fragment'),querySelector:()=>new Element(),querySelectorAll:()=>[],
    addEventListener(type,handler){(events.get(type)||events.set(type,[]).get(type)).push(handler);},
    dispatchEvent(event){for(const handler of events.get(event.type)||[])handler(event);return true;}};
  const context=vm.createContext({document,URL,URLSearchParams,location:{search:'?day=2026-09-23&meal=lunch&group=QA+Class+A',origin:'https://test.invalid'},
    history:{replaceState(...args){history.push(args);}},window:{confirm:()=>true,addEventListener(){},matchMedia:()=>({matches:false})},
    CustomEvent:class{constructor(type,options={}){this.type=type;this.detail=options.detail;}},setTimeout(){},clearTimeout(){},
    setInterval(handler,time){intervals.push({handler,time});return intervals.length;},clearInterval(){},calls,bootstrap:teacher});
  const run=code=>vm.runInContext(code,context);
  run(plain(read('state.js')));
  return {nodes,events,calls,intervals,history,context,document,run};
}
function viewFixture(){
  const fixture=environment();fixture.run(plain(read('views.js')));
  fixture.context.fetcher=async url=>{
    let selection=JSON.parse(new URL(url,'https://test.invalid').searchParams.get('selection_json'));
    fixture.calls.push({url,selection});
    // Native selection() treats students as all-date master data, not a dated roster.
    if(selection.view==='students')selection={view:'students',presentation:'table'};
    return {version:1,selection,title:selection.view,subtitle:'当前可见范围',source:'QA native source',generated_at:'now',components:[{type:'notice',text:'未登记不等于缺勤'}]};
  };
  return fixture;
}

test('teacher left-side views initialize without chat or recipe requests',async()=>{
  const {run,calls,nodes}=viewFixture();
  const result=await run('initializeViews({request:fetcher,bootstrap})');
  assert.equal(result.status,'rendered');assert.equal(calls.length,1);assert.equal(calls[0].selection.view,'classroom_day');
  assert.equal(calls[0].selection.group,'QA Class A');assert.equal(nodes.get('recipe-workspace').hidden,true);
  assert.equal(nodes.get('business-view').hidden,false);assert.equal(nodes.get('view-back').textContent,'← 场景首页');
  assert(calls.every(call=>!call.url.includes('meal_chat')&&!call.url.includes('get_overview')));
});

test('teacher navigation and homepage remain in-scene and carry exact selected context',async()=>{
  const {run,calls,nodes}=viewFixture();await run('initializeViews({request:fetcher,bootstrap})');
  const navigation=run('sceneNavigation');await navigation.buttons[1].button.click();
  assert.equal(calls.at(-1).selection.view,'meal_counts');assert.equal(calls.at(-1).selection.group,'QA Class A');
  navigation.day.value='2026-09-22';navigation.meal.value='dinner';await navigation.day.change();
  assert.equal(run('mealContext().day'),'2026-09-22');assert.equal(run('mealContext().meal'),'dinner');
  await nodes.get('view-back').click();
  assert.equal(calls.at(-1).selection.view,'classroom_day');assert.equal(calls.at(-1).selection.day,'2026-09-22');
  assert.equal(calls.at(-1).selection.meal,'dinner');assert.equal(nodes.get('recipe-workspace').hidden,true);
});

test('teacher refresh reads current business only and keeps the calendar unavailable',async()=>{
  const {run,calls,nodes}=viewFixture();await run('initializeViews({request:fetcher,bootstrap})');
  await run('showBusinessView({view:"meal_counts",group:"QA Class A",day:"2026-09-22",meal:"dinner"})');
  const before=calls.length;run('refreshMealData()');await flush();assert.equal(calls.length,before+1);
  assert.equal(calls.at(-1).selection.view,'meal_counts');assert.equal(nodes.get('recipe-workspace').hidden,true);
  assert.equal(run('showCalendar().status'),'blocked');assert.equal(nodes.get('recipe-workspace').hidden,true);
});

test('changing date on a catalog or student view carries forward to classroom navigation',async()=>{
  for(const view of ['students','frappe_catalog']){
    const {run,calls}=viewFixture();await run('initializeViews({request:fetcher,bootstrap})');
    await run(`showBusinessView({view:'${view}',day:'2026-09-23',meal:'lunch'})`);
    const navigation=run('sceneNavigation');navigation.day.value='2026-09-21';navigation.meal.value='breakfast';await navigation.day.change();
    assert.equal(run('mealContext().day'),'2026-09-21');assert.equal(run('mealContext().meal'),'breakfast');
    await navigation.buttons[0].button.click();assert.equal(calls.at(-1).selection.view,'classroom_day');
    assert.equal(calls.at(-1).selection.day,'2026-09-21');assert.equal(calls.at(-1).selection.meal,'breakfast');
  }
});

test('date changes respect unsaved edits and revert controls when rejected',async()=>{
  const {run,context,calls}=viewFixture();await run('initializeViews({request:fetcher,bootstrap})');
  run('registerSession={dirty:true,state:"ready"}');context.window.confirm=()=>false;
  const navigation=run('sceneNavigation'),before=calls.length;navigation.day.value='2026-09-20';await navigation.day.change();
  assert.equal(calls.length,before);assert.equal(navigation.day.value,'2026-09-23');assert.equal(run('mealContext().day'),'2026-09-23');
  assert.equal((await navigation.buttons[1].button.click()).status,'blocked');
});

test('bootstrap-selected student or catalog home also works without a teacher class',async()=>{
  for(const view of ['students','frappe_catalog']){
    const {run,context,calls}=viewFixture();context.bootstrap={...teacher,scope:{group_count:0,selected_group:null},default_view:{view},navigation:[]};
    assert.equal((await run('initializeViews({request:fetcher,bootstrap})')).status,'rendered');
    assert.equal(calls[0].selection.view,view);assert.equal(calls[0].selection.group,undefined);
  }
});

test('administrator still starts on weekly recipes without a navigation toolbar',()=>{
  const {run,context,calls,nodes}=viewFixture();context.bootstrap={...teacher,recipe_calendar:true,chat:{allowed:true,mode:'admin_project'},default_view:{view:'recipe_week'}};
  run('initializeViews({request:fetcher,bootstrap})');assert.equal(calls.length,0);
  assert.equal(nodes.get('recipe-workspace').hidden,false);assert.equal(run('sceneNavigation'),null);
  assert.equal(nodes.get('view-back').textContent,'← 回到食谱');
});

test('teacher calendar bootstrap never calls overview or creates a refresh interval',async()=>{
  const {run,context,calls,intervals,document,nodes}=environment();context.getSceneBootstrap=async()=>teacher;
  run('const h=esc,n=number;');run(plain(read('app.js')).replace(/load\(\);\s*$/,''));
  run('api=async(method)=>{calls.push({method});throw Error("unexpected recipe request")};');
  await run('load()');await run('load(true)');run('refreshMealData()');document.dispatchEvent({type:'visibilitychange'});await flush();
  assert.equal(calls.length,0);assert.equal(intervals.length,0);assert.equal(nodes.get('recipe-workspace').hidden,true);
  assert.equal(run('mealContext().day'),teacher.day);assert.equal(nodes.get('user-label').textContent,teacher.user_label);
});

test('failed bootstrap cannot fall back to recipe access',async()=>{
  const {run,context,calls,intervals,nodes}=environment();context.getSceneBootstrap=async()=>{throw Error('登录失效，请刷新后重试。')};
  run('const h=esc,n=number;');run(plain(read('app.js')).replace(/load\(\);\s*$/,''));run('api=async(method)=>calls.push({method})');
  await run('load()');assert.equal(calls.length,0);assert.equal(intervals.length,0);assert.equal(nodes.get('recipe-workspace').hidden,true);
  assert.match(nodes.get('message').textContent,/登录失效/);assert.equal(run('sceneBootstrap'),null);
});

test('chat initializes teacher views but never requests conversation or starts SSE',async()=>{
  const {run,context,calls,nodes}=environment();context.getSceneBootstrap=async()=>teacher;
  context.initializeViews=options=>{calls.push({initialize:options.bootstrap});return Promise.resolve({status:'rendered'});};
  context.currentViewContext=()=>teacher.default_view;context.showBusinessView=()=>{};context.context=()=>({day:teacher.day,meal:teacher.meal});
  context.fetch=async url=>{throw Error('Unexpected chat request: '+url);};context.EventSource=class{constructor(){throw Error('Teacher SSE must not start');}};
  run(plain(read('chat.js')));await flush();
  assert.equal(calls.length,1);assert.equal(calls[0].initialize.chat.allowed,false);
  assert.equal(nodes.get('chat-form').hidden,true);assert.equal(nodes.get('chat-input').disabled,true);
  assert.equal(nodes.get('chat-messages').children.length,1);assert.match(nodes.get('chat-messages').children[0].textContent,/尚未开通/);
});

test('bootstrap module shares one request and forwards only day meal and optional group',async()=>{
  const {run,context,calls}=environment();context.fetch=async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>({message:teacher})};};
  run(plain(read('scene_bootstrap.js')));const first=run('getSceneBootstrap()'),second=run('getSceneBootstrap()');
  assert.equal(first,second);assert.equal(await first,teacher);assert.equal(calls.length,1);
  const url=new URL(calls[0].url,'https://test.invalid');assert.deepEqual([...url.searchParams.keys()],['day','meal','group']);
  assert.equal(url.searchParams.get('group'),'QA Class A');assert.equal(calls[0].options.credentials,'same-origin');
  assert.equal(calls[0].options.cache,'no-store');
});

test('failed chat bootstrap explains the failure and offers only a page reload',async()=>{
  const {run,context,calls,nodes}=environment();context.getSceneBootstrap=async()=>{throw Error('场景读取失败')};
  context.initializeViews=()=>calls.push('unexpected initialization');context.context=()=>({day:teacher.day,meal:teacher.meal});
  context.currentViewContext=()=>teacher.default_view;context.showBusinessView=()=>{};
  context.fetch=async()=>{throw Error('Unexpected request')};context.window.location={reload:()=>calls.push('reload')};
  run(plain(read('chat.js')));await flush();assert.equal(calls.length,0);assert.equal(nodes.get('chat-form').hidden,true);
  const children=nodes.get('chat-messages').children;assert.match(children[0].textContent,/场景读取失败/);
  assert.equal(children[1].textContent,'重新加载场景');children[1].click();assert.deepEqual(calls,['reload']);
});

test('bootstrap rejects unauthorized or malformed data and cannot retry into an allowed fallback',async()=>{
  for(const response of [{ok:false,status:403,json:async()=>({message:teacher})},
    {ok:true,json:async()=>({message:{...teacher,recipe_calendar:'false'}})},
    {ok:true,json:async()=>({message:{...teacher,chat:{allowed:'true'}}})}]){
    const {run,context,calls}=environment();context.fetch=async()=>{calls.push(1);return response;};run(plain(read('scene_bootstrap.js')));
    await assert.rejects(run('getSceneBootstrap()'));await assert.rejects(run('getSceneBootstrap()'));assert.equal(calls.length,1);
  }
});
