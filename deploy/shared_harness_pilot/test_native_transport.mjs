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
