/** Model controls use signed account identity, not client role flags. */
import { createConnection } from 'node:net';
const SOCKET = '/home/zyd/frappe/state/harness/authority.sock';
const denied = () => Object.assign(new Error('Account access unavailable'), {status:403});

export function loginValue(cookie) {
  const rows = cookie.split(';').map(row=>row.trim()).filter(row=>row.startsWith('__Host-dsh-shared='));
  if(rows.length !== 1) throw Object.assign(new Error('Login unavailable'),{status:401});
  const value = rows[0].slice('__Host-dsh-shared='.length);
  if(!/^[A-Za-z0-9_-]{43}$/.test(value)) throw Object.assign(new Error('Login unavailable'),{status:401});
  return value;
}

export async function nativePrincipal(cookie, signal) {
  const value = loginValue(cookie);
  signal.throwIfAborted();
  return new Promise((resolve,reject)=>{
    const socket = createConnection({path:SOCKET,signal});
    let raw = '', ended = false, failed = false;
    const timer = setTimeout(()=>{failed=true;socket.destroy();},10000);
    socket.on('connect',()=>socket.end(JSON.stringify({version:1,operation:'authorize',value})+'\n'));
    socket.on('error',()=>{failed=true;});
    socket.on('data',chunk=>{raw+=chunk.toString('utf8');if(Buffer.byteLength(raw)>8192){failed=true;socket.destroy();}});
    socket.on('end',()=>{ended=true;});
    socket.on('close',()=>{
      clearTimeout(timer);
      if(failed || !ended || signal.aborted){reject(denied());return;}
      try {
        const answer=JSON.parse(raw);
        if(answer.ok!==true || answer.result?.site!=='child.myyr.top' || typeof answer.result.user!=='string') throw denied();
        resolve(answer.result);
      } catch {reject(denied());}
    });
  });
}

export async function nativeModelCatalog(cookie,signal,services,authorize=nativePrincipal) {
  await authorize(cookie,signal);
  const catalog = await services.sessionController.modelCatalog();
  await authorize(cookie,signal);
  signal.throwIfAborted();
  // Provider diagnostics can contain upstream URLs or credentials; never return those messages.
  return {...catalog,failures:catalog.failures.map(row=>({id:row.id,name:row.name,message:'Model catalog unavailable'}))};
}

export async function selectNativeModel(value,cookie,signal,services,owned,authorize=nativePrincipal) {
  if(!value || typeof value!=='object' || Array.isArray(value)
    || Object.keys(value).some(key=>!['sessionId','provider','model','reasoningEffort'].includes(key))
    || typeof value.sessionId!=='string' || !/^session-[0-9a-f-]{36}$/.test(value.sessionId)
    || ['provider','model'].some(key=>typeof value[key]!=='string' || !value[key] || value[key].length>200)
    || (value.reasoningEffort!==undefined && (typeof value.reasoningEffort!=='string' || value.reasoningEffort.length>100)))
    throw Object.assign(new Error('Invalid model selection'),{status:400});
  const check = async()=>{const principal=await authorize(cookie,signal);if(principal.site!=='child.myyr.top' || principal.user!=='Administrator')throw denied();};
  await check();
  await owned(cookie,'session/page',{sessionId:value.sessionId,maxMessages:1},signal);
  const catalog=await services.sessionController.modelCatalog();
  if(!catalog.groups.some(group=>group.id===value.provider && group.models.some(model=>model.id===value.model)))
    throw Object.assign(new Error('Model is not configured'),{status:400});
  await check(); signal.throwIfAborted();
  const result=await services.sessionController.selectModel(value);
  await check(); signal.throwIfAborted();
  return result;
}
