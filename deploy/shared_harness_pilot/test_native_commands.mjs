import test from 'node:test';
import assert from 'node:assert/strict';
import { executeOwnedCommand } from './native-ui.mjs';
const sessionId = 'session-aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa';
for (const operation of ['rename', 'cancel']) {
  for (const rejectAt of [0, 1, 2]) test(`${operation}: ownership check ${rejectAt}`, async () => {
    let checks = 0;
    const calls = [];
    const services = {sessionController: {
      cancel(value) {calls.push(value); return {accepted:true};},
      async rename(value) {calls.push(value); return {title:value.title,seq:2};},
    }};
    const authorize = async (_cookie, method, input) => {
      checks++;
      assert.equal(method, 'session/page'); assert.equal(input.sessionId, sessionId);
      if(checks === rejectAt) throw Object.assign(new Error('denied'),{status:404});
    };
    const value = {operation, sessionId, ...(operation === 'rename' ? {title:'验收会话'} : {})};
    const result = executeOwnedCommand(value,'synthetic',new AbortController().signal,services,authorize);
    if(rejectAt) await assert.rejects(result,/denied/); else await result;
    assert.equal(calls.length,rejectAt === 1 ? 0 : 1);
    if(calls.length) assert.deepEqual(calls[0],operation === 'cancel' ? {sessionId} : {sessionId,title:'验收会话'});
  });
}
test('commands reject actor overrides, global operations and malformed inputs before authorization',async()=>{
  for(const value of [null,{}, {operation:'delete',sessionId}, {operation:'cancel',sessionId,user:'Administrator'},
    {operation:'cancel',sessionId,title:'extra'}, {operation:'rename',sessionId,title:''},
    {operation:'rename',sessionId,title:'a\nb'}, {operation:'rename',sessionId,title:'a'.repeat(201)}]) {
    await assert.rejects(executeOwnedCommand(value,'synthetic',new AbortController().signal,{},async()=>assert.fail('must not authorize')),
      {status:400});
  }
});
test('aborted request performs no command',async()=>{
  const abort = new AbortController(); abort.abort(new Error('aborted'));
  await assert.rejects(executeOwnedCommand({operation:'cancel',sessionId},'synthetic',abort.signal,
    {sessionController:{cancel(){assert.fail('must not cancel');}}},async()=>{}), /aborted/);
});
