'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../public/js/teacher_entry_compat.js'),'utf8');
const target='/desk/tongjianyun-workbench';
async function run({profiles=[{id:'teacher',enabled:true}],pathname=target,user='teacher',ok=true,fail=false,changePath=false,changeUser=false}={}) {
  const calls=[],redirects=[];
  const window={location:{pathname,replace:x=>redirects.push(x)},frappe:{session:{user},router:{on(){}}},addEventListener(){}};
  const context={window,document:{readyState:'complete',addEventListener(){}},setTimeout(){},
    fetch:async(url,options)=>{
      calls.push({url,options});
      if(changePath)window.location.pathname='/desk/student';
      if(changeUser)window.frappe.session.user='other';
      if(fail)throw new Error('Network failure');
      return {ok,json:async()=>({message:{profiles}})};
    }};
  vm.runInNewContext(source,context);
  await new Promise(resolve=>setImmediate(resolve));
  return {calls,redirects};
}
(async()=>{
  const teacher=await run();
  assert.deepEqual(teacher.redirects,['/tongjianyun-entry']);
  assert.equal(teacher.calls.length,1);
  assert.equal(teacher.calls[0].options.method,'GET');
  assert.equal(teacher.calls[0].options.cache,'no-store');
  assert.deepEqual((await run({profiles:[{id:'teacher',enabled:false}]})).redirects,['/tongjianyun-entry']);
  for(const options of [{profiles:[]},{profiles:[{id:'business',enabled:true}]},
    {profiles:[{id:'teacher',enabled:true},{id:'business',enabled:true}]},
    {ok:false},{fail:true},{changePath:true},{changeUser:true}]) {
    assert.deepEqual((await run(options)).redirects,[]);
  }
  for(const options of [{pathname:'/apps'},{pathname:target+'-other'},{user:'Guest'}]) {
    const result=await run(options);assert.equal(result.calls.length,0);assert.equal(result.redirects.length,0);
  }
  assert.deepEqual((await run({pathname:target+'/'})).redirects,['/tongjianyun-entry']);
  console.log('PASS: 13 teacher-entry compatibility cases; no role changes or writes');
})().catch(error=>{console.error(error);process.exitCode=1;});
