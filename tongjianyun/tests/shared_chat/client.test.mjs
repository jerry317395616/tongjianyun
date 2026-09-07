import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EmployeeChat, messages } from '../../public/shared_chat/client.mjs';
const id = 'session-11111111-1111-1111-1111-111111111111';
test('only scoped paths, current cookie and server cursor are used', async () => {
  const calls = [], replies = [{sessionId:id}, {settled:true,throughSeq:24}, {records:[],hasMore:false}];
  const api = new EmployeeChat(async (path, options) => { calls.push([path, options]); return {ok:true,status:200,json:async()=>replies.shift()}; });
  assert.deepEqual(await api.prompt('查询学生'), {messages:[],hasMore:false});
  assert.deepEqual(calls.map(c=>c[0]), ['/employee/session/create','/employee/session/prompt','/employee/session/page']);
  for (const [,options] of calls) { assert.equal(options.credentials,'same-origin'); assert.equal(options.redirect,'error'); }
  assert.deepEqual(JSON.parse(calls[1][1].body),{sessionId:id,text:'查询学生'});
  assert.equal(JSON.parse(calls[2][1].body).throughSeq,24);
});
test('expired authorization drops local session', async () => {
  const api = new EmployeeChat(async()=>({ok:false,status:401})); api.session=id;
  await assert.rejects(api.status(), e=>e.status===401); assert.equal(api.session,null);
});
test('cancellation propagates without automatic retry', async () => {
  const abort = new AbortController(); abort.abort(); let calls=0;
  const api = new EmployeeChat(async(_,options)=>{calls++; options.signal.throwIfAborted();});
  await assert.rejects(api.prompt('查询',abort.signal)); assert.equal(calls,1);
});
test('invalid settlement is not used to fetch history', async () => {
  let calls=0; const api=new EmployeeChat(async()=>({ok:true,status:200,json:async()=>{calls++;return {settled:true,throughSeq:'24'};}}));api.session=id;
  await assert.rejects(api.prompt('查询'));assert.equal(calls,1);
});
test('history displays only final public text and keeps HTML as text', () => {
  const rows=messages({records:[
    {type:'event',event:{type:'user/message',data:{content:[{type:'text',text:'问题'}]}}},
    {type:'event',event:{type:'assistant/message',data:{message:{content:[{type:'text',text:'<img src=x onerror=alert(1)>'},{type:'reasoning',text:'private'}]}}}},
    {type:'event',event:{type:'tool/result',data:{secret:'not displayed'}}},
  ]});
  assert.deepEqual(rows,[{role:'user',text:'问题'},{role:'assistant',text:'<img src=x onerror=alert(1)>'}]);
});
test('logout uses employee endpoint and clears state', async () => {
  const api=new EmployeeChat(async(path)=>{assert.equal(path,'/employee/logout');return {ok:true,status:204};});api.session=id;
  await api.logout(); assert.equal(api.session,null);
});
test('empty or oversized questions never issue network requests', async () => {
  const api=new EmployeeChat(()=>{throw Error('unexpected network');});
  await assert.rejects(api.prompt(' '));await assert.rejects(api.prompt('a'.repeat(6001)));
});
