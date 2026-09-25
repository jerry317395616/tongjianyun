// No browser dependency: exercise event ordering, dedupe and reload state.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};

class Element {
  constructor() { this.children=[]; this.dataset={}; this.style={}; this.textContent=''; this.classList={toggle(){}}; this.listeners={}; }
  append(node) { this.children.push(node); }
  insertBefore(node,anchor) { this.children=this.children.filter(item=>item!==node); this.children.splice(this.children.indexOf(anchor),0,node); }
  setAttribute() {}
  addEventListener(type,handler) { this.listeners[type]=handler; }
  click() { return this.listeners.click?.(); }
  focus() {}
}

function setup() {
  const nodes = new Map();
  const document = {
    getElementById(id) { assert(!['day','meal','refresh'].includes(id),'removed header control requested: '+id);if(!nodes.has(id))nodes.set(id,new Element()); return nodes.get(id); },
    createElement() { return new Element(); },
    querySelector() { return new Element(); },
  };
  const opened=[];
  const refreshed=[];
  const context = vm.createContext({document,clearTimeout,setTimeout,URLSearchParams,opened,context:()=>({day:'2026-09-24',meal:'lunch'}),refreshMealData:()=>refreshed.push(true),showBusinessView:value=>{opened.push(value);return {status:'rendered',selection:value};}});
  const source = fs.readFileSync(path.join(__dirname,'../public/meal_scene/chat.js'),'utf8');
  vm.runInContext(source.replace(/^import .*;\r?\n/gm,'').split("fileInput.addEventListener('change'")[0],context);
  vm.runInContext("const view=taskView({task_id:'test',message:'测试',status:'running'});",context);
  return {context,nodes,refreshed,run:code=>vm.runInContext(code,context)};
}

test('messages and tool stages stay in chronological order',()=>{
  const {run}=setup();
  run("applyEvent(view,{kind:'message',item_id:'m1',text:'开始检查'},'1-0')");
  run("applyEvent(view,{kind:'progress',item_id:'p1',status:'running',text:'执行操作'},'2-0')");
  run("applyEvent(view,{kind:'progress',item_id:'p1',status:'completed',text:'执行操作'},'3-0')");
  run("applyEvent(view,{kind:'message',item_id:'m2',text:'完成'},'4-0')");
  assert.deepEqual(Array.from(run('view.root.children.map(node=>node.textContent)')),
    ['测试','开始检查','✓ 执行操作','完成','正在继续处理…']);
});

test('replayed event does not add a duplicate message',()=>{
  const {run}=setup();
  run("applyEvent(view,{kind:'message',item_id:'m1',text:'阶段一'},'1-0')");
  run("applyEvent(view,{kind:'message',item_id:'m1',text:'阶段一'},'1-0')");
  assert.equal(run('view.seen.size'),1);
  assert.equal(run('view.root.children.length'),3);
});
test('active task completion refreshes business data once without header controls',()=>{
  const {run,refreshed,nodes}=setup();
  run("showContext();activeTask='test';applyEvent(view,{kind:'terminal',status:'completed',text:'完成'},'1-0')");
  run("applyEvent(view,{kind:'terminal',status:'completed',text:'完成'},'1-0')");
  assert.equal(refreshed.length,1);assert.equal(run('activeTask'),null);
  assert.equal(nodes.get('chat-context').textContent,'2026-09-24 · 午餐');
});

test('terminal event wins over stale running metadata during reload',async()=>{
  const {run}=setup();
  run("request=async()=>({tasks:[{task_id:'test',status:'running',events:[{id:'1-0',kind:'terminal',status:'completed',text:'完成'}]}]})");
  await run('loadConversation()');
  assert.equal(run('activeTask'),null);
  assert.equal(run('view.state'),'completed');
});

test('cancellation ends unfinished stage without falsely marking success',()=>{
  const {run}=setup();
  run("applyEvent(view,{kind:'progress',item_id:'p1',status:'running',text:'执行操作'},'1-0')");
  run("applyEvent(view,{kind:'terminal',status:'cancelled',text:'已停止'},'2-0')");
  assert.equal(run("view.items.get('progress:p1').dataset.state"),'stopped');
  assert.equal(run('view.state'),'cancelled');
});

test('live view SSE selects the canvas once and adds a reopen button',()=>{
  const {run}=setup();
  const event="{kind:'view',version:1,title:'学生',selection:{view:'students'}}";
  run(`applyEvent(view,${event},'1-0')`);run(`applyEvent(view,${event},'1-0')`);
  assert.equal(run('opened.length'),1);assert.equal(run('view.root.children.length'),3);
});

test('historical view replay does not steal the selected canvas',()=>{
  const {run}=setup();
  run("applyEvent(view,{kind:'view',version:1,title:'学生',selection:{view:'students'}},'1-0',true)");
  assert.equal(run('opened.length'),0);assert.equal(run('view.root.children.length'),3);
});
test('initial conversation history keeps default canvas but its result button can reopen the view',async()=>{
  const {run}=setup();
  run("request=async()=>({tasks:[{task_id:'test',status:'completed',events:[{id:'1-0',kind:'view',version:1,title:'学生',selection:{view:'students'}}]}]})");
  await run('loadConversation()');
  assert.equal(run('opened.length'),0);
  run("view.root.children.find(node=>node.className==='chat-view-result').click()");
  assert.equal(run('opened.length'),1);assert.equal(run('opened[0].view'),'students');
});
test('new view received during conversation recovery still switches the canvas',async()=>{
  const {run}=setup();
  run("request=async()=>({tasks:[{task_id:'test',status:'completed',events:[{id:'1-0',kind:'view',version:1,title:'学生',selection:{view:'students'}}]}]})");
  await run('loadConversation()');
  run("request=async()=>({tasks:[{task_id:'test',status:'completed',events:[{id:'1-0',kind:'view',version:1,title:'学生',selection:{view:'students'}},{id:'2-0',kind:'view',version:1,title:'人数',selection:{view:'meal_counts'}}]}]})");
  await run('loadConversation()');
  assert.equal(run('opened.length'),1);assert.equal(run('opened[0].view'),'meal_counts');
});

test('chat waits for the frontend rendering result before showing success',async()=>{
  const {run,context}=setup();let resolve;context.showBusinessView=()=>new Promise(r=>resolve=r);
  run('applyEvent(view,{kind:"view",version:1,title:"学生",selection:{view:"students"}},"1-0")');
  const button=run('view.root.children.find(node=>node.className==="chat-view-result")');
  assert.equal(button.textContent,'正在显示：学生');assert.equal(button.disabled,true);
  resolve({status:'rendered',selection:{view:'students'}});await flush();
  assert.equal(button.textContent,'已显示：学生');assert.equal(button.disabled,false);assert.match(button.title,/不代表已执行/);
});

test('failed and blocked views provide retry without claiming they appeared',async()=>{
  for(const status of ['failed','blocked','superseded']){
    const {run,context}=setup();context.showBusinessView=async()=>({status,message:'未保存原单已保留'});
    run('applyEvent(view,{kind:"view",version:1,title:"发票",selection:{view:"frappe_doctype",doctype:"Sales Invoice"}},"1-0")');
    await flush();
    const button=run('view.root.children.find(node=>node.className==="chat-view-result")');
    assert.equal(button.dataset.state,status);assert.doesNotMatch(button.textContent,/^已显示|^已打开/);assert.equal(button.title,'未保存原单已保留');assert.equal(button.disabled,false);
    context.showBusinessView=async()=>({status:'rendered',selection:{view:'frappe_doctype'},message:'已打开业务容器，等待原生页面加载'});
    await button.click();assert.equal(button.textContent,'已打开业务窗口：发票');assert.match(button.title,/等待原生页面加载/);
  }
});

test('unexpected view errors are shown as failure and allow a later retry',async()=>{
  const {run,context}=setup();context.showBusinessView=async()=>{throw Error('显示失败')};
  run('applyEvent(view,{kind:"view",version:1,title:"学生",selection:{view:"students"}},"1-0")');
  await flush();
  const button=run('view.root.children.find(node=>node.className==="chat-view-result")');
  assert.equal(button.dataset.state,'failed');assert.equal(button.disabled,false);assert.equal(button.title,'显示失败');
});
