import {initializeViews,showBusinessView,currentViewContext} from './views.js?v=business-handoffs-20260926-1';
import {mealContext as context,refreshMealData} from './state.js?v=meal-header-20260925-1';
import {getSceneBootstrap} from './scene_bootstrap.js?v=teacher-scene-20260925-1';
const $=id=>document.getElementById(id);
const form=$('chat-form'),input=$('chat-input'),fileInput=$('chat-file'),send=$('chat-send');
const messages=$('chat-messages'),chip=$('chat-file-chip'),fileName=$('chat-file-name');
const mealNames={breakfast:'早餐',morning_snack:'早点',lunch:'午餐',afternoon_snack:'午点',dinner:'晚餐'};
const adminApi='/api/method/tongjianyun.meal_chat.',businessApi='/api/method/tongjianyun.business_chat.';
const activeStates=new Set(['queued','running','stopping']),terminalStates=new Set(['completed','failed','cancelled']);
const stateLabels={queued:'已收到，正在准备处理…',running:'正在处理…',stopping:'正在停止，请等待执行结果核对。',completed:'本次处理结束。',failed:'本次任务未完成，请先核对业务记录。',cancelled:'任务已停止，已提交的业务不会自动撤销。'};
const tasks=new Map();
let allowed=false,submitting=false,activeTask=null,source=null,recoveryTimer=null,historyLoaded=false;
let api=adminApi,chatMode='admin_project',chatUser='',generation=0,loading=null,pendingSend=null;
let canSubmit=true,readinessReason='';

function configureChat(bootstrap){
  const mode=bootstrap.chat?.mode;
  if(mode&&mode!=='business'&&mode!=='admin_project'&&!(mode==='unavailable'&&!bootstrap.chat.allowed))throw Error('业务对话配置不完整，请刷新后重试。');
  const nextMode=mode==='business'?'business':'admin_project',user=bootstrap.user||'';
  if(nextMode!==chatMode||user!==chatUser){
    generation++;source?.close();source=null;clearTimeout(recoveryTimer);recoveryTimer=null;
    tasks.clear();messages.replaceChildren();activeTask=null;historyLoaded=false;loading=null;pendingSend=null;submitting=false;
    if(chatUser&&user!==chatUser){clearFile();input.value='';}
  }
  chatMode=nextMode;chatUser=user;api=chatMode==='business'?businessApi:adminApi;
  fileInput.accept=chatMode==='business'?'.txt,.csv,.xlsx':'.xlsx,.xls,.csv,.pdf,.png,.jpg,.jpeg,.webp,.txt';
  allowed=bootstrap.chat.allowed===true;canSubmit=bootstrap.chat.can_submit!==false;
  readinessReason=bootstrap.chat.reason||'后台助手暂不可用，仍可查看已有记录或停止任务。';controls();
  if(chatMode==='business'){
    $('chat-title').textContent='业务助手';input.placeholder=canSubmit?'说出需要办理的业务…':'后台暂不可用，已有任务仍可停止';
  }
}

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
  const stopping=tasks.get(activeTask)?.state==='stopping';
  send.disabled=!allowed||submitting||stopping||(!activeTask&&!canSubmit);
  input.disabled=!allowed||submitting||!!activeTask||!canSubmit;
  fileInput.disabled=input.disabled;
  $('chat-remove-file').disabled=input.disabled;
  const attach=document.querySelector('.chat-attach');
  attach.classList.toggle('disabled',fileInput.disabled);attach.setAttribute('aria-disabled',String(fileInput.disabled));
  attach.title=chatMode==='business'?'上传 TXT、CSV 或 XLSX 文件（最多 2 MB）':'上传业务文件';
  send.textContent=activeTask?'■':'↑';
  send.setAttribute('aria-label',stopping?'正在停止':activeTask?'停止处理':'发送消息');
  send.title=stopping?'正在停止':activeTask?'停止处理':'发送消息';
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
  if(!response.ok||body.exc){const error=Error(errorText(body,response.status));error.status=response.status;error.notAccepted=body.business_request_not_accepted===true;throw error;}
  return body.message;
}
function clearFile(){fileInput.value='';chip.hidden=true;fileName.textContent='';}
function fileError(file,mode=chatMode){
  if(!file)return '';
  if(mode==='business'&&!/\.(txt|csv|xlsx)$/i.test(file.name))return '当前支持 TXT、CSV、XLSX 文件，其他格式尚未接通。';
  const limit=mode==='business'?2:10;
  return file.size>limit*1024*1024?`文件不能超过 ${limit} MB。`:'';
}
async function upload(file){
  const data=new FormData();data.append('file',file);data.append('is_private','1');
  const uploaded=await request('/api/method/upload_file',{method:'POST',body:data});
  if(!uploaded?.name)throw Error('文件未上传成功。');
  return uploaded.name;
}
function taskView(task){
  if(tasks.has(task.task_id)){
    const existing=tasks.get(task.task_id);
    if(typeof task.message==='string')existing.userMessage.textContent=[task.message,task.file_name?`上传：${task.file_name}`:''].filter(Boolean).join('\n');
    return existing;
  }
  const root=document.createElement('section');root.className='chat-task';messages.append(root);
  const userMessage=addMessage('user',[task.message,task.file_name?`上传：${task.file_name}`:''].filter(Boolean).join('\n'),root);
  const status=document.createElement('div');status.className='chat-task-status';status.setAttribute('role','status');root.append(status);
  const view={id:task.task_id,root,userMessage,status,items:new Map(),seen:new Set(),cursor:chatMode==='business'?'0':'0-0',state:task.status,mode:chatMode,api};
  status.textContent=stateLabels[task.status]||'正在核对任务状态…';
  tasks.set(task.task_id,view);return view;
}
function finish(view,event){
  if(!terminalStates.has(event.status))throw Error('任务结束状态尚未确认。');
  view.state=event.status;view.status.textContent=event.text||'本次处理结束。';
  view.status.classList.toggle('error',event.status==='failed');
  for(const row of view.items.values()){if(row.dataset.state==='running'){row.dataset.state='stopped';row.textContent='· '+row.dataset.label+'（已结束）';}}
  if(activeTask===view.id){activeTask=null;source?.close();source=null;clearTimeout(recoveryTimer);controls();refreshMealData();input.focus();}
}
async function openViewResult(button,event,origin='user'){
  if(button.disabled)return;
  button.disabled=true;button.dataset.state='loading';button.textContent='正在显示：'+event.title;
  try{
    const result=await showBusinessView(event.selection,{origin});
    const status=result?.status||'failed';button.dataset.state=status;
    const native=['frappe_doctype','frappe_document','frappe_new','frappe_report','frappe_page','frappe_workspace'].includes(result?.selection?.view);
    button.textContent=({rendered:native?'已打开业务窗口：':'已显示：',blocked:'未切换，可重试：',superseded:'已切换其他内容，查看：',failed:'未显示，点击重试：'}[status]||'查看：')+event.title;
    button.title=result?.message||(status==='rendered'?'已显示业务视图，不代表已执行保存、审批等操作。':'业务视图未能显示。');
  }catch(error){button.dataset.state='failed';button.textContent='未显示，点击重试：'+event.title;button.title=error.message||'业务视图未能显示。';}
  finally{button.disabled=false;scrollMessages();}
}
function applyEvent(view,event,id,replay=false){
  if(event.kind==='terminal'&&!terminalStates.has(event.status))throw Error('任务结束状态尚未确认。');
  if(view.mode==='business'){
    const sequence=businessCursor(view,id),previous=businessCursor(view,view.cursor);
    if(sequence<=previous||view.seen.has(id))return;
    if(sequence!==previous+1n)throw Error('任务进度不连续，正在重新读取。');
  }
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
    button.textContent='查看：'+event.title;button.addEventListener('click',()=>openViewResult(button,event));
    view.root.insertBefore(button,view.status);if(!replay)openViewResult(button,event,'assistant');
  }
  if(event.kind==='terminal')finish(view,event);
  scrollMessages();
}
function businessCursor(view,id){
  if(id==='0')return 0n;
  if(typeof id!=='string'||!id.startsWith(view.id+':'))throw Error('任务进度标识不匹配。');
  const number=id.slice(view.id.length+1);
  if(!/^(0|[1-9][0-9]{0,18})$/.test(number)||BigInt(number)>9223372036854775807n)throw Error('任务进度标识无效。');
  return BigInt(number);
}
function unavailable(view){
  source?.close();source=null;clearTimeout(recoveryTimer);recoveryTimer=null;allowed=false;
  view.status.textContent='当前会话无法继续读取进度，请重新登录或刷新后核对。后台任务状态尚未确认。';
  view.status.classList.toggle('error',true);controls();
}
function connect(view){
  source?.close();clearTimeout(recoveryTimer);activeTask=view.id;controls();
  source=new EventSource(view.api+'stream_events?'+new URLSearchParams({task_id:view.id,after:view.cursor}));
  const current=source,epoch=generation;
  const valid=()=>source===current&&generation===epoch;
  current.addEventListener('update',event=>{
    if(!valid())return;
    try{applyEvent(view,JSON.parse(event.data),event.lastEventId);}catch(_){view.status.textContent='正在恢复进度…';current.close();loadConversation().catch(showFailure);}
  });
  current.addEventListener('closed',()=>{if(!valid())return;current.close();loadConversation().catch(showFailure);});
  current.addEventListener('unavailable',()=>{if(valid())unavailable(view);});
  current.onopen=()=>{
    if(!valid())return;
    if(!view.dispatchUnconfirmed)clearTimeout(recoveryTimer);
    view.status.textContent=view.dispatchUnconfirmed?'任务已保存，正在核对后台派发状态…':stateLabels[view.state]||'正在核对任务状态…';
  };
  current.onerror=()=>{
    if(!valid()||!activeTask)return;
    view.status.textContent='连接恢复中，后台任务继续运行…';
    clearTimeout(recoveryTimer);
    recoveryTimer=setTimeout(()=>{if(valid())loadConversation().catch(showFailure);},5000);
  };
}
function showFailure(error){
  if(error.status===401||error.status===403){allowed=false;source?.close();source=null;controls();}
  const view=tasks.get(activeTask);
  if(view)view.status.textContent=error.message||'连接恢复中，后台任务继续运行…';
  else addMessage('assistant error',error.message||'网络连接中断，请稍后刷新核对。');
}
function loadConversation(){
  if(loading)return loading;
  const epoch=generation,endpoint=api,mode=chatMode;
  const promise=(async()=>{
    const result=await request(endpoint+'get_conversation');
    if(epoch!==generation)return;
    if(mode==='business'&&(result?.mode!=='business'||!Array.isArray(result.tasks)))throw Error('业务会话返回内容不完整，请刷新核对。');
    const initial=!historyLoaded;let running=null,dispatchUnconfirmed=false;
    for(const task of result.tasks||[]){
      const view=taskView(task);
      if(!terminalStates.has(view.state)&&!(view.state==='stopping'&&['queued','running'].includes(task.status)))view.state=task.status;
      let page=task,after='0',pages=0;
      while(true){
        for(const event of page.events||[])applyEvent(view,event,event.id,initial);
        if(mode!=='business'||!page.next_after)break;
        const next=page.next_after;
        if(++pages>100||!Array.isArray(page.events)||!page.events.length||page.events.at(-1).id!==next
          ||businessCursor(view,next)<=businessCursor(view,after))throw Error('业务进度分页无效，请刷新核对。');
        after=next;page=await request(endpoint+'get_events?'+new URLSearchParams({task_id:view.id,after}));
        if(epoch!==generation)return;
      }
      if(mode==='business'&&canSubmit&&view.state==='queued'&&!task.cancel_requested){
        try{
          const dispatched=await request(endpoint+'retry_dispatch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({task_id:view.id})});
          if(epoch!==generation)return;
          if(dispatched?.task_id!==view.id||!activeStates.has(dispatched.status)&&!terminalStates.has(dispatched.status))throw Error('后台派发状态尚未确认。');
          if(activeStates.has(dispatched.status))view.state=dispatched.status;
          // A task may end during recovery. Still drain its remaining SSE/history
          // before releasing the composer; never resubmit the user message.
          dispatchUnconfirmed=dispatched.delivery==='unconfirmed';
        }catch(error){
          if(epoch!==generation)return;
          if(error.status===401||error.status===403)throw error;
          dispatchUnconfirmed=true;
        }
      }
      if(terminalStates.has(view.state)){view.status.textContent=stateLabels[view.state];}
      else if(activeStates.has(view.state)){
        if(mode==='business'&&running&&running.id!==view.id)throw Error('发现多个未结束任务，请核对后再操作。');
        running=view;
      }else throw Error('任务状态尚未确认，请刷新核对。');
      if(pendingSend?.payload.request_id===task.task_id){
        if(input.value.trim()===pendingSend.payload.message){input.value='';input.style.height='auto';}
        if(pendingSend.file&&fileInput.files?.[0]===pendingSend.file)clearFile();
        pendingSend=null;
      }
    }
    if(running){
      running.dispatchUnconfirmed=dispatchUnconfirmed&&running.state==='queued';
      connect(running);
      if(dispatchUnconfirmed&&running.state==='queued'){
        running.status.textContent='任务已保存，正在核对后台派发状态…';
        recoveryTimer=setTimeout(()=>{if(epoch===generation&&allowed&&activeTask===running.id)loadConversation().catch(showFailure);},5000);
      }
    }
    else{activeTask=null;source?.close();source=null;clearTimeout(recoveryTimer);controls();}
    historyLoaded=true;scrollMessages();
  })();
  loading=promise;promise.finally(()=>{if(loading===promise)loading=null;}).catch(()=>{});return promise;
}

async function submitMessage(event){
  event.preventDefault();if(!allowed||submitting)return;
  const epoch=generation,endpoint=api,mode=chatMode;
  const sendPost=(method,body)=>request(endpoint+method,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  if(activeTask){
    if(tasks.get(activeTask)?.state==='stopping')return;
    submitting=true;controls();
    try{
      const result=await sendPost('cancel_task',{task_id:activeTask});
      if(epoch!==generation)return;
      const view=tasks.get(result.task_id);
      if(view&&mode==='business'){
        if(result.status==='stopping'){view.state='stopping';view.status.textContent=stateLabels.stopping;}
        else if(!terminalStates.has(result.status))throw Error('停止请求结果尚未确认，请恢复进度后核对。');
        // Even an immediate queued-task cancellation gets its authoritative
        // terminal event from history; the POST response is not a fake success.
        await loadConversation();
      }
    }catch(error){if(epoch===generation)showFailure(error);}
    finally{if(epoch===generation){submitting=false;controls();}}
    return;
  }
  if(!canSubmit){addMessage('assistant error',readinessReason);return;}
  const text=input.value.trim(),file=fileInput.files?.[0];if(!text&&!file)return input.focus();
  const invalidFile=fileError(file,mode);if(invalidFile){addMessage('assistant error',invalidFile);return;}
  const {day,meal}=context();if(!day)return addMessage('assistant error','业务日期还没读取完成，请稍等。');
  if(mode==='business'&&pendingSend&&(pendingSend.payload.message!==text||pendingSend.file!==file)){
    try{await loadConversation();}catch(error){if(epoch===generation)showFailure(error);}
    if(epoch===generation&&pendingSend)addMessage('assistant error','上次发送结果尚未确认，请先恢复进度或刷新核对，不要改成新请求重复办理。');
    return;
  }
  submitting=true;controls();
  const sending=addMessage('assistant',file?'正在上传业务文件…':'正在发送…');scrollMessages();
  try{
    let payload;
    if(mode==='business'){
      if(!pendingSend){
        const file_name=file?await upload(file):undefined;
        if(epoch!==generation)return;
        pendingSend={file,payload:{message:text,day,meal,stream:1,request_id:crypto.randomUUID(),view_context:currentViewContext(),...(file_name?{file_name}:{})}};
      }
      payload=pendingSend.payload;
    }else{
      const file_name=file?await upload(file):undefined;
      if(epoch!==generation)return;
      payload={message:text,day,meal,file_name,stream:1,request_id:crypto.randomUUID(),view_context:currentViewContext()};
    }
    const result=await sendPost('send_message',payload);
    if(epoch!==generation)return;
    if(typeof result?.accepted!=='boolean'||typeof result.task_id!=='string')throw Error('发送结果尚未确认，请先恢复进度。');
    pendingSend=null;
    if(result.accepted){input.value='';input.style.height='auto';clearFile();}
    if(mode==='business'){
      const view=taskView({task_id:result.task_id,message:result.accepted?text:'正在恢复已有任务…',file_name:result.accepted?file?.name:'',status:result.status||'queued'});
      activeTask=view.id;controls();
    }
    await loadConversation();
  }catch(error){
    if(epoch!==generation)return;
    // A lost response may follow a committed submission. Recover history only;
    // an explicit same-text retry reuses its original business request_id.
    try{await loadConversation();}catch(_){}
    if(epoch!==generation)return;
    if(error.notAccepted===true||error.status===400||error.status===422)pendingSend=null;
    showFailure(error);
    if(activeTask&&allowed){clearTimeout(recoveryTimer);recoveryTimer=setTimeout(()=>{if(epoch===generation)loadConversation().catch(showFailure);},5000);}
  }finally{sending.remove();if(epoch===generation){submitting=false;controls();}}
}

async function initializeChat(bootstrap){
  configureChat(bootstrap);
  // Business views stay independent of whether this user's chat is enabled.
  const initialView=initializeViews({request,bootstrap});
  if(allowed){form.hidden=false;await loadConversation();}
  else{
    messages.replaceChildren();$('chat-title').textContent='业务助手';
    addMessage('assistant',bootstrap.chat.reason||'业务对话尚未开通，可先在左侧办理有权访问的业务。');
    input.placeholder='业务对话尚未开通';form.hidden=true;
  }
  await initialView;
}

fileInput.addEventListener('change',()=>{
  const file=fileInput.files?.[0];if(!file)return clearFile();
  const error=fileError(file);if(error){clearFile();addMessage('assistant error',error);return;}
  fileName.textContent=file.name;chip.hidden=false;
});
$('chat-remove-file').addEventListener('click',clearFile);
input.addEventListener('input',()=>{input.style.height='auto';input.style.height=Math.min(input.scrollHeight,132)+'px';});
input.addEventListener('keydown',event=>{
  if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();form.requestSubmit();}
});
document.addEventListener('meal-scene:context',showContext);
form.addEventListener('submit',submitMessage);

showContext();controls();
getSceneBootstrap().then(initializeChat).catch(error=>{
  allowed=false;controls();form.hidden=true;messages.replaceChildren();
  showFailure(error);
  const retry=document.createElement('button');retry.type='button';retry.className='chat-view-result';retry.textContent='重新加载场景';
  retry.addEventListener('click',()=>window.location.reload());messages.append(retry);
});
