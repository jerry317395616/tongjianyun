// No browser dependency: exercise event ordering, dedupe and reload state.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const flush=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};

class Element {
  constructor() { this.children=[]; this.dataset={}; this.style={}; this.textContent=''; this.value='';this.files=[];this.attributes={};this.classList={toggle(){}}; this.listeners={}; }
  append(node) { this.children.push(node);node.parentNode=this; }
  insertBefore(node,anchor) { this.children=this.children.filter(item=>item!==node); this.children.splice(this.children.indexOf(anchor),0,node);node.parentNode=this; }
  replaceChildren(...nodes) { this.children=nodes;nodes.forEach(node=>node.parentNode=this); }
  remove() { if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(node=>node!==this); }
  setAttribute(key,value) { this.attributes[key]=value; }
  addEventListener(type,handler) { this.listeners[type]=handler; }
  click() { return this.listeners.click?.(); }
  focus() {}
}

const businessTask='d4ebd4c5-9f06-41dc-a58d-0a5f8f7f6001';
function setup(options={}) {
  const nodes = new Map();
  const attach=new Element(),streams=[],timers=[],initialized=[];
  class EventSource {
    constructor(url){this.url=url;this.listeners={};this.closed=false;streams.push(this);}
    addEventListener(kind,handler){this.listeners[kind]=handler;}
    close(){this.closed=true;}
  }
  const document = {
    getElementById(id) { assert(!['day','meal','refresh'].includes(id),'removed header control requested: '+id);if(!nodes.has(id))nodes.set(id,new Element()); return nodes.get(id); },
    createElement() { return new Element(); },
    querySelector(selector) { return selector==='.chat-attach'?attach:{content:'csrf-placeholder'}; },
  };
  const opened=[];
  const refreshed=[];
  const context = vm.createContext({document,clearTimeout:timer=>{if(timer)timer.cleared=true;},setTimeout:fn=>{const timer={fn};timers.push(timer);return timer;},URLSearchParams,opened,EventSource,
    crypto:{randomUUID:()=>businessTask},fetch:()=>{throw Error('Unexpected network request in a unit test');},
    currentViewContext:()=>({view:'classroom_day',group:'Synthetic Class'}),initializeViews:value=>{initialized.push(value);},
    context:()=>({day:'2026-09-24',meal:'lunch'}),refreshMealData:()=>refreshed.push(true),showBusinessView:value=>{opened.push(value);return {status:'rendered',selection:value};}});
  const source = fs.readFileSync(path.join(__dirname,'../public/meal_scene/chat.js'),'utf8');
  vm.runInContext(source.replace(/^import .*;\r?\n/gm,'').split("fileInput.addEventListener('change'")[0],context);
  if(options.mode)vm.runInContext(`configureChat({user:'teacher@example.invalid',chat:{mode:${JSON.stringify(options.mode)},allowed:true}})`,context);
  vm.runInContext(`const view=taskView({task_id:${JSON.stringify(options.mode==='business'?businessTask:'test')},message:'测试',status:'running'});`,context);
  return {context,nodes,refreshed,streams,timers,attach,initialized,run:code=>vm.runInContext(code,context)};
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

test('business failure stage survives terminal status and history replay',()=>{
  const {run}=setup({mode:'business'});
  const stage={kind:'progress',item_id:'codex-runtime-failure',status:'failed',text:'模型输出连接未完整结束'};
  const ended={kind:'terminal',status:'failed',text:'本次任务未完成，请先核对业务记录。'};
  run(`applyEvent(view,${JSON.stringify(stage)},'${businessTask}:1',true)`);
  run(`applyEvent(view,${JSON.stringify(ended)},'${businessTask}:2',true)`);
  run(`applyEvent(view,${JSON.stringify(stage)},'${businessTask}:1',true)`);
  assert.equal(run("view.items.get('progress:codex-runtime-failure').dataset.state"),'failed');
  assert.match(run("view.items.get('progress:codex-runtime-failure').textContent"),/模型输出连接未完整结束/);
  assert.equal(run("view.root.children.filter(node=>node.textContent.includes('模型输出连接未完整结束')).length"),1);
  assert.equal(run('view.state'),'failed');
  assert.equal(run('activeTask'),null);
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

test('bootstrap business mode selects only business history and cursor namespace',async()=>{
  const {run,context,streams,nodes,attach}=setup({mode:'business'}),calls=[];
  context.fetch=async url=>{calls.push(url);return {ok:true,json:async()=>({message:{mode:'business',tasks:[{task_id:businessTask,message:'测试',status:'running',events:[],next_after:null}]}})};};
  await run('loadConversation()');
  assert.deepEqual(calls,['/api/method/tongjianyun.business_chat.get_conversation']);
  assert.match(streams[0].url,/business_chat\.stream_events/);assert.equal(new URLSearchParams(streams[0].url.split('?')[1]).get('after'),'0');
  assert.equal(nodes.get('chat-file').disabled,true);assert.match(attach.title,/暂不支持上传/);
});

test('missing mode retains administrator API and unknown mode never falls back',()=>{
  const {run}=setup();run("configureChat({user:'Administrator',chat:{allowed:true}})");
  assert.equal(run('api'),'/api/method/tongjianyun.meal_chat.');
  assert.throws(()=>run("configureChat({user:'teacher',chat:{mode:'invented',allowed:true}})"),/配置不完整/);
});

test('disabled business chat still initializes business views without any chat request',async()=>{
  const {run,context,initialized,nodes}=setup(),calls=[];context.fetch=async url=>{calls.push(url);throw Error('must not call');};
  await run("initializeChat({user:'teacher@example.invalid',chat:{mode:'business',allowed:false,reason:'验收前暂未开放'}})");
  assert.equal(initialized.length,1);assert.equal(calls.length,0);assert.equal(nodes.get('chat-form').hidden,true);
  assert.match(nodes.get('chat-messages').children[0].textContent,/验收前/);
});

test('offline launcher preserves history and cancellation but prevents new sends or redispatch',async()=>{
  const {run,context,nodes}=setup({mode:'business'}),calls=[];
  run("configureChat({user:'teacher@example.invalid',chat:{mode:'business',allowed:true,can_submit:false,reason:'后台暂不可用'}})");
  context.fetch=async(url,options)=>{
    calls.push({url,options});
    const message=url.endsWith('cancel_task')?{task_id:businessTask,status:'cancelled'}:
      {mode:'business',tasks:[{task_id:businessTask,status:calls.some(c=>c.url.endsWith('cancel_task'))?'cancelled':'queued',events:[],next_after:null}]};
    return {ok:true,json:async()=>({message})};
  };
  await run('loadConversation()');
  assert.equal(run('activeTask'),businessTask);assert.equal(nodes.get('chat-send').disabled,false);
  assert.equal(nodes.get('chat-input').disabled,true);
  assert.equal(calls.filter(c=>c.url.endsWith('retry_dispatch')).length,0);
  await run('submitMessage({preventDefault(){}})');
  assert.equal(calls.filter(c=>c.url.endsWith('cancel_task')).length,1);
  assert.equal(run('activeTask'),null);assert.equal(nodes.get('chat-send').disabled,true);
  run("input.value='新任务'");await run('submitMessage({preventDefault(){}})');
  assert.equal(calls.filter(c=>c.url.endsWith('send_message')).length,0);
});

test('all event pages are consumed before SSE starts without jumping last_event_id',async()=>{
  const {run,context,streams}=setup({mode:'business'}),calls=[];
  context.fetch=async url=>{
    calls.push(url);assert.equal(streams.length,0,'SSE opened before history finished');
    const message=calls.length===1?{mode:'business',tasks:[{task_id:businessTask,status:'running',last_event_id:businessTask+':99',
      events:[{id:businessTask+':1',kind:'message',item_id:'a',text:'第一步'}],next_after:businessTask+':1'}]}:
      calls.length===2?{events:[{id:businessTask+':2',kind:'message',item_id:'a',text:'第一步\n第二步'}],next_after:businessTask+':2'}:
        {events:[{id:businessTask+':3',kind:'progress',item_id:'p',text:'核对',status:'running'}],next_after:null};
    return {ok:true,json:async()=>({message})};
  };
  await run('loadConversation()');assert.equal(calls.length,3);assert.equal(streams.length,1);
  assert.equal(new URLSearchParams(streams[0].url.split('?')[1]).get('after'),businessTask+':3');
  assert.equal(run("view.items.get('message:a').textContent"),'第一步\n第二步');
  assert.equal(run('view.items.size'),2);
});

test('business cursors reject foreign task, gaps and never move backwards',()=>{
  const {run}=setup({mode:'business'});
  const message="{kind:'message',item_id:'a',text:'结果'}";
  assert.throws(()=>run(`applyEvent(view,${message},'other:1')`),/不匹配/);
  assert.throws(()=>run(`applyEvent(view,${message},'${businessTask}:2')`),/不连续/);
  run(`applyEvent(view,${message},'${businessTask}:1')`);
  run(`applyEvent(view,{kind:'message',item_id:'a',text:'新结果'},'${businessTask}:2')`);
  run(`applyEvent(view,${message},'${businessTask}:1')`);
  assert.equal(run('view.cursor'),businessTask+':2');assert.equal(run("view.items.get('message:a').textContent"),'新结果');
});

test('stopping task remains active and cannot accept a new message',async()=>{
  const {run,context,nodes,streams}=setup({mode:'business'});
  context.fetch=async()=>({ok:true,json:async()=>({message:{mode:'business',tasks:[{task_id:businessTask,status:'stopping',events:[],next_after:null}]}})});
  await run('loadConversation()');assert.equal(run('activeTask'),businessTask);assert.equal(nodes.get('chat-input').disabled,true);
  assert.equal(nodes.get('chat-send').disabled,true);assert.equal(streams.length,1);
});

test('cancel uses business endpoint and waits for real terminal history',async()=>{
  const {run,context,nodes}=setup({mode:'business'}),calls=[];
  run('activeTask=view.id');
  context.fetch=async(url,options)=>{
    calls.push({url,options});const message=url.endsWith('cancel_task')?{task_id:businessTask,status:'stopping'}:
      {mode:'business',tasks:[{task_id:businessTask,status:'stopping',events:[{id:businessTask+':1',kind:'status',text:'正在停止'}],next_after:null}]};
    return {ok:true,json:async()=>({message})};
  };
  await run('submitMessage({preventDefault(){}})');
  assert.equal(calls[0].url,'/api/method/tongjianyun.business_chat.cancel_task');assert.deepEqual(JSON.parse(calls[0].options.body),{task_id:businessTask});
  assert.equal(run('view.state'),'stopping');assert.equal(run('activeTask'),businessTask);assert.equal(nodes.get('chat-send').disabled,true);
});

test('SSE unavailable stops reading without pretending backend task failed',()=>{
  const {run,streams,nodes}=setup({mode:'business'});run('connect(view)');
  streams[0].listeners.unavailable();assert.equal(streams[0].closed,true);assert.equal(run('view.state'),'running');
  assert.equal(run('activeTask'),businessTask);assert.equal(run('allowed'),false);assert.equal(nodes.get('chat-send').disabled,true);
  assert.match(run('view.status.textContent'),/状态尚未确认/);
});

test('SSE disconnect schedules recovery but never terminal or second submission',()=>{
  const {run,streams,timers}=setup({mode:'business'});run('connect(view)');streams[0].onerror();
  assert.equal(run('view.state'),'running');assert.equal(run('activeTask'),businessTask);assert.equal(timers.length,1);
  assert.match(run('view.status.textContent'),/后台任务继续运行/);
});

test('old source callbacks cannot affect a switched user or administrator history',()=>{
  const {run,streams,nodes}=setup({mode:'business'});run('connect(view)');const old=streams[0];
  run("configureChat({user:'Administrator',chat:{mode:'admin_project',allowed:true}})");
  old.listeners.update({lastEventId:businessTask+':1',data:JSON.stringify({kind:'message',item_id:'private',text:'旧用户私有数据'})});
  old.listeners.unavailable();assert.equal(old.closed,true);assert.equal(run('tasks.size'),0);assert.equal(run('allowed'),true);
  assert.equal(nodes.get('chat-messages').children.length,0);
});

test('business selected file is preserved and rejected, never uploaded or sent to admin',async()=>{
  const {run,nodes,context}=setup({mode:'business'}),calls=[];
  nodes.get('chat-input').value='处理附件';nodes.get('chat-file').files=[{name:'private.xlsx',size:100}];
  context.fetch=async url=>{calls.push(url);throw Error('must not call');};
  await run('submitMessage({preventDefault(){}})');assert.equal(calls.length,0);
  assert.equal(nodes.get('chat-file').files[0].name,'private.xlsx');assert.equal(nodes.get('chat-input').value,'处理附件');
  assert.match(nodes.get('chat-messages').children.at(-1).textContent,/尚未发送/);
});

test('business send contains no attachment field and lost response reuses request identity on explicit retry',async()=>{
  const {run,nodes,context}=setup({mode:'business'}),posts=[];let attempts=0;
  nodes.get('chat-input').value='查看本班学生';
  context.fetch=async(url,options)=>{
    assert.doesNotMatch(url,/meal_chat\.|upload_file/);
    if(url.endsWith('send_message')){
      posts.push(JSON.parse(options.body));attempts++;
      if(attempts===1)throw Error('response lost');
      return {ok:true,json:async()=>({message:{accepted:true,task_id:businessTask,status:'queued'}})};
    }
    return {ok:true,json:async()=>({message:{mode:'business',tasks:attempts===1?[]:[{task_id:businessTask,message:'查看本班学生',status:'queued',events:[],next_after:null}]}})};
  };
  await run('submitMessage({preventDefault(){}})');assert.equal(posts.length,1);assert.equal(nodes.get('chat-input').value,'查看本班学生');
  await run('submitMessage({preventDefault(){}})');assert.equal(posts.length,2);assert.deepEqual(posts[0],posts[1]);
  assert.equal(posts[0].request_id,businessTask);assert.equal('file_name' in posts[0],false);assert.equal(nodes.get('chat-input').value,'');
});

test('accepted false resumes existing task and does not clear unsent request',async()=>{
  const {run,nodes,context}=setup({mode:'business'});nodes.get('chat-input').value='另一项请求';
  context.fetch=async url=>({ok:true,json:async()=>({message:url.endsWith('send_message')?{accepted:false,task_id:businessTask,status:'running'}:
    {mode:'business',tasks:[{task_id:businessTask,message:'已有任务',status:'running',events:[],next_after:null}]}})});
  await run('submitMessage({preventDefault(){}})');assert.equal(nodes.get('chat-input').value,'另一项请求');
  assert.equal(run('activeTask'),businessTask);assert.equal(run('view.userMessage.textContent'),'已有任务');
});

test('late history response after account switch is ignored',async()=>{
  const {run,context,nodes}=setup({mode:'business'});let resolve;
  context.fetch=()=>new Promise(r=>resolve=r);const loading=run('loadConversation()');
  run("configureChat({user:'different@example.invalid',chat:{mode:'business',allowed:true}})");
  resolve({ok:true,json:async()=>({message:{mode:'business',tasks:[{task_id:businessTask,message:'PRIVATE_OLD_ACCOUNT',status:'completed',events:[],next_after:null}]}})});
  await loading;assert.equal(run('tasks.size'),0);assert.equal(nodes.get('chat-messages').children.length,0);
});

test('queued recovery retries only dispatch of the existing task, including unconfirmed delivery',async()=>{
  const {run,context,timers,streams}=setup({mode:'business'}),calls=[];
  context.fetch=async(url,options)=>{
    calls.push({url,options});assert.doesNotMatch(url,/send_message|meal_chat\./);
    const message=url.endsWith('retry_dispatch')?{task_id:businessTask,status:'queued',delivery:'unconfirmed'}:
      {mode:'business',tasks:[{task_id:businessTask,status:'queued',events:[],next_after:null}]};
    return {ok:true,json:async()=>({message})};
  };
  await run('loadConversation()');
  const retries=calls.filter(call=>call.url.endsWith('retry_dispatch'));
  assert.equal(retries.length,1);assert.deepEqual(JSON.parse(retries[0].options.body),{task_id:businessTask});
  assert.equal(run('view.state'),'queued');assert.equal(run('activeTask'),businessTask);
  assert.match(run('view.status.textContent'),/任务已保存/);
  streams[0].onopen();assert.notEqual(timers[0].cleared,true,'stream open must not cancel unconfirmed-dispatch recovery');
  await timers[0].fn();await flush();
  assert.equal(calls.filter(call=>call.url.endsWith('retry_dispatch')).length,2);
});

test('completed and cancelled tasks are never dispatched during history recovery',async()=>{
  for(const status of ['completed','cancelled','failed','stopping']){
    const {run,context}=setup({mode:'business'}),calls=[];
    context.fetch=async url=>{calls.push(url);return {ok:true,json:async()=>({message:{mode:'business',tasks:[{task_id:businessTask,status,events:[],next_after:null}]}})};};
    await run('loadConversation()');assert.equal(calls.length,1,status+' must not retry dispatch');
  }
});

test('previous terminal event cannot be downgraded by stale running metadata on another reload',async()=>{
  const {run,context,streams}=setup({mode:'business'});
  context.fetch=async()=>({ok:true,json:async()=>({message:{mode:'business',tasks:[{task_id:businessTask,status:'running',
    events:[{id:businessTask+':1',kind:'terminal',status:'completed',text:'完成'}],next_after:null}]}})});
  await run('loadConversation()');await run('loadConversation()');
  assert.equal(run('view.state'),'completed');assert.equal(run('activeTask'),null);assert.equal(streams.length,0);
});
