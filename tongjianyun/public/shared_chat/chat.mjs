import { EmployeeChat } from './client.mjs';
const api = new EmployeeChat();
const $ = id => document.getElementById(id);
let authenticated = false, busy = false, pending;
const restored = location.hash.slice(1);
if (/^session-[0-9a-f-]{36}$/.test(restored)) api.session = restored;
function controls() {
  for (const id of ['send', 'question', 'new', 'refresh']) $(id).disabled = !authenticated || busy;
  $('logout').disabled = !authenticated;
  $('cancel').hidden = !busy;
  for (const button of document.querySelectorAll('[data-question]')) button.disabled = !authenticated || busy;
}
function clear() { api.reset(); history.replaceState(null, '', location.pathname); $('approvals').replaceChildren(); $('messages').replaceChildren(); $('question').value = ''; $('welcome').hidden = false; }
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
const stateLabels = { awaiting_confirmation: '等待你确认 · 尚未执行', succeeded: '执行成功',
  failed: '执行失败 · 请管理员核查', outcome_unknown: '结果尚不明确 · 请核查，不要重复发起业务', expired: '预览已过期 · 请重新生成' };
const operationLabels = { create: '新增', update: '修改', submit: '提交', cancel: '取消提交', delete: '删除' };
async function reviews() {
  if (api.session) history.replaceState(null, '', '#' + api.session);
  const result = await api.reviews();
  $('approvals').replaceChildren();
  for (const preview of result.items) {
    const card = document.createElement('article'); card.className = 'message approval';
    const title = document.createElement('h3');
    title.textContent = `${operationLabels[preview.plan.operation] || preview.plan.operation} · ${preview.plan.doctype} · ${preview.plan.name || '新记录'}`;
    const status = document.createElement('p'); status.textContent = stateLabels[preview.state] || '未知状态';
    const detail = document.createElement('pre');
    detail.textContent = JSON.stringify({ '修改前': preview.plan.before, '拟写入': preview.plan.changes }, null, 2);
    const note = document.createElement('p'); note.textContent = `${preview.plan.site} · ${preview.plan.user} · 影响 1 条记录 · 确认有效期至 ${new Date(preview.expires_at * 1000).toLocaleTimeString('zh-CN')} · ${preview.preview_id}`;
    card.append(title, status, detail, note);
    if (preview.state === 'awaiting_confirmation') {
      const consent = document.createElement('input'); consent.type = 'checkbox';
      const label = document.createElement('label'); label.append(consent, ' 我已核对目标记录、修改前后值，同意执行此操作');
      const button = document.createElement('button'); button.type = 'button'; button.textContent = '确认执行'; button.disabled = true;
      consent.addEventListener('change', () => { button.disabled = !consent.checked || busy; });
      button.addEventListener('click', async () => {
        if (busy || !consent.checked) return;
        busy = true; button.disabled = true; consent.disabled = true; controls();
        status.textContent = '正在确认执行，请勿重复操作…';
        try {
          const receipt = await api.confirm(preview);
          status.textContent = stateLabels[receipt.state] || '请核查执行状态';
          await reviews();
        } catch {
          status.textContent = '未取得执行回执，不能据此判断失败。请点“核查执行状态”，不要重新发起业务。';
        } finally { busy = false; controls(); }
      });
      card.append(label, button);
    }
    $('approvals').append(card);
  }
}
$('form').addEventListener('submit', async event => {
  event.preventDefault(); if (!authenticated || busy) return;
  const text = $('question').value.trim(); if (!text) return;
  busy = true; pending = new AbortController(); controls(); $('status').textContent = '正在查询，请稍候…';
  try {
    const result = await api.prompt(text, pending.signal); show(result.messages); $('question').value = '';
    await reviews();
    $('status').textContent = result.hasMore ? '已显示最近 50 条消息；较早记录未在此页展示。' : '本轮已结束，请核对回答和业务单据。';
  } catch (error) {
    if ([401, 403].includes(error.status)) { signedOut(); $('status').textContent = '登录已失效或权限已变化，请重新登录。'; }
    else { if (api.session) history.replaceState(null, '', '#' + api.session); $('status').textContent = '请求未完成或等待已停止。不会自动重试；请核查执行状态。'; }
  } finally { busy = false; pending = null; controls(); }
});
$('cancel').addEventListener('click', () => pending?.abort());
$('refresh').addEventListener('click', async () => {
  if (busy || !authenticated) return;
  busy = true; controls();
  try { show((await api.history()).messages); await reviews(); $('status').textContent = '已核查服务器记录。'; }
  catch { $('status').textContent = '无法核查，请重新登录或联系管理员；不要重复发起业务。'; }
  finally { busy = false; controls(); }
});
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
void check().then(async () => {
  if (authenticated && api.session) {
    try { show((await api.history()).messages); await reviews(); }
    catch { $('status').textContent = '无法恢复此对话，请核查登录账号，或返回工作台。'; }
  }
});
