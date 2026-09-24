const $=id=>document.getElementById(id);
const form=$('chat-form'),input=$('chat-input'),fileInput=$('chat-file'),send=$('chat-send');
const messages=$('chat-messages'),chip=$('chat-file-chip'),fileName=$('chat-file-name');
const mealNames={breakfast:'早餐',morning_snack:'早点',lunch:'午餐',afternoon_snack:'午点',dinner:'晚餐'};
let allowed=false,busy=false;

function addMessage(kind,text,extra=''){
  const node=document.createElement('div');
  node.className=`chat-message ${kind} ${extra}`.trim();
  node.textContent=text;
  messages.append(node);
  messages.scrollTop=messages.scrollHeight;
  return node;
}
function context(){return {day:$('day').value,meal:$('meal').value};}
function showContext(){
  const {day,meal}=context();
  $('chat-context').textContent=day?`${day} · ${mealNames[meal]||'午餐'}`:'正在读取业务日期…';
}
function controls(){
  send.disabled=!allowed||busy;
  input.disabled=!allowed||busy;
  fileInput.disabled=!allowed||busy;
  document.querySelector('.chat-attach').classList.toggle('disabled',!allowed||busy);
}
function errorText(body,status){
  try{
    const row=JSON.parse(body._server_messages||'[]')[0];
    const item=typeof row==='string'?JSON.parse(row):row;
    if(item?.message)return new DOMParser().parseFromString(item.message,'text/html').body.textContent;
  }catch(_){}
  return status===403?'当前账号没有此操作权限。':'操作没有完成，请稍后再试。';
}
async function request(path,options={}){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),115000);
  try{
    const response=await fetch(path,{credentials:'same-origin',cache:'no-store',signal:controller.signal,
      headers:{Accept:'application/json',...(options.method==='POST'?{'X-Frappe-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content}:{})},...options});
    const body=await response.json().catch(()=>({}));
    if(!response.ok||body.exc)throw Error(errorText(body,response.status));
    return body.message;
  }catch(error){
    if(error.name==='AbortError')throw Error('处理时间较长，请先核对周历，再决定是否重发。');
    if(error instanceof TypeError)throw Error('网络中断。请先核对周历，再决定是否重发。');
    throw error;
  }finally{clearTimeout(timer);}
}
function clearFile(){fileInput.value='';chip.hidden=true;fileName.textContent='';}
async function upload(file){
  const data=new FormData();data.append('file',file);data.append('is_private','1');
  const uploaded=await request('/api/method/upload_file',{method:'POST',body:data});
  if(!uploaded?.name)throw Error('文件未上传成功。');
  return uploaded.name;
}

fileInput.addEventListener('change',()=>{
  const file=fileInput.files?.[0];
  if(!file)return clearFile();
  if(file.size>10*1024*1024){clearFile();addMessage('assistant','文件不能超过 10 MB。','error');return;}
  fileName.textContent=file.name;chip.hidden=false;
});
$('chat-remove-file').addEventListener('click',clearFile);
input.addEventListener('input',()=>{input.style.height='auto';input.style.height=Math.min(input.scrollHeight,132)+'px';});
input.addEventListener('keydown',event=>{
  if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();form.requestSubmit();}
});
document.addEventListener('meal-scene:context',showContext);
$('day').addEventListener('change',showContext);
$('meal').addEventListener('change',showContext);

form.addEventListener('submit',async event=>{
  event.preventDefault();
  if(!allowed||busy)return;
  const text=input.value.trim(),file=fileInput.files?.[0];
  if(!text&&!file)return input.focus();
  const {day,meal}=context();
  if(!day)return addMessage('assistant','业务日期还没读取完成，请稍等。','error');
  busy=true;controls();
  addMessage('user',[text,file?`上传：${file.name}`:''].filter(Boolean).join('\n'));
  const pending=addMessage('assistant','正在处理…','busy');
  try{
    const file_name=file?await upload(file):undefined;
    const result=await request('/api/method/tongjianyun.meal_chat.send_message',{
      method:'POST',headers:{'Content-Type':'application/json','X-Frappe-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},
      body:JSON.stringify({message:text,day,meal,file_name})});
    pending.classList.remove('busy');pending.textContent=result?.reply||'已经处理，请查看周历。';
    input.value='';input.style.height='auto';clearFile();
    $('refresh').click();
  }catch(error){pending.classList.remove('busy');pending.classList.add('error');pending.textContent=error.message||'操作没有完成。';}
  finally{busy=false;controls();messages.scrollTop=messages.scrollHeight;input.focus();}
});

showContext();controls();
request('/api/method/tongjianyun.meal_chat.get_chat_access').then(result=>{
  allowed=!!result?.allowed;
  if(!allowed)addMessage('assistant','当前账号暂不能使用对话，请联系管理员。','error');
  controls();
}).catch(error=>{addMessage('assistant',error.message||'对话服务暂不可用。','error');controls();});
