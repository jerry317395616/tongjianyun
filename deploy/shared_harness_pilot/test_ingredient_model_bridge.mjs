import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, lstat, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {createConnection} from 'node:net';
import {validateInput, classify, startBridge} from './ingredient-model-bridge.mjs';

const value={version:1,ingredients:[{key:'a',ingredient:'大米',unit:'g'}],
  groups:[{name:'主食',is_group:0,parent_item_group:'根'}]};
const result={rows:[{key:'a',action:'existing',group:'主食',parent:'',reason:'谷物'}]};
function services(chunks) {
  return {agentDefaultModel:{currentSelection:()=>({provider:'current',model:'live-default'})},
    llm:{async *stream(options){
      assert.equal(options.provider,'current'); assert.equal(options.model,'live-default');
      assert.deepEqual(options.tools,[]); assert.ok(options.signal);
      yield* chunks;
    }}};
}
const good=[{type:'text-delta',text:JSON.stringify(result)},{type:'finish',reason:{kind:'stop'}}];
test('reject arbitrary prompts, model selection and excess input',()=>{
  assert.equal(validateInput(value),value);
  for(const invalid of [{...value,prompt:'execute'}, {...value,model:'other'},
    {...value,ingredients:[]},{...value,ingredients:[value.ingredients[0],value.ingredients[0]]},
    {...value,groups:[{...value.groups[0],secret:'x'}]}]) assert.throws(()=>validateInput(invalid));
});
test('uses live default and no tools',async()=>{
  assert.deepEqual((await classify(value,services(good),new AbortController().signal)).result,result);
});
for(const [name,chunks] of [['missing finish',good.slice(0,1)],['truncated',[...good.slice(0,1),{type:'finish',reason:{kind:'max-tokens'}}]],
  ['tool call',[{type:'tool-call-delta'}]],['large output',[{type:'text-delta',text:'x'.repeat(131073)}]],
  ['provider failure',[{type:'finish',reason:{kind:'error',failure:{message:'private'}}}]]]) {
  test('reject '+name,async()=>assert.rejects(classify(value,services(chunks),new AbortController().signal)));
}
test('abort before calling model',async()=>{
  const abort=new AbortController();abort.abort();
  await assert.rejects(classify(value,services(good),abort.signal));
});
test('private socket, real framing, teardown',async()=>{
  const dir=await mkdtemp(tmpdir()+'/tjy-model-test-');
  let close;
  try {
    close=await startBridge(services(good),dir);
    assert.equal((await lstat(dir)).mode&0o777,0o700);
    assert.equal((await lstat(dir+'/bridge.sock')).mode&0o777,0o600);
    const answer=await new Promise((resolve,reject)=>{
      const client=createConnection(dir+'/bridge.sock');let raw='';
      client.on('connect',()=>client.write(JSON.stringify(value)+'\n'));
      client.on('data',chunk=>raw+=chunk);client.on('error',reject);
      client.on('end',()=>resolve(JSON.parse(raw)));
    });
    assert.deepEqual(answer.result,result);
  } finally {await close?.();await rm(dir,{recursive:true});}
});
