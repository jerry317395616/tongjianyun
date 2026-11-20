import test from 'node:test';
import assert from 'node:assert/strict';
import { readOwnedAttachment } from './native-attachments.mjs';
const value = { sessionId:'session-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', attachmentId:'sha256:'+'a'.repeat(64) };
const signal = () => new AbortController().signal;
for (const denyAt of [0, 1, 2]) test(`attachment ownership check ${denyAt}`, async () => {
  let checks = 0, reads = 0;
  const result = { attachment:{attachmentId:value.attachmentId}, data:'AQ==' };
  const services = {sessionController:{async attachment(input){reads++; assert.deepEqual(input,value); return result;}}};
  const authorize = async (cookie, method, input) => {
    assert.equal(cookie,'synthetic'); assert.equal(method,'session/page');
    assert.deepEqual(input,{sessionId:value.sessionId,maxMessages:1});
    if(++checks === denyAt) throw Object.assign(new Error('denied'),{status:404});
  };
  const task = readOwnedAttachment(value,'synthetic',signal(),services,authorize);
  if(denyAt) await assert.rejects(task,{status:404}); else assert.deepEqual(await task,result);
  assert.equal(reads,denyAt === 1 ? 0 : 1);
});
test('reject paths, actor overrides, malformed identifiers and extra fields', async () => {
  for(const input of [null,{},[],{...value,user:'Administrator'},{...value,path:'/etc/passwd'},
    {...value,attachmentId:'../../secret'},{...value,sessionId:'other'}, {...value,attachmentId:'sha256:a'}]) {
    await assert.rejects(readOwnedAttachment(input,'synthetic',signal(),{},async()=>assert.fail('no authorization')),{status:400});
  }
});
test('native reference validation failures are not replaced with shared-store reads', async () => {
  await assert.rejects(readOwnedAttachment(value,'synthetic',signal(),{sessionController:{attachment(){throw new Error('not referenced');}}},async()=>{}),/not referenced/);
});
test('oversized responses are not released', async () => {
  await assert.rejects(readOwnedAttachment(value,'synthetic',signal(),{sessionController:{attachment(){return {data:'a'.repeat(1000001)};}}},async()=>{}),{status:413});
});
for(const when of ['before','during']) test(`abort ${when} read suppresses data`,async()=>{
  const controller=new AbortController();
  if(when==='before') controller.abort();
  let reads=0;
  await assert.rejects(readOwnedAttachment(value,'synthetic',controller.signal,{sessionController:{attachment(){reads++;controller.abort();return {data:'AQ=='};}}},async()=>{}),{name:'AbortError'});
  assert.equal(reads,when==='before'?0:1);
});
