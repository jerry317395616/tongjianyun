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
  const document={getElementById(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id);},createElement:()=>new Element(),createDocumentFragment:()=>new Element()};
  const context=vm.createContext({document,URLSearchParams,sessionStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)}});
  const source=fs.readFileSync(path.join(__dirname,'../public/meal_scene/views.js'),'utf8').replace(/export /g,'');
  vm.runInContext(source,context);
  return {nodes,context,run:code=>vm.runInContext(code,context)};
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
test('returning to calendar beats pending requests and survives restore',async()=>{
  const {run,context,nodes}=setup();let resolve;context.fetcher=()=>new Promise(r=>resolve=r);
  run("initializeViews({request:fetcher,user:'user'})");const pending=run("showBusinessView({view:'students'})");run('showCalendar()');resolve(data);await pending;
  await run("restoreBusinessView({view:'students'})");assert.equal(nodes.get('recipe-workspace').hidden,false);assert.equal(nodes.get('business-view').hidden,true);
});
