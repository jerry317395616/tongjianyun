import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('./native-transport.js',import.meta.url),'utf8');
function transport(fetch) {
  const window={fetch};
  vm.runInNewContext(source,{window,Response,Error,Map,JSON,crypto:globalThis.crypto,
    document:{addEventListener(){}},setTimeout(fn){return setTimeout(fn,0);},clearTimeout});
  return window.__DSH_TRANSPORT__;
}
test('view retries transient failures without re-submitting a prompt',async()=>{
  let calls=0;
  const api=transport(async(path)=>{assert.equal(path,'/native/view'); if(++calls===1)throw new Error('network');
    return Response.json({snapshot:{cursor:1,projections:{},type:'snapshot'},events:[]});});
  const stream=api.openStream('session/follow',{args:{address:{kind:'session',sessionId:'test'}}},new AbortController().signal);
  assert.equal((await stream.next()).value.type,'snapshot');assert.equal(calls,2);await stream.return();
});
test('view does not retry authorization failures',async()=>{
  let calls=0;const api=transport(async()=>{calls++;return new Response('',{status:401});});
  const stream=api.openStream('session/follow',{args:{address:{kind:'session',sessionId:'test'}}},new AbortController().signal);
  await assert.rejects(stream.next());assert.equal(calls,1);
});
test('prompt failure is surfaced and never automatically replayed',async()=>{
  let calls=0;const api=transport(async()=>{calls++;throw new Error('network');});
  const response=await api.fetch('',{signal:new AbortController().signal,body:JSON.stringify({method:'session/prompt',payload:{args:{sessionId:'test',content:[{type:'text',text:'hello'}]}}})});
  assert.equal((await response.json()).result.ok,false);assert.equal(calls,1);
});
test('new empty sessions publish verified model defaults at sequence minus one',async()=>{
  const calls=[];
  const block={asOfSeq:-1,values:{modelSelection:{lastUsed:null,next:null}}};
  const api=transport(async(path,init)=>{
    calls.push([path,init.body ? JSON.parse(init.body) : undefined]);
    if(path==='/employee/status')return Response.json({});
    if(path==='/employee/session/list')return Response.json({items:[{sessionId:'owned-new',running:false,updatedAt:1}]});
    if(path==='/employee/session/create')return Response.json({sessionId:'owned-new'});
    assert.equal(path,'/native/view');
    assert.deepEqual(JSON.parse(init.body),{sessionId:'owned-new',maxMessages:1});
    return Response.json({snapshot:{type:'snapshot',cursor:-1,projections:block},events:[]});
  });
  const abort=new AbortController();
  const reply=await api.fetch('',{signal:abort.signal,body:JSON.stringify({method:'session/create',payload:{args:{request:{}}}})});
  assert.equal((await reply.json()).result.value.sessionId,'owned-new');
  assert.equal(calls.length,2);
  const control=api.openStream('session/control',{},abort.signal);
  assert.deepEqual(JSON.parse(JSON.stringify((await control.next()).value)),
    {type:'baseline',value:{queues:{},jobs:{},projections:{'owned-new':block}}});
  await control.return();
  const events=api.openStream('$events',{},abort.signal);
  assert.equal((await events.next()).value.type,'ready');
  const added=(await events.next()).value;
  assert.equal(added.event,'api-session/added');
  assert.deepEqual(JSON.parse(JSON.stringify(added.args[0].projections)),block);
  await events.return();
});
test('creation does not publish a projection if the ownership-checked view is denied',async()=>{
  const api=transport(async(path)=>path==='/employee/session/create'
    ?Response.json({sessionId:'denied-view'}):new Response('',{status:403}));
  const abort=new AbortController();
  const reply=await api.fetch('',{signal:abort.signal,body:JSON.stringify({method:'session/create',payload:{args:{request:{}}}})});
  assert.equal((await reply.json()).result.ok,false);
  const control=api.openStream('session/control',{},abort.signal);
  assert.deepEqual(JSON.parse(JSON.stringify((await control.next()).value.value.projections)),{});
  await control.return();
});
