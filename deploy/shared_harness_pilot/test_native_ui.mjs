import test from 'node:test';
import assert from 'node:assert/strict';
import { validView, readOwnedSnapshot } from './native-ui.mjs';
const input = { sessionId:'session-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',maxMessages:50 };
test('view input rejects authority overrides and malformed ranges', () => {
  assert.ok(validView(input));
  for (const value of [null,{}, {...input,user:'Administrator'}, {...input,sessionId:'../private'},
    {...input,maxMessages:101},{...input,afterSeq:-2},{...input,afterSeq:1.5}]) assert.ok(!validView(value));
});
for (const rejectAt of [0,1,2]) test('ownership rechecked before releasing snapshot '+rejectAt, async () => {
  let checks=0, followed=0, returned=0, disposed=0;
  const events=[{seq:0},{seq:1},{seq:2},{seq:3}];
  const services={sessionController:{follow(){followed++;return { [Symbol.asyncIterator](){return {
    async next(){return {done:false,value:{type:'snapshot',cursor:2}};},
    async return(){returned++;return {done:true};},
  };}};}},sessionQuery:{async observeSession(){return {events,[Symbol.dispose](){disposed++;}};}}};
  const authorize=async()=>{checks++;if(checks===rejectAt)throw Object.assign(new Error('denied'),{status:403});};
  const run=readOwnedSnapshot({...input,afterSeq:0},'synthetic',new AbortController().signal,services,authorize);
  if(rejectAt) await assert.rejects(run,/denied/);
  else assert.deepEqual((await run).events.map(row=>row.event.seq),[1,2]);
  assert.equal(followed,rejectAt===1?0:1);
  assert.equal(returned,followed);assert.equal(disposed,followed);
});
