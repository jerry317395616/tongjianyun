import {initializeViews,showBusinessView,currentViewContext} from './views.js?v=meal-ingredients-20260925-1';
import {mealContext as context,refreshMealData} from './state.js?v=meal-header-20260925-1';
const $=id=>document.getElementById(id);
const form=$('chat-form'),input=$('chat-input'),fileInput=$('chat-file'),send=$('chat-send');
const messages=$('chat-messages'),chip=$('chat-file-chip'),fileName=$('chat-file-name');
const mealNames={breakfast:'早餐',morning_snack:'早点',lunch:'午餐',afternoon_snack:'午点',dinner:'晚餐'};
const api='/api/method/tongjianyun.meal_chat.';
const tasks=new Map();
let allowed=false,submitting=false,activeTask=null,source=null,recoveryTimer=null,historyLoaded=false;

function addMessage(kind,text,parent=messages){
  const node=document.createElement('div');
  node.className=`chat-message ${kind}`;node.textContent=text;parent.append(node);return node;
}
function scrollMessages(){messages.scrollTop=messages.scrollHeight;}
function showContext(){
  const {day,meal}=context();
  $('chat-context').textContent=day?`${day} · ${mealNames[meal]||'午餐'}`:'正在读取业务日期…';
}
function controls(){
  send.disabled=!allowed||submitting;
  input.disabled=!allowed||submitting||!!activeTask;
  fileInput.disabled=input.disabled;
  $('chat-remove-file').disabled=input.disabled;
  document.querySelector('.chat-attach').classList.toggle('disabled',input.disabled);
  send.textContent=activeTask?'■':'↑';
  send.setAttribute('aria-label',activeTask?'停止处理':'发送消息');
  send.title=activeTask?'停止处理':'发送消息';
}
function errorText(body,status){
  try{
    const row=JSON.parse(body._server_messages||'[]')[0];
    const item=typeof row==='string'?JSON.parse(row):row;
    if(item?.message)return new DOMParser().parseFromString(item.message,'text/html').body.textContent;
  }catch(_){}
  return status===403?'当前账号没有此操作权限，请重新登录后核对。':'操作未完成，请稍后再试。';
}
async function request(path,options={}){
  const response=await fetch(path,{credentials:'same-origin',cache:'no-store',...options,
    headers:{Accept:'application/json',...(options.method==='POST'?{'X-Frappe-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content}:{}),...options.headers}});
  const body=await response.json().catch(()=>({}));
  if(!response.ok||body.exc){const error=Error(errorText(body,response.status));error.status=response.status;throw error;}
  return body.message;
}
const post=(method,body)=>request(api+method,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
function clearFile(){fileInput.value='';chip.hidden=true;fileName.textContent='';}
async function upload(file){
  const data=new FormData();data.append('file',file);data.append('is_private','1');
  const uploaded=await request('/api/method/upload_file',{method:'POST',body:data});
  if(!uploaded?.name)throw Error('文件未上传成功。');
  return uploaded.name;
}
function taskView(task){
  if(tasks.has(task.task_id))return tasks.get(task.task_id);
  const root=document.createElement('section');root.className='chat-task';messages.append(root);
  addMessage('user',[task.message,task.file_name?`上传：${task.file_name}`:''].filter(Boolean).join('\n'),root);
  const status=document.createElement('div');status.className='chat-task-status';status.setAttribute('role','status');root.append(status);
  const view={id:task.task_id,root,status,items:new Map(),seen:new Set(),cursor:'0-0',state:task.status};
  tasks.set(task.task_id,view);return view;
}
function finish(view,event){
  view.state=event.status;view.status.textContent=event.text||'本次处理结束。';
  view.status.classList.toggle('error',event.status==='failed');
  for(const row of view.items.values()){if(row.dataset.state==='running'){row.dataset.state='stopped';row.textContent='· '+row.dataset.label+'（已结束）';}}
  if(activeTask===view.id){activeTask=null;source?.close();source=null;clearTimeout(recoveryTimer);controls();refreshMealData();input.focus();}
}
function applyEvent(view,event,id,replay=false){
  if(id){if(view.seen.has(id))return;view.seen.add(id);view.cursor=id;}
  if(event.kind==='status'){view.status.textContent=event.text;}
  if(event.kind==='progress'){
    const key='progress:'+event.item_id;
    let row=view.items.get(key);
    if(!row){row=document.createElement('div');row.className='chat-progress';view.root.insertBefore(row,view.status);view.items.set(key,row);}
    row.dataset.state=event.status;row.dataset.label=event.text;
    row.textContent=({running:'◌ ',completed:'✓ ',failed:'! '}[event.status]||'· ')+event.text+(event.status==='failed'?'（此步骤未成功）':'');
  }
  if(event.kind==='message'){
    const key='message:'+event.item_id;
    let node=view.items.get(key);
    if(!node){node=addMessage('assistant','',view.root);view.root.insertBefore(node,view.status);view.items.set(key,node);}
    node.textContent=event.text;view.status.textContent='正在继续处理…';
  }
  if(event.kind==='view'&&event.version===1){
    const button=document.createElement('button');button.type='button';button.className='chat-view-result';
    button.textContent='查看：'+event.title+' ↗';button.addEventListener('click',()=>showBusinessView(event.selection));
    view.root.insertBefore(button,view.status);if(!replay)showBusinessView(event.selection);
  }
  if(event.kind==='terminal')finish(view,event);
  scrollMessages();
}
function connect(view){
  source?.close();clearTimeout(recoveryTimer);activeTask=view.id;controls();
  source=new EventSource(api+'stream_events?'+new URLSearchParams({task_id:view.id,after:view.cursor}));
  const current=source;
  current.addEventListener('update',event=>{
    if(source!==current)return;
    try{applyEvent(view,JSON.parse(event.data),event.lastEventId);}catch(_){view.status.textContent='正在恢复进度…';}
  });
  current.addEventListener('closed',()=>{current.close();loadConversation().catch(showFailure);});
  current.addEventListener('unavailable',()=>{current.close();finish(view,{status:'failed',text:'任务记录已不可用，请先核对业务记录。'});});
  current.onopen=()=>{clearTimeout(recoveryTimer);if(view.state==='running')view.status.textContent='正在处理…';};
  current.onerror=()=>{
    if(source!==current||!activeTask)return;
    view.status.textContent='连接恢复中，后台任务继续运行…';
    clearTimeout(recoveryTimer);
    recoveryTimer=setTimeout(()=>loadConversation().catch(showFailure),5000);
  };
}
function showFailure(error){
  if(error.status===401||error.status===403){allowed=false;source?.close();source=null;controls();}
  const view=tasks.get(activeTask);
  if(view)view.status.textContent=error.message||'连接恢复中，后台任务继续运行…';
  else addMessage('assistant error',error.message||'网络连接中断，请稍后刷新核对。');
}
async function loadConversation(){
  const result=await request(api+'get_conversation');
  const initial=!historyLoaded;let running=null;
  for(const task of result.tasks||[]){
    const view=taskView(task);view.state=task.status;
    for(const event of task.events||[])applyEvent(view,event,event.id,initial);
    if(['queued','running'].includes(view.state))running=view;
  }
  if(running)connect(running);
  else{activeTask=null;source?.close();source=null;clearTimeout(recoveryTimer);controls();}
  historyLoaded=true;
  scrollMessages();
}

fileInput.addEventListener('change',()=>{
  const file=fileInput.files?.[0];if(!file)return clearFile();
  if(file.size>10*1024*1024){clearFile();addMessage('assistant error','文件不能超过 10 MB。');return;}
  fileName.textContent=file.name;chip.hidden=false;
});
$('chat-remove-file').addEventListener('click',clearFile);
input.addEventListener('input',()=>{input.style.height='auto';input.style.height=Math.min(input.scrollHeight,132)+'px';});
input.addEventListener('keydown',event=>{
  if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();form.requestSubmit();}
});
document.addEventListener('meal-scene:context',showContext);
form.addEventListener('submit',async event=>{
  event.preventDefault();if(!allowed||submitting)return;
  if(activeTask){
    submitting=true;controls();
    try{await post('cancel_task',{task_id:activeTask});}catch(error){showFailure(error);}
    finally{submitting=false;controls();}
    return;
  }
  const text=input.value.trim(),file=fileInput.files?.[0];if(!text&&!file)return input.focus();
  const {day,meal}=context();if(!day)return addMessage('assistant error','业务日期还没读取完成，请稍等。');
  submitting=true;controls();
  const sending=addMessage('assistant',file?'正在上传业务文件…':'正在发送…');scrollMessages();
  try{
    const file_name=file?await upload(file):undefined;
    const result=await post('send_message',{message:text,day,meal,file_name,stream:1,request_id:crypto.randomUUID(),view_context:currentViewContext()});
    if(result.accepted){input.value='';input.style.height='auto';clearFile();}
    await loadConversation();
  }catch(error){
    // Recover an accepted task after a lost HTTP response; never submit it twice.
    try{await loadConversation();}catch(_){}
    if(!activeTask)showFailure(error);
  }finally{sending.remove();submitting=false;controls();}
});

showContext();controls();
request(api+'get_chat_access').then(async result=>{
  allowed=!!result?.allowed;controls();
  if(allowed){initializeViews({request});await loadConversation();}
  else addMessage('assistant error','当前账号暂不能使用对话，请联系管理员。');
}).catch(showFailure);
