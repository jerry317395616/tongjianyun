const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const read=file=>fs.readFileSync(path.join(__dirname,file),'utf8');
const DAY='2026-09-21';
const overview=(day=DAY,meal='lunch',rows=[{name:'R1'}])=>({day,meal,user_label:'老师',recipes:{rows},week_recipes:{available:true,rows,has_more:false},capabilities:{recipe:true,recipe_write:true}});
const payload=(day=DAY,ingredient='大米',slot='lunch')=>({recipe:{title:'本周食谱',weekStart:DAY,weekEnd:'2026-09-25',workflowStatus:'草稿'},days:[{date:day,portions:[{slot,dishes:['米饭','青菜','第三道菜'],dishIngredientRows:[{dishName:'米饭',ingredient,amount:40,unit:'g'}]}]}]});
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
function setup(){
  const nodes=new Map(),events=new Map(),requests=[],emitted=[];
  let document;
  class Node{
    constructor(id){this.id=id;this.open=false;this.hidden=false;this.disabled=false;this.value='';this.innerHTML='';this.textContent='';this.dataset={};this.attrs={};this.listeners=new Map();this.focused=0;this.scrolled=0;this.dispatched=[];this.tagName='DIV';this.style={setProperty(k,v){this[k]=v;}};const classes=new Set();this.classList={add:(...items)=>items.forEach(item=>classes.add(item)),remove:(...items)=>items.forEach(item=>classes.delete(item)),contains:item=>classes.has(item),toggle:(item,force)=>{const add=force===undefined?!classes.has(item):force;if(add)classes.add(item);else classes.delete(item);return add;}};}
    addEventListener(type,handler){const list=this.listeners.get(type)||[];list.push(handler);this.listeners.set(type,list);}
    dispatchEvent(event){event.target=event.target||this;this.dispatched.push(event.type);for(const handler of this.listeners.get(event.type)||[])handler(event);if(event.bubbles)document.dispatchEvent(event);return true;}
    setAttribute(k,v){this.attrs[k]=String(v);}
    getAttribute(k){return this.attrs[k];}
    focus(){this.focused++;document.activeElement=this;}
    scrollIntoView(){this.scrolled++;}
    append(...children){this.children=(this.children||[]).concat(children);}
    replaceChildren(...children){this.children=children;}
    closest(){return null;}
    querySelectorAll(){return [];}
  }
  const getNode=id=>{if(!nodes.has(id))nodes.set(id,new Node(id));return nodes.get(id);};
  const cell=(day,meal)=>{const node=getNode('cell:'+day+':'+meal);node.dataset={workbenchDate:day,workbenchMeal:meal};return node;};
  document={hidden:false,activeElement:null,getElementById:getNode,createElement:tag=>new Node(tag),createDocumentFragment:()=>new Node('fragment'),
    querySelector(selector){const match=selector.match(/^\[data-workbench-date="([^"]+)"\]\[data-workbench-meal="([^"]+)"\]$/);return match?cell(match[1],match[2]):null;},
    querySelectorAll(selector){return selector==='#workbench-week [aria-expanded]'?[...nodes.values()].filter(node=>node.id.startsWith('cell:')):[];},
    addEventListener(type,handler){const list=events.get(type)||[];list.push(handler);events.set(type,list);},
    dispatchEvent(event){emitted.push(event);for(const handler of events.get(event.type)||[])handler(event);return true;}};
  class Event{constructor(type,options={}){this.type=type;Object.assign(this,options);}preventDefault(){this.defaultPrevented=true;}}
  const context=vm.createContext({document,URLSearchParams,location:{search:'?day='+DAY+'&meal=lunch'},history:{replaceState(){}},window:{addEventListener(){},confirm:()=>true,matchMedia:()=>({matches:false})},CustomEvent:Event,Event,setInterval(){},clearInterval(){},setTimeout(){},clearTimeout(){},requests});
  const run=source=>vm.runInContext(source,context);
  run(read('../public/meal_scene/state.js').replace(/export /g,''));run('const h=esc,n=number;');
  run(read('../public/meal_scene/app.js').replace(/^import .*;\r?\n/gm,'').replace(/load\(\);\s*$/,''));
  run('sceneBootstrap={recipe_calendar:true};'); // Recipe fixtures represent an authorized scene bootstrap.
  context.apiHandler=async(method,args)=>method==='get_recipe'?{payload:payload(args.recipe?.slice(0,10)==='2026-09-22'?'2026-09-22':DAY)}:overview(args.day||DAY,args.meal);
  run('api=async(method,args={},write=false)=>{requests.push({method,...args,write});return apiHandler(method,args,write);};');
  function seed(day=DAY,meal='lunch',recipePayload=payload(day)){
    context.fixtureData=overview(day,meal);context.fixturePayload=recipePayload;
    run('data=fixtureData;weekPayload={name:"R1",payload:fixturePayload};selectedRecipe="R1";ready=true;setMealContext({day:data.day,meal:data.meal});renderWeekOverview();');
  }
  function open(day=DAY,meal='lunch'){const selected=cell(day,meal);document.dispatchEvent({type:'click',target:{closest:selector=>selector==='[data-workbench-date][data-workbench-meal]'?selected:null}});}
  return {run,nodes,context,requests,emitted,document,seed,open,cell,node:getNode};
}

async function installViews(fixture){
  const source=read('../public/meal_scene/views.js').replace(/^import .*;\r?\n/gm,'').replace(/export /g,'');
  fixture.run('globalThis.testViews=(()=>{'+source+';return {initializeViews,showCalendar,showBusinessView};})()');
  fixture.context.viewHandler=async url=>({version:1,selection:JSON.parse(new URL(url,'https://qa.invalid').searchParams.get('selection_json')),title:'业务',subtitle:'',source:'原服务',generated_at:'now',components:[{type:'notice',text:'原生结果'}]});
  await fixture.run('testViews.initializeViews({request:(url)=>viewHandler(url)})');
  fixture.requests.length=0;fixture.emitted.length=0;
}

test('same-context recipe view waits for real overview and detail, not container visibility',async()=>{
  const fixture=setup(),{seed,run,context,requests,emitted,node}=fixture;seed();await installViews(fixture);
  let resolveDetail,settled=false;
  context.apiHandler=async(method,args)=>method==='get_recipe'?new Promise(resolve=>resolveDetail=resolve):overview(args.day,args.meal);
  const pending=run("testViews.showBusinessView({view:'recipe_week',day:'2026-09-21',meal:'lunch'})").then(result=>{settled=true;return result;});
  await flush();assert.equal(settled,false);assert.equal(node('recipe-workspace').hidden,false);
  assert.equal(emitted.some(event=>event.type==='meal-scene:view-status'&&event.detail.status==='rendered'),false);
  run('refreshMealData()');await flush();assert.equal(requests.length,2,'terminal refresh joins the in-flight post-request read');
  resolveDetail({payload:payload(DAY,'保存后的真实原料')});
  assert.equal((await pending).status,'rendered');fixture.open();assert.match(node('meal-ingredients-content').innerHTML,/保存后的真实原料/);
  assert.equal(requests.filter(row=>row.method==='get_overview').length,1);
  context.apiHandler=async(method,args)=>method==='get_recipe'?{payload:payload(DAY,'随后另一次保存的原料')}:overview(args.day,args.meal);
  run('refreshMealData()');await flush();
  assert.equal(requests.filter(row=>row.method==='get_overview').length,2,'completed reads are never cached across another save');
  assert.match(node('meal-ingredients-content').innerHTML,/随后另一次保存的原料/);
});

test('a recipe view does not reuse an older in-flight pre-save snapshot',async()=>{
  const fixture=setup(),{seed,run,context,requests,node}=fixture;seed();await installViews(fixture);
  let resolveOld;
  context.apiHandler=async(method,args)=>method==='get_recipe'?new Promise(resolve=>resolveOld=resolve):overview(args.day,args.meal);
  const old=run('load()');await flush();
  context.apiHandler=async(method,args)=>method==='get_recipe'?{payload:payload(DAY,'刚保存的原料')}:overview(args.day,args.meal);
  assert.equal((await run("testViews.showBusinessView({view:'recipe_week',day:'2026-09-21',meal:'lunch'})")).status,'rendered');
  resolveOld({payload:payload(DAY,'旧请求原料')});assert.equal((await old).status,'superseded');fixture.open();
  assert.match(node('meal-ingredients-content').innerHTML,/刚保存的原料/);assert.doesNotMatch(node('meal-ingredients-content').innerHTML,/旧请求原料/);
  assert.equal(requests.filter(row=>row.method==='get_overview').length,2);
});

test('failed overview or recipe detail yields failed and a real retry, never rendered',async()=>{
  for(const failingMethod of ['get_overview','get_recipe']){
    const fixture=setup(),{seed,run,context,node,emitted}=fixture;seed();await installViews(fixture);
    context.apiHandler=async(method,args)=>{if(method===failingMethod)throw Error('本次周历读取失败');return overview(args.day,args.meal);};
    const result=await run("testViews.showBusinessView({view:'recipe_week',day:'2026-09-21',meal:'lunch'})");
    assert.equal(result.status,'failed');assert.match(node('view-status').textContent,/本次周历读取失败/);
    assert.equal(emitted.some(event=>event.type==='meal-scene:view-status'&&event.detail.status==='rendered'),false);
    context.apiHandler=async(method,args)=>method==='get_recipe'?{payload:payload()}:overview(args.day,args.meal);
    assert.equal((await run("testViews.showBusinessView({view:'recipe_week',day:'2026-09-21',meal:'lunch'})")).status,'rendered');
  }
});

test('a late calendar read cannot report rendered or replace a newer business view',async()=>{
  const fixture=setup(),{seed,run,context,node}=fixture;seed();await installViews(fixture);let resolveDetail;
  context.apiHandler=async(method,args)=>method==='get_recipe'?new Promise(resolve=>resolveDetail=resolve):overview(args.day,args.meal);
  const pending=run("testViews.showBusinessView({view:'recipe_week',day:'2026-09-21',meal:'lunch'})");await flush();
  assert.equal((await run("testViews.showBusinessView({view:'students'})")).status,'rendered');
  resolveDetail({payload:payload()});assert.equal((await pending).status,'superseded');
  assert.equal(node('recipe-workspace').hidden,true);assert.equal(node('business-view').hidden,false);
});

test('calendar read rejects a mismatched context and a missing or denied week projection',async()=>{
  for(const mode of ['wrong-context','old-server','denied']){
    const fixture=setup(),{seed,run,context,node}=fixture;seed();await installViews(fixture);
    context.apiHandler=async(method,args)=>{assert.equal(method,'get_overview');const result=overview(args.day,args.meal);if(mode==='wrong-context')result.day='2026-09-22';if(mode==='old-server')delete result.week_recipes;if(mode==='denied')result.week_recipes.available=false;return result;};
    assert.equal((await run("testViews.showBusinessView({view:'recipe_week',day:'2026-09-21',meal:'lunch'})")).status,'failed');
    assert.match(node('view-status').textContent,/不一致|尚未更新|权限/);
  }
});

test('missing recipe detail cannot be acknowledged as a rendered empty calendar',async()=>{
  const fixture=setup(),{seed,run,context,node}=fixture;seed();await installViews(fixture);
  context.apiHandler=async(method,args)=>method==='get_recipe'?{}:overview(args.day,args.meal);
  assert.equal((await run("testViews.showBusinessView({view:'recipe_week',day:'2026-09-21',meal:'lunch'})")).status,'failed');
  assert.match(node('view-status').textContent,/食谱明细返回不完整/);assert.equal(run('weekPayload'),null);
});

test('weekend calendar uses weekly recipes without changing the user date or claiming weekend service',async()=>{
  const fixture=setup(),{seed,run,context,node}=fixture;seed();await installViews(fixture);
  context.apiHandler=async(method,args)=>{if(method==='get_recipe')return {payload:payload()};const result=overview(args.day,args.meal);result.recipes={rows:[],available:true,has_more:false};return result;};
  const result=await run("testViews.showBusinessView({view:'recipe_week',day:'2026-09-27',meal:'dinner'})");
  assert.equal(result.status,'rendered');assert.equal(run('mealContext().day'),'2026-09-27');assert.equal(run('mealContext().meal'),'dinner');
  assert.equal(node('week-title').textContent,'2026-09-21 — 2026-09-25');assert.match(node('workbench-week').innerHTML,/<b>米饭<\/b>/);
  assert.doesNotMatch(node('workbench-week').innerHTML,/data-workbench-date="2026-09-27"/);
  assert.equal(run('data.recipes.rows.length'),0);assert.equal(run('data.week_recipes.rows.length'),1);
});

test('stored Saturday and Sunday dishes expand the same week and both ingredients remain clickable',async()=>{
  const fixture=setup(),{seed,run,context,node,open}=fixture;
  const saved=payload();saved.recipe.weekEnd='2026-09-27';
  for(const [day,dish,ingredient] of [['2026-09-26','周六青菜粥','周六大米'],['2026-09-27','周日蒸蛋','周日鸡蛋']]){
    saved.days.push({date:day,portions:[{slot:'lunch',dishes:[dish],dishIngredientRows:[{dishName:dish,ingredient,amount:35,unit:'g'}]}]});
  }
  seed(DAY,'lunch',saved);assert.equal(node('workbench-week').style['--workbench-days'],'7');
  assert.equal(node('week-title').textContent,'2026-09-21 — 2026-09-27');
  assert.match(node('workbench-week').innerHTML,/<b>周六青菜粥<\/b>/);assert.match(node('workbench-week').innerHTML,/<b>周日蒸蛋<\/b>/);
  context.apiHandler=async(method,args)=>method==='get_recipe'?{payload:saved}:overview(args.day,args.meal);
  for(const [day,ingredient] of [['2026-09-26','周六大米'],['2026-09-27','周日鸡蛋']]){
    open(day,'lunch');await run('load()');assert.equal(run('mealContext().day'),day);
    assert.match(node('meal-ingredients-title').textContent,new RegExp(day));assert.match(node('meal-ingredients-content').innerHTML,new RegExp(ingredient));
    assert.match(node('meal-ingredients-content').innerHTML,/35 g/);
  }
  open('2026-09-27','dinner');await run('load()');
  assert.match(node('meal-ingredients-content').innerHTML,/尚未编排，不代表不供餐/);
});

test('empty weekend placeholders or another week never expand or masquerade as this week meals',()=>{
  const fixture=setup(),{seed,run,context,node}=fixture;
  const blank=payload();blank.days.push({date:'2026-09-26',portions:[]},{date:'2026-09-27',portions:[{slot:'lunch',dishes:[],dishIngredientRows:[]}]});
  seed(DAY,'lunch',blank);assert.equal(node('workbench-week').style['--workbench-days'],'5');
  const other=payload('2026-10-04','其他周日原料');other.recipe.weekStart='2026-09-28';other.recipe.weekEnd='2026-10-04';
  seed(DAY,'lunch',other);assert.equal(node('workbench-week').style['--workbench-days'],'5');
  assert.doesNotMatch(node('workbench-week').innerHTML,/<b>米饭<\/b>|其他周日原料/);assert.match(node('week-caption').textContent,/不覆盖本周/);
  context.weekPayloadWithOnlySaturday=payload('2026-09-26','周六原料');context.weekPayloadWithOnlySaturday.recipe.weekEnd='2026-09-26';
  run('weekPayload.payload=weekPayloadWithOnlySaturday;renderWeekOverview()');
  assert.equal(node('workbench-week').style['--workbench-days'],'7');
  assert.match(node('workbench-week').innerHTML,/data-workbench-date="2026-09-27"[^>]*><b>未编排<\/b>/);
});

test('narrow calendar picker includes stored weekend dates without changing context until a meal is clicked',async()=>{
  const fixture=setup(),{seed,run,context,node,open}=fixture;
  context.window.matchMedia=()=>({matches:true});
  const saved=payload();saved.recipe.weekEnd='2026-09-27';saved.days.push(payload('2026-09-27','周日食材').days[0]);
  seed(DAY,'lunch',saved);assert.match(node('week-mobile-day').innerHTML,/<option value="2026-09-26"/);assert.match(node('week-mobile-day').innerHTML,/<option value="2026-09-27"/);
  node('week-mobile-day').value='2026-09-27';node('week-mobile-day').onchange();
  assert.equal(run('mobileWeekDay'),'2026-09-27');assert.equal(run('mealContext().day'),DAY);
  assert.match(node('workbench-week').innerHTML,/class="workbench-week-cell [^"]*mobile-day[^"]*" data-workbench-date="2026-09-27"/);
  context.apiHandler=async(method,args)=>method==='get_recipe'?{payload:saved}:overview(args.day,args.meal);
  open('2026-09-27','lunch');await run('load()');assert.equal(run('mealContext().day'),'2026-09-27');
  assert.match(node('meal-ingredients-content').innerHTML,/周日食材/);assert(node('meal-ingredients-panel').scrolled>0);
  const css=read('../public/meal_scene/app.css');
  assert.match(css,/repeat\(var\(--workbench-days,5\),minmax\(0,1fr\)\)/);
  assert.match(css,/\.workbench-week-cell:not\(\.mobile-day\)\{display:none\}/);
});

test('an empty-ingredient saved recipe remains a draft with explicit missing detail and edit prompt only',async()=>{
  const fixture=setup(),{seed,run,context,node,requests}=fixture;seed();await installViews(fixture);
  const saved=payload();saved.days[0].portions[0].dishIngredientRows=[];
  context.apiHandler=async(method,args)=>method==='get_recipe'?{payload:saved}:overview(args.day,args.meal);
  assert.equal((await run("testViews.showBusinessView({view:'recipe_week',day:'2026-09-21',meal:'lunch'})")).status,'rendered');
  fixture.open();assert.match(node('meal-ingredients-content').innerHTML,/食材明细未填写/);assert.doesNotMatch(node('meal-ingredients-content').innerHTML,/0 g/);
  assert.match(node('meal-ingredients-caption').textContent,/草稿.*不能作为采购依据/);run('askToEditMeal()');
  assert.equal(node('chat-input').value,'帮我修改 2026-09-21 午餐的食谱：');assert.equal(requests.some(item=>item.write),false);
});

test('ingredient region is hidden initially and belongs to the calendar workspace',()=>{
  const html=read('../www/tongjianyun-meal-scene.html');
  assert.match(html,/<section[^>]*id="meal-ingredients-panel"[^>]*\bhidden/);
  assert(html.indexOf('id="recipe-workspace"')<html.indexOf('id="meal-ingredients-panel"'));
  assert(html.indexOf('id="meal-ingredients-panel"')<html.indexOf('id="business-view"'));
  const {seed,node}=setup();seed();assert.equal(node('meal-ingredients-panel').hidden,true);
});

test('week cells show every dish but never inline ingredients or quantities',()=>{
  const {seed,node}=setup();seed(DAY,'lunch',payload(DAY,'仅在明细显示的原料'));
  const html=node('workbench-week').innerHTML;
  assert.match(html,/<b>米饭<\/b><b>青菜<\/b><b>第三道菜<\/b>/);
  assert.doesNotMatch(html,/仅在明细显示的原料|40 g|另有 \d+ 道菜/);
  assert.match(html,/aria-controls="meal-ingredients-panel" aria-expanded="false"/);
});

test('clicking the selected meal opens only its stored ingredients and original unit',()=>{
  const {seed,open,node,requests}=setup();const data=payload();data.days[0].portions[0].dishIngredientRows[0].unit='克';seed(DAY,'lunch',data);open();
  assert.equal(node('meal-ingredients-panel').hidden,false);
  assert.match(node('meal-ingredients-content').innerHTML,/大米/);
  assert.match(node('meal-ingredients-content').innerHTML,/40 克/);
  assert.match(node('meal-ingredients-caption').textContent,/每生用量.*非全园采购总量.*草稿/);
  assert.equal(node('meal-ingredients-ask').disabled,false);
  assert.equal(requests.length,0);
});

test('amount formatter preserves real zero, decimals and source units without conversions',()=>{
  const {run,context}=setup();
  for(const [row,expected] of [[{amount:0,unit:'g'},'0 g'],[{amount:1.25,unit:'kg'},'1.25 kg'],[{amount:' 20 ',unit:'毫升'},'20 毫升'],[{amount:2,unit:'个'},'2 个'],[{amount:3,unit:''},'3 （单位未填写）']]){
    context.row=row;assert.equal(run('ingredientAmount(row)'),expected);
  }
});

test('missing and nonnumeric amounts never turn into a false zero',()=>{
  const {run,context}=setup();
  for(const amount of [null,undefined,'','  ','abc',NaN,Infinity]){context.row={amount,unit:'g'};assert.equal(run('ingredientAmount(row)'),'未填写');}
});

test('small nonzero amounts never round to zero in their original units',()=>{
  const {run}=setup();
  assert.equal(run('ingredientAmount({amount:0.0004,unit:"kg"})'),'0.0004 kg');
  assert.equal(run('ingredientAmount({amount:0.0000002,unit:"kg"})'),'0.0000002 kg');
});

test('ingredient markup escapes dish, ingredient and unit strings and keeps orphan rows',()=>{
  const {run,context}=setup();context.portion={dishes:['<img onerror="x">','没有食材的菜'],dishIngredientRows:[{dishName:'<img onerror="x">',ingredient:'<script>alert(1)</script>',amount:2,unit:'g<&"'},{ingredient:'未关联原料',amount:0,unit:'个'}]};
  const html=run('mealIngredientsMarkup(portion)');
  assert.match(html,/&lt;img onerror=&quot;x&quot;&gt;/);assert.match(html,/&lt;script&gt;alert\(1\)&lt;\/script&gt;/);assert.match(html,/g&lt;&amp;&quot;/);
  assert.doesNotMatch(html,/<script|<img/);assert.match(html,/没有食材的菜/);assert.match(html,/食材明细未填写/);assert.match(html,/未关联菜品/);assert.match(html,/未关联原料/);
});

test('missing meal, empty meal and missing ingredient name remain explicit',()=>{
  const {run}=setup();
  assert.match(run('mealIngredientsMarkup(null)'),/尚未编排，不代表不供餐/);
  assert.match(run('mealIngredientsMarkup({dishes:[]})'),/尚未填写菜品和食材/);
  assert.match(run('mealIngredientsMarkup({dishes:["菜"],dishIngredientRows:[{dishName:"菜",amount:1,unit:"g"}]})'),/食材名称未填写/);
});

test('API meal keys map to morningSnack and snack payload slots',()=>{
  for(const [meal,slot] of [['morning_snack','morningSnack'],['afternoon_snack','snack']]){
    const {seed,open,node}=setup();seed(DAY,meal,payload(DAY,'对应点心原料',slot));open(DAY,meal);
    assert.match(node('meal-ingredients-content').innerHTML,/对应点心原料/);
  }
});

test('no permission, no selected recipe and multiple recipes cannot pretend to have ingredients',()=>{
  for(const [source,expected] of [['data.capabilities.recipe=false','没有读取食谱明细的权限'],['data.week_recipes.rows=[]','尚未选定食谱'],['data.week_recipes.rows=[{name:"R1"},{name:"R2"}]','请先选择本周食谱']]){
    const {seed,run,open,node}=setup();seed();run('weekPayload=null;'+source);open();
    assert.match(node('meal-ingredients-content').innerHTML,new RegExp(expected));assert.equal(node('meal-ingredients-ask').disabled,true);
    assert.doesNotMatch(node('meal-ingredients-content').innerHTML,/大米|40 g/);
  }
});

test('read-only and archived recipes cannot prefill an edit request',()=>{
  for(const change of ['data.capabilities.recipe_write=false','weekPayload.payload.recipe.workflowStatus="已归档"']){
    const {seed,run,open,node}=setup();seed();run(change);open();assert.equal(node('meal-ingredients-ask').disabled,true);run('askToEditMeal()');assert.equal(node('chat-input').value,'');
  }
});

test('loading or an error replaces old detail content without inventing an empty result',()=>{
  const {seed,open,run,node}=setup();seed();open();run('ready=false;renderMealIngredients()');
  assert.match(node('meal-ingredients-content').innerHTML,/正在读取/);assert.doesNotMatch(node('meal-ingredients-content').innerHTML,/大米/);assert.equal(node('meal-ingredients-ask').disabled,true);
  run('weekReadError="没有权限 <img>";renderMealIngredients()');
  assert.match(node('meal-ingredients-content').innerHTML,/没有权限 &lt;img&gt;/);assert.doesNotMatch(node('meal-ingredients-content').innerHTML,/大米|<img>/);
});

test('failed detail fetch clears the previous recipe and renders the failure',async()=>{
  const {seed,open,run,node,context}=setup();seed();open();context.apiHandler=async(method,args)=>{if(method==='get_recipe')throw Error('食谱明细不可读取');return overview(args.day,args.meal);};
  await run('load()');assert.equal(run('weekPayload'),null);assert.match(node('meal-ingredients-content').innerHTML,/食谱明细不可读取/);assert.equal(node('meal-ingredients-ask').disabled,true);
});

test('a repeated click while recipe details are pending still shows loading, not a false unselected state',async()=>{
  const {seed,open,run,node,context}=setup();seed();open();let resolve;
  context.apiHandler=async(method,args)=>method==='get_recipe'?new Promise(r=>resolve=r):overview(args.day,args.meal);
  const pending=run('load()');await flush();open();
  assert.equal(run('ready'),false);assert.match(node('meal-ingredients-content').innerHTML,/正在读取/);assert.doesNotMatch(node('meal-ingredients-content').innerHTML,/尚未选定食谱|大米/);
  resolve({payload:payload()});await pending;assert.match(node('meal-ingredients-content').innerHTML,/大米/);
});

test('failed overview fetch removes visible old ingredients while retaining a retryable selection',async()=>{
  const {seed,open,run,node,context}=setup();seed();open();context.apiHandler=async()=>{throw Error('网络读取失败');};
  await run('load()');assert.equal(node('meal-ingredients-panel').hidden,false);assert.match(node('meal-ingredients-content').innerHTML,/网络读取失败/);assert.doesNotMatch(node('meal-ingredients-content').innerHTML,/大米/);
});

test('automatic refresh replaces open ingredients with the latest permission-checked payload',async()=>{
  const {seed,open,run,node,context}=setup();seed();open();context.apiHandler=async(method,args)=>method==='get_recipe'?{payload:payload(DAY,'更新后的原料')}:overview(args.day,args.meal);
  await run('load(true)');assert.equal(node('meal-ingredients-panel').hidden,false);assert.match(node('meal-ingredients-content').innerHTML,/更新后的原料/);assert.doesNotMatch(node('meal-ingredients-content').innerHTML,/大米/);
});

test('rapid selection ignores a slow old recipe response and never shows its ingredients under a new date',async()=>{
  const {seed,open,run,node,context}=setup();seed();open();let resolveOld;
  context.apiHandler=async(method,args)=>{if(method==='get_overview')return overview(args.day,args.meal,[{name:args.day}]);if(args.recipe===DAY)return new Promise(resolve=>resolveOld=resolve);return {payload:payload('2026-09-22','周二最新原料')};};
  const old=run('load()');await flush();assert.equal(typeof resolveOld,'function');
  open('2026-09-22','lunch');await flush();assert.match(node('meal-ingredients-title').textContent,/2026-09-22/);assert.match(node('meal-ingredients-content').innerHTML,/周二最新原料/);
  resolveOld({payload:payload(DAY,'迟到的周一原料')});await old;
  assert.match(node('meal-ingredients-content').innerHTML,/周二最新原料/);assert.doesNotMatch(node('meal-ingredients-content').innerHTML,/迟到的周一原料/);assert.equal(run('data.day'),'2026-09-22');
});

test('a stale failed request cannot replace a newer successful ingredient view with an error',async()=>{
  const {seed,open,run,node,context}=setup();seed();open();let rejectOld;
  context.apiHandler=async(method,args)=>{if(method==='get_overview')return overview(args.day,args.meal,[{name:args.day}]);if(args.recipe===DAY)return new Promise((_,reject)=>rejectOld=reject);return {payload:payload('2026-09-22','正确原料')};};
  const old=run('load()');await flush();open('2026-09-22','lunch');await flush();rejectOld(Error('旧请求失败'));await old;
  assert.match(node('meal-ingredients-content').innerHTML,/正确原料/);assert.doesNotMatch(node('meal-ingredients-content').innerHTML,/旧请求失败/);assert.equal(run('weekReadError'),'');
});

test('closing returns focus and a later render or refresh does not reopen details',async()=>{
  const {seed,open,run,node,cell}=setup();seed();open();cell(DAY,'lunch').setAttribute('aria-expanded','true');run('closeMealIngredients()');
  assert.equal(node('meal-ingredients-panel').hidden,true);assert.equal(cell(DAY,'lunch').focused,1);assert.equal(cell(DAY,'lunch').attrs['aria-expanded'],'false');
  run('renderWeekOverview()');await run('load(true)');assert.equal(node('meal-ingredients-panel').hidden,true);assert.equal(run('ingredientSelection'),null);
});

test('closing during a pending load keeps details closed when the response arrives',async()=>{
  const {seed,open,run,node,context}=setup();seed();open();let resolve;
  context.apiHandler=async(method,args)=>method==='get_recipe'?new Promise(r=>resolve=r):overview(args.day,args.meal);
  const pending=run('load()');await flush();run('closeMealIngredients(false)');resolve({payload:payload()});await pending;assert.equal(node('meal-ingredients-panel').hidden,true);
});

test('changing the mobile visible day closes details without overwriting conversation context',()=>{
  const {seed,open,node,run}=setup();seed();open();node('week-mobile-day').value='2026-09-22';node('week-mobile-day').onchange();
  assert.equal(node('meal-ingredients-panel').hidden,true);assert.equal(run('mobileWeekDay'),'2026-09-22');assert.equal(run('mealContext().day'),DAY);
});

test('Escape closes ingredients first and restores the selected meal focus',()=>{
  const {seed,open,document,node,cell}=setup();seed();open();const event={type:'keydown',key:'Escape',target:node('meal-ingredients-close'),preventDefault(){this.defaultPrevented=true;}};document.dispatchEvent(event);
  assert.equal(event.defaultPrevented,true);assert.equal(node('meal-ingredients-panel').hidden,true);assert.equal(cell(DAY,'lunch').focused,1);
});

test('registered business-view transitions close the details and returning to the calendar does not reopen them',async()=>{
  const {seed,open,run,node}=setup();seed();
  const views=read('../public/meal_scene/views.js').replace(/^import .*;\r?\n/gm,'').replace(/export /g,'');
  run('globalThis.testViews=(()=>{'+views+';return {initializeViews,showCalendar,showBusinessView};})()');
  run('testViews.initializeViews({request:async()=>({version:1,selection:{view:"students"},title:"在园学生",subtitle:"可见范围",components:[],source:"Student",generated_at:"now"})})');open();
  await run('testViews.showBusinessView({view:"students"})');assert.equal(node('meal-ingredients-panel').hidden,true);assert.equal(run('ingredientSelection'),null);assert.equal(node('recipe-workspace').hidden,true);
  run('testViews.showCalendar()');assert.equal(node('recipe-workspace').hidden,false);assert.equal(node('meal-ingredients-panel').hidden,true);
});

test('ask only prefills a contextual message, focuses input and never submits or writes',()=>{
  const {seed,open,run,node,requests,emitted}=setup();seed();open();run('askToEditMeal()');
  assert.equal(node('chat-input').value,`帮我修改 ${DAY} 午餐的食谱：`);assert.equal(node('chat-input').focused,1);assert(node('chat-input').dispatched.includes('input'));
  assert.equal(node('meal-ingredients-panel').hidden,true);assert.equal(requests.length,0);assert(!emitted.some(event=>event.type==='submit'));
});

test('ask preserves unsent text and attached files',()=>{
  const {seed,open,run,node,requests}=setup();seed();open();node('chat-input').value='正在输入的内容';node('chat-file').files=[{name:'食谱.xlsx'}];node('chat-file-chip').hidden=false;run('askToEditMeal()');
  assert.equal(node('chat-input').value,'正在输入的内容');assert.deepEqual(node('chat-file').files,[{name:'食谱.xlsx'}]);assert.equal(node('chat-file-chip').hidden,false);assert.equal(requests.length,0);
});

test('ask cannot alter a disabled assistant input or submit while a task is running',()=>{
  const {seed,open,run,node,requests}=setup();seed();open();node('chat-input').disabled=true;node('chat-input').value='保留';run('askToEditMeal()');
  assert.equal(node('chat-input').value,'保留');assert.equal(node('meal-ingredients-panel').hidden,false);assert.match(node('toast').textContent,/稍后/);assert.equal(requests.length,0);
});
