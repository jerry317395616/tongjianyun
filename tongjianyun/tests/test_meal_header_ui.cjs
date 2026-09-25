const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const read=file=>fs.readFileSync(path.join(__dirname,file),'utf8');
function setup(search=''){
  const nodes=new Map(),events=new Map(),requests=[];
  const document={hidden:false,getElementById(id){
    assert(!['day','meal','refresh'].includes(id),'removed header control requested: '+id);
    if(!nodes.has(id))nodes.set(id,{open:false,style:{},classList:{toggle(){},remove(){}},addEventListener(){},focus(){}});
    return nodes.get(id);
  },addEventListener(type,handler){const list=events.get(type)||[];list.push(handler);events.set(type,list);},dispatchEvent(event){for(const handler of events.get(event.type)||[])handler(event);}};
  const context=vm.createContext({document,URLSearchParams,location:{search},history:{replaceState(){}},window:{addEventListener(){},confirm:()=>true,matchMedia:()=>({matches:false})},CustomEvent:class{constructor(type,options={}){this.type=type;this.detail=options.detail;}},setInterval(){},clearInterval(){},setTimeout(){},clearTimeout(){},requests});
  const run=source=>vm.runInContext(source,context);
  run(read('../public/meal_scene/state.js').replace(/export /g,''));
  run('const h=esc,n=number;');
  run(read('../public/meal_scene/app.js').replace(/^import .*;\r?\n/gm,'').replace(/load\(\);\s*$/,''));
  run('sceneBootstrap={recipe_calendar:true};'); // Existing calendar tests run after authorized bootstrap.
  run("api=async(method,args)=>{requests.push({method,...args});return {day:args.day||'2026-09-25',meal:args.meal,user_label:'老师',recipes:{rows:[]}}};renderWeekOverview=()=>{};");
  return {run,requests,document};
}
test('header contains brand and account but no date, meal or refresh controls',()=>{
  const html=read('../www/tongjianyun-meal-scene.html');
  const header=html.split('<header class="topbar">')[1].split('</header>')[0];
  assert.match(header,/class="brand"/);assert.match(header,/class="account"/);
  assert.doesNotMatch(html,/id="(?:day|meal|refresh)"/);
  assert.doesNotMatch(header,/<(?:input|select|button)\b|class="filters"/);
});
test('deep link date and meal still initialize the workspace without controls',async()=>{
  const {run,requests}=setup('?day=2026-09-24&meal=dinner');await run('load()');
  assert.deepEqual(JSON.parse(JSON.stringify(requests[0])),{method:'get_overview',day:'2026-09-24',meal:'dinner'});
  assert.equal(run('mealContext().meal'),'dinner');
});
test('missing or invalid URL values keep server-date and lunch defaults',async()=>{
  for(const search of ['','?day=bad&meal=bad']){
    const {run,requests}=setup(search);await run('load()');
    assert.equal(requests[0].day,'');assert.equal(requests[0].meal,'lunch');
    assert.equal(run('mealContext().day'),'2026-09-25');
  }
});
test('weekly cell selection and completion refresh do not need header DOM',async()=>{
  const {run,requests,document}=setup('?day=2026-09-24&meal=lunch');await run('load()');
  const selected={dataset:{workbenchDate:'2026-09-22',workbenchMeal:'morning_snack'}};
  document.dispatchEvent({type:'click',target:{closest:selector=>selector==='[data-workbench-date][data-workbench-meal]'?selected:null}});
  await Promise.resolve();
  assert.equal(run('mealContext().day'),'2026-09-22');assert.equal(run('mealContext().meal'),'morning_snack');
  run('refreshMealData()');await Promise.resolve();
  assert.equal(requests.length,3);assert.equal(requests[2].day,'2026-09-22');
});
