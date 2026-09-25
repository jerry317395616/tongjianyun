const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const read=file=>fs.readFileSync(path.join(__dirname,file),'utf8');
const DAY='2026-09-21';
const overview=(day=DAY,meal='lunch',rows=[{name:'R1'}])=>({day,meal,user_label:'老师',recipes:{rows},capabilities:{recipe:true,recipe_write:true}});
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
  for(const [source,expected] of [['data.capabilities.recipe=false','没有读取食谱明细的权限'],['data.recipes.rows=[]','尚未选定食谱'],['data.recipes.rows=[{name:"R1"},{name:"R2"}]','请先选择本周食谱']]){
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
