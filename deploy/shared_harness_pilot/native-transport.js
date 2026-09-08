/* Native Harness Client transport. The server still authorizes every account operation. */
(() => {
  const originalFetch = window.fetch.bind(window);
  const projections = new Map();
  let selectedSession;
  let visibleRows = [];
  const sleep = (signal) => new Promise((resolve, reject) => {
    if (signal.aborted) { reject(signal.reason); return; }
    const abort = () => { clearTimeout(timer); reject(signal.reason); };
    const timer = setTimeout(() => { signal.removeEventListener('abort', abort); resolve(); }, 1500);
    signal.addEventListener('abort', abort, { once: true });
  });
  async function request(path, payload, signal) {
    const response = await originalFetch(path, {
      method: payload === undefined ? 'GET' : 'POST', credentials: 'same-origin', signal,
      headers: { 'Content-Type': 'application/json' },
      ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
    });
    if (!response.ok) throw new Error('Account request failed: ' + response.status);
    return response.json();
  }
  const employee = (operation, payload, signal) => request('/employee/session/' + operation, payload, signal);
  const argsOf = payload => payload?.args ?? {};
  const requestOf = payload => argsOf(payload).request ?? argsOf(payload);
  async function invoke(endpoint, payload, signal) {
    const input = requestOf(payload);
    switch (endpoint) {
      case 'session/list': return employee('list', {}, signal);
      case 'session/create': return employee('create', {}, signal);
      case 'session/modelCatalog': return request('/native/models',undefined,signal);
      case 'session/selectModel': return request('/native/model-selection',input,signal);
      case 'commands/list': return [];
      case 'session/cancel': return request('/native/command', { operation: 'cancel', sessionId: input.sessionId }, signal);
      case 'session/rename': return request('/native/command', { operation: 'rename', sessionId: input.sessionId, title: input.title }, signal);
      case 'session/prompt': {
        if (!Array.isArray(input.content) || input.content.some(part => part.type !== 'text'))
          throw new Error('Only text business requests are available');
        await employee('prompt', { sessionId: input.sessionId, requestId: input.requestId,
          text: input.content.map(part => part.text).join('\n') }, signal);
        return { accepted: true };
      }
      case 'session/page': return employee('page', { sessionId: input.address.sessionId,
        throughSeq: input.throughSeq, beforeSeq: input.beforeSeq, maxMessages: Math.min(input.maxMessages ?? 50, 100) }, signal);
      case 'session/canOpenWorkspacePath': return { allowed: false };
      case 'settings/describe': return { namespaces: [], writable: false, hasDocument: false };
      default: throw new Error('This management operation is not available in the shared entry');
    }
  }
  async function* openStream(endpoint, payload, signal) {
    const input = requestOf(payload);
    if (endpoint === '$events') {
      await request('/employee/status', undefined, signal);
      yield { type: 'ready', clientId: crypto.randomUUID(), host: { home: '童健云' } };
      const seen = new Map();
      while (!signal.aborted) {
        const list = await employee('list', {}, signal);
        visibleRows = list.items;
        for (const row of list.items) {
          const prior = seen.get(row.sessionId);
          if (!prior) yield { type: 'emit', event: 'api-session/added', args: [row] };
          if (!prior || prior.running !== row.running)
            yield { type: 'emit', event: 'api-session/status', args: [row.sessionId, row.running] };
          if (!prior || prior.updatedAt !== row.updatedAt)
            yield { type: 'emit', event: 'api-session/activity', args: [row.sessionId, row.updatedAt] };
          seen.set(row.sessionId, row);
        }
        await sleep(signal);
      }
    } else if (endpoint === 'workspace/follow') {
      // A presentation-only group: never a filesystem workspace or a new business record.
      const group = () => ({ workspaceId: 'workspace-tongjianyun', path: '童健云', title: '童健云',
        sessionIds: visibleRows.map(row => row.sessionId),
        createdAt: '2026-09-08T00:00:00.000Z', updatedAt: '2026-09-08T00:00:00.000Z' });
      yield { type: 'baseline', value: { items: [group()], archivedSessionIds: [] } };
      let previous = '';
      while (!signal.aborted) {
        const key = JSON.stringify(visibleRows.map(row => row.sessionId));
        if (previous !== key) { yield { type: 'upsert', workspace: group() }; previous = key; }
        await sleep(signal);
      }
    } else if (endpoint === 'session/control') {
      yield { type: 'baseline', value: { queues: {}, jobs: {}, projections: {} } };
      const seen = new Map();
      while (!signal.aborted) {
        for (const [sessionId, block] of projections) {
          if (seen.get(sessionId) === block.asOfSeq) continue;
          for (const [key, value] of Object.entries(block.values))
            yield { type: 'projection', sessionId, key, value, seq: block.asOfSeq };
          seen.set(sessionId, block.asOfSeq);
        }
        await sleep(signal);
      }
    } else if (endpoint === 'session/follow') {
      if (input.address?.kind !== 'session') throw new Error('Unsupported session address');
      const sessionId = input.address.sessionId;
      selectedSession = sessionId;
      let cursor;
      while (!signal.aborted) {
        const value = await request('/native/view', { sessionId, maxMessages: Math.min(input.maxMessages ?? 50, 100),
          ...(cursor === undefined ? {} : { afterSeq: cursor }) }, signal);
        projections.set(sessionId, value.snapshot.projections);
        if (cursor === undefined) yield value.snapshot;
        else for (const event of value.events) yield event;
        cursor = value.snapshot.cursor;
        await sleep(signal);
      }
    } else throw new Error('This stream is not available in the shared entry');
  }
  window.__DSH_TRANSPORT__ = {
    ownsHost: false,
    openStream,
    async fetch(url, init) {
      const message = JSON.parse(init.body);
      let result;
      try { result = { ok: true, value: await invoke(message.method, message.payload, init.signal) }; }
      catch (error) { result = { ok: false, error: { code: 'gateway/bad-request', message: error.message, details: {} } }; }
      return new Response(JSON.stringify({ type: 'server-response', rpcId: message.rpcId, result }),
        { status: 200, headers: { 'Content-Type': 'application/json' } });
    },
  };
  document.addEventListener('DOMContentLoaded', () => {
    const nav = document.createElement('nav');
    nav.style.cssText = 'position:fixed;right:16px;top:8px;z-index:9999;display:flex;gap:12px;font:13px sans-serif;background:var(--background,#fff);padding:6px 10px;border-radius:8px';
    const approve = document.createElement('a');
    approve.textContent = '业务确认'; approve.href = '/employee/chat/'; approve.target = '_blank'; approve.rel = 'noopener';
    approve.addEventListener('click', () => { approve.href = '/employee/chat/' + (selectedSession ? '#' + selectedSession : ''); });
    const back = document.createElement('a'); back.textContent = '返回工作台'; back.href = 'https://child.myyr.top/desk';
    nav.append(approve, back); document.body.append(nav);
  });
})();
