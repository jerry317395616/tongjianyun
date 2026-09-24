// No browser dependency: exercise event ordering, dedupe and reload state.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
  constructor() { this.children=[]; this.dataset={}; this.style={}; this.textContent=''; this.classList={toggle(){}}; }
  append(node) { this.children.push(node); }
  insertBefore(node,anchor) { this.children=this.children.filter(item=>item!==node); this.children.splice(this.children.indexOf(anchor),0,node); }
  setAttribute() {}
  addEventListener() {}
  click() {}
  focus() {}
}

function setup() {
  const nodes = new Map();
  const document = {
    getElementById(id) { if(!nodes.has(id))nodes.set(id,new Element()); return nodes.get(id); },
    createElement() { return new Element(); },
    querySelector() { return new Element(); },
  };
  const opened=[];
  const context = vm.createContext({document,clearTimeout,setTimeout,URLSearchParams,opened,restoreBusinessView:async()=>{},showBusinessView:value=>opened.push(value)});
  const source = fs.readFileSync(path.join(__dirname,'../public/meal_scene/chat.js'),'utf8');
  vm.runInContext(source.replace(/^import .*;\r?\n/,'').split("fileInput.addEventListener('change'")[0],context);
  vm.runInContext("const view=taskView({task_id:'test',message:'测试',status:'running'});",context);
  return {context,nodes,run:code=>vm.runInContext(code,context)};
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
