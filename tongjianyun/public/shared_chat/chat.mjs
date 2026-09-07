import { EmployeeChat } from './client.mjs';
const api = new EmployeeChat();
const $ = id => document.getElementById(id);
let authenticated = false, busy = false, pending;
function controls() {
  for (const id of ['send', 'question', 'new']) $(id).disabled = !authenticated || busy;
  $('logout').disabled = !authenticated;
  $('cancel').hidden = !busy;
  for (const button of document.querySelectorAll('[data-question]')) button.disabled = !authenticated || busy;
}
function clear() { api.reset(); $('messages').replaceChildren(); $('question').value = ''; $('welcome').hidden = false; }
function signedOut() { authenticated = false; clear(); $('login').hidden = false; controls(); }
async function check() {
  try {
    const state = await api.status();
    authenticated = state.agentExecution === true && state.access === 'read-only-turns';
    if (!authenticated) clear();
    $('login').hidden = true;
    $('status').textContent = authenticated ? '已连接 · 查询范围由当前账号权限决定' : '共享只读对话尚未开放，请联系管理员。';
  } catch { signedOut(); $('status').textContent = '请通过童健云登录；若仍无法连接，请联系管理员。'; }
  controls();
}
function show(rows) {
  $('messages').replaceChildren();
  for (const row of rows) {
    const article = document.createElement('article'); article.className = `message ${row.role}`;
    const label = document.createElement('strong'); label.textContent = row.role === 'user' ? '你' : '童健云助手';
    const text = document.createElement('div'); text.textContent = row.text;
    article.append(label, text); $('messages').append(article);
  }
  $('welcome').hidden = rows.length > 0;
}
$('form').addEventListener('submit', async event => {
  event.preventDefault(); if (!authenticated || busy) return;
  const text = $('question').value.trim(); if (!text) return;
  busy = true; pending = new AbortController(); controls(); $('status').textContent = '正在查询，请稍候…';
  try {
    const result = await api.prompt(text, pending.signal); show(result.messages); $('question').value = '';
    $('status').textContent = result.hasMore ? '已显示最近 50 条消息；较早记录未在此页展示。' : '本轮已结束，请核对回答和业务单据。';
  } catch (error) {
    if ([401, 403].includes(error.status)) { signedOut(); $('status').textContent = '登录已失效或权限已变化，请重新登录。'; }
    else { clear(); $('status').textContent = '请求未完成或等待已停止；结果状态未知。为避免重复执行，不会自动重试，请新建对话后核查。'; }
  } finally { busy = false; pending = null; controls(); }
});
$('cancel').addEventListener('click', () => pending?.abort());
$('new').addEventListener('click', () => { if (!busy) { clear(); $('status').textContent = '新对话已准备好。'; $('question').focus(); } });
$('logout').addEventListener('click', async () => {
  pending?.abort(); signedOut();
  try { await api.logout(); $('status').textContent = '已退出 AI 助手。童健云登录状态不受影响。'; }
  catch { $('status').textContent = '未能确认服务器退出成功，请重试或关闭页面。'; $('logout').disabled = false; }
});
for (const button of document.querySelectorAll('[data-question]')) button.addEventListener('click', () => {
  $('question').value = button.dataset.question; $('question').focus();
});
window.addEventListener('pagehide', () => pending?.abort());
window.addEventListener('focus', () => { if (!busy) void check(); });
void check();
