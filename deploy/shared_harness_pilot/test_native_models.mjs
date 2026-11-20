import test from 'node:test';
import assert from 'node:assert/strict';
import {loginValue,nativeModelCatalog,selectNativeModel} from './native-models.mjs';
const sessionId='session-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
const input={sessionId,provider:'configured',model:'one'};
const admin={site:'child.myyr.top',user:'Administrator'};
const catalog={default:{provider:'configured',model:'one'},routableProviders:['configured'],
  groups:[{id:'configured',name:'Configured',models:[{id:'one',name:'One'}]}],failures:[]};
const signal=()=>new AbortController().signal;
test('login parser rejects missing duplicate malformed cookies',()=>{
  assert.equal(loginValue('__Host-dsh-shared='+'a'.repeat(43)),'a'.repeat(43));
  for(const cookie of ['', '__Host-dsh-shared=x','__Host-dsh-shared='+'a'.repeat(43)+'; __Host-dsh-shared='+'b'.repeat(43)])
    assert.throws(()=>loginValue(cookie),{status:401});
});
for(const user of ['Administrator','teacher']) test('catalog read and diagnostics redaction for '+user,async()=>{
  const result=await nativeModelCatalog('synthetic',signal(),{sessionController:{async modelCatalog(){return {...catalog,failures:[{id:'x',name:'X',message:'synthetic private upstream diagnostic'}]};}}},async()=>({site:'child.myyr.top',user}));
  assert.equal(result.failures[0].message,'Model catalog unavailable');
});
for(const principal of [{...admin,user:'teacher'},{...admin,site:'other.test'}]) test('non-admin selection rejected '+principal.user+principal.site,async()=>{
  await assert.rejects(selectNativeModel(input,'synthetic',signal(),{},async()=>assert.fail(),async()=>principal),{status:403});
});
for(const rejectAt of [0,1,2,3]) test('administrator checks at selection '+rejectAt,async()=>{
  let checks=0,writes=0;
  const services={sessionController:{async modelCatalog(){return catalog;},async selectModel(value){writes++;assert.deepEqual(value,input);return {selected:value};}}};
  const authorize=async()=>{if(++checks===rejectAt)throw new Error('revoked');return admin;};
  const promise=selectNativeModel(input,'synthetic',signal(),services,async()=>{},authorize);
  if(rejectAt) await assert.rejects(promise,/revoked/);else await promise;
  assert.equal(writes,rejectAt===1||rejectAt===2?0:1);
});
test('session ownership enforced before native model API',async()=>{
  await assert.rejects(selectNativeModel(input,'synthetic',signal(),{},async()=>{throw new Error('not owned');},async()=>admin),/not owned/);
});
test('unconfigured models and caller role overrides never reach selection',async()=>{
  const services={sessionController:{async modelCatalog(){return catalog;},selectModel(){assert.fail();}}};
  for(const value of [{...input,user:'Administrator'},{...input,model:'unconfigured'},{...input,reasoningEffort:12}])
    await assert.rejects(selectNativeModel(value,'synthetic',signal(),services,async()=>{},async()=>admin),{status:400});
});
