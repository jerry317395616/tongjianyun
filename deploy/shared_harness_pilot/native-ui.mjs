/** Native Harness presentation over the existing account-owned employee API. */
import { readFile } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import { request } from 'node:http';
import { nativeModelCatalog, selectNativeModel } from './native-models.mjs';
import { readOwnedAttachment } from './native-attachments.mjs';

export const name = 'tongjianyun-native-harness-ui';
export const inject = ['webServer', 'sessionController', 'sessionQuery'];
const ORIGIN = 'https://harness.myyr.top';
const BASE = '/home/zyd/frappe/native-bench/apps/tongjianyun/deploy/shared_harness_pilot/';
const INDEX = '/home/zyd/frappe/deepseek-harness/apps/web/dist/index.html';

export async function ownedRequest(cookie, operation, data, signal) {
  return new Promise((resolve, reject) => {
    const req = request({ hostname: '127.0.0.1', port: 13090, path: '/employee/' + operation,
      method: data === undefined ? 'GET' : 'POST', signal,
      headers: { Host: 'harness.myyr.top', Origin: ORIGIN, Cookie: cookie, 'Content-Type': 'application/json' },
    }, response => {
      let raw = '';
      response.on('error', reject);
      response.on('data', chunk => {
        raw += chunk.toString('utf8');
        if (Buffer.byteLength(raw) > 1000000) req.destroy(new Error('Response too large'));
      });
      response.on('end', () => {
        if (response.statusCode !== 200) {
          reject(Object.assign(new Error('Account access unavailable'), { status: response.statusCode })); return;
        }
        try { resolve(JSON.parse(raw)); } catch { reject(new Error('Invalid response')); }
      });
    });
    req.on('error', reject);
    req.end(data === undefined ? undefined : JSON.stringify(data));
  });
}

export function validView(value) {
  return value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).every(key => ['sessionId', 'maxMessages', 'afterSeq'].includes(key))
    && typeof value.sessionId === 'string' && /^session-[0-9a-f-]{36}$/.test(value.sessionId)
    && Number.isInteger(value.maxMessages) && value.maxMessages >= 1 && value.maxMessages <= 100
    && (value.afterSeq === undefined || (Number.isSafeInteger(value.afterSeq) && value.afterSeq >= -1));
}

export async function readOwnedSnapshot(value, cookie, signal, services, authorize = ownedRequest) {
  if (!validView(value)) throw Object.assign(new Error('Invalid view'), { status: 400 });
  const owned = { sessionId: value.sessionId, maxMessages: value.maxMessages };
  await authorize(cookie, 'session/page', owned, signal);
  const iterator = services.sessionController.follow({ address: { kind: 'session', sessionId: value.sessionId },
    maxMessages: value.maxMessages }, signal)[Symbol.asyncIterator]();
  let first;
  try { first = await iterator.next(); } finally { await iterator.return?.(); }
  if (first.done || first.value.type !== 'snapshot') throw new Error('Snapshot unavailable');
  let events = [];
  if (value.afterSeq !== undefined) {
    const observation = await services.sessionQuery.observeSession(value.sessionId, { signal, projectionMode: 'none' });
    try {
      events = observation.events.filter(event => event.seq > value.afterSeq && event.seq <= first.value.cursor)
        .map(event => ({ type: 'event', event }));
    } finally { observation[Symbol.dispose](); }
  }
  await authorize(cookie, 'session/page', owned, signal);
  signal.throwIfAborted();
  return { snapshot: first.value, events };
}

/** Session-local commands only; no browser-selected service, actor or filesystem path. */
export async function executeOwnedCommand(value, cookie, signal, services, authorize = ownedRequest) {
  const bad = () => Object.assign(new Error('Invalid command'), { status: 400 });
  if (!value || typeof value !== 'object' || Array.isArray(value)
      || !['cancel', 'rename'].includes(value.operation)
      || !validView({ sessionId: value.sessionId, maxMessages: 1 })
      || Object.keys(value).some(key => !['operation', 'sessionId', ...(value.operation === 'rename' ? ['title'] : [])].includes(key)))
    throw bad();
  if (value.operation === 'rename' && (typeof value.title !== 'string'
      || !value.title.trim() || value.title.length > 200 || /[\u0000-\u001f\u007f]/.test(value.title))) throw bad();
  const owned = { sessionId: value.sessionId, maxMessages: 1 };
  await authorize(cookie, 'session/page', owned, signal);
  signal.throwIfAborted();
  const result = value.operation === 'cancel'
    ? services.sessionController.cancel({ sessionId: value.sessionId })
    : await services.sessionController.rename({ sessionId: value.sessionId, title: value.title });
  // A denied response after mutation does not imply the mutation was rolled back.
  await authorize(cookie, 'session/page', owned, signal);
  signal.throwIfAborted();
  return result;
}

export function apply(ctx) {
  const active = new Map();
  let closing = false;
  async function handle(req, res, abort) {
    const closed = () => abort.abort();
    const destroy = () => { if (!res.writableEnded) { req.destroy(); res.destroy(); } };
    abort.signal.addEventListener('abort', destroy, { once: true });
    const timer = setTimeout(closed, 15000);
    res.once('close', closed);
    const send = (code, body, type = 'application/json', headers = {}) => {
      if (res.destroyed) return;
      res.writeHead(code, { 'content-type': type, 'cache-control': 'no-store',
        'referrer-policy': 'no-referrer', 'x-content-type-options': 'nosniff', ...headers });
      res.end(body);
    };
    try {
      if (req.headers.host !== 'harness.myyr.top') { send(403, '{}'); return; }
      const path = req.url;
      if (path === '/native/transport.js' && req.method === 'GET') {
        send(200, await readFile(BASE + 'native-transport.js', 'utf8'), 'text/javascript'); return;
      }
      const cookie = req.headers.cookie ?? '';
      if(path === '/native/models' && req.method === 'GET') {
        const serialized=JSON.stringify(await nativeModelCatalog(cookie,abort.signal,ctx));
        if(Buffer.byteLength(serialized)>1000000){send(503,'{}');return;}
        send(200,serialized);return;
      }
      if (path === '/native/' && req.method === 'GET') {
        try { await ownedRequest(cookie, 'status', undefined, abort.signal); }
        catch (error) {
          if (error.status === 401) {
            send(302, '', 'text/html', { location: 'https://child.myyr.top/api/method/tongjianyun.harness_shared_login.launch' }); return;
          }
          throw error;
        }
        const nonce = randomBytes(18).toString('base64');
        let html = ctx.webServer.renderIndex(await readFile(INDEX, 'utf8'));
        html = html.replace('<head>', '<head><base href="/"><script src="/native/transport.js"></script>');
        html = html.replace(/<script\b/g, '<script nonce="' + nonce + '"');
        send(200, html, 'text/html; charset=utf-8', {
          'content-security-policy': `default-src 'self'; script-src 'self' 'nonce-${nonce}' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'`,
        }); return;
      }
      if (!['/native/view', '/native/command', '/native/model-selection', '/native/attachment'].includes(path) || req.method !== 'POST') { send(404, '{}'); return; }
      if (req.headers.origin !== ORIGIN || req.headers['content-type'] !== 'application/json') { send(403, '{}'); return; }
      let raw = '';
      for await (const chunk of req) {
        raw += chunk.toString('utf8');
        if (Buffer.byteLength(raw) > 2048) { send(413, '{}'); return; }
      }
      let value;
      try { value = JSON.parse(raw); } catch { send(400, '{}'); return; }
      if (path === '/native/attachment') {
        send(200, JSON.stringify(await readOwnedAttachment(value, cookie, abort.signal, ctx, ownedRequest))); return;
      }
      if(path === '/native/model-selection') {
        send(200,JSON.stringify(await selectNativeModel(value,cookie,abort.signal,ctx,ownedRequest)));return;
      }
      // The authoritative employee operation verifies both login and ownership.
      const serialized = JSON.stringify(await (path === '/native/view'
        ? readOwnedSnapshot(value, cookie, abort.signal, ctx)
        : executeOwnedCommand(value, cookie, abort.signal, ctx)));
      if (Buffer.byteLength(serialized) > 1000000) { send(503, '{}'); return; }
      send(200, serialized);
    } catch (error) {
      send([400, 401, 403, 404, 413].includes(error.status) ? error.status : 503, '{"error":"native access unavailable"}');
    } finally { clearTimeout(timer); res.off('close', closed); abort.signal.removeEventListener('abort', destroy); }
  }
  ctx.effect(() => {
    const unregister = ctx.webServer.register({ kind: 'prefix', path: '/native', handler(req, res) {
      if (closing || active.size >= 16) { res.writeHead(503); res.end(); return; }
      const abort = new AbortController();
      const task = handle(req, res, abort);
      active.set(task, abort);
      void task.finally(() => active.delete(task));
      return task;
    } });
    return async () => {
      closing = true; unregister();
      for (const abort of active.values()) abort.abort();
      await Promise.allSettled([...active.keys()]);
    };
  });
}
