/* Native Harness Client transport. The server still authorizes every account operation. */
(() => {
  const originalFetch = window.fetch.bind(window);
  const projections = new Map();
  let visibleRows = [];
  // A page opened from Frappe starts with the latest account session.  Older
  // sessions can remain blocked after an interrupted employee turn; create one
  // clean session per page instance so the official client does not keep
  // submitting into that stale turn.
  let bootstrapSessionPromise;
  const defaultWorkspace = {
    workspaceId: 'workspace-frappe', path: '/home/zyd/frappe', title: 'Frappe 项目',
    sessionIds: [], createdAt: '2026-09-08T00:00:00.000Z', updatedAt: '2026-09-08T00:00:00.000Z',
  };
  const workspaceViews = new Map([[defaultWorkspace.workspaceId, defaultWorkspace]]);
  let statusNode;
  const showStatus = text => { if (statusNode) { statusNode.textContent = text; statusNode.hidden = !text; } };
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
    if (!response.ok) {
      const status = response.status;
      const message = status === 401
        ? '登录状态已失效，请重新登录。'
        : status === 403
          ? '当前账号无权执行此操作。'
          : status >= 500
            ? 'Harness 服务或模型暂时不可用，请稍后重试。'
            : '请求失败（' + status + '），请核对结果后再操作。';
      const error = new Error(message);
      error.status = status;
      throw error;
    }
    const value = await response.json();
    if (value && value.error) throw new Error('请求未完成，请核对已保存结果；不要重复提交业务。');
    return value;
  }
  const employee = (operation, payload, signal) => request('/employee/session/' + operation, payload, signal);
  async function ensureBootstrapSession(signal) {
    if (bootstrapSessionPromise) return bootstrapSessionPromise;
    bootstrapSessionPromise = (async () => {
      const created = await employee('create', {}, signal);
      const view = await request('/native/view', { sessionId: created.sessionId, maxMessages: 1 }, signal);
      projections.set(created.sessionId, view.snapshot.projections);
      return created;
    })();
    try {
      return await bootstrapSessionPromise;
    } catch (error) {
      bootstrapSessionPromise = undefined;
      throw error;
    }
  }
  const argsOf = payload => payload?.args ?? {};
  const requestOf = payload => argsOf(payload).request ?? argsOf(payload);
  async function invoke(endpoint, payload, signal) {
    const input = requestOf(payload);
    switch (endpoint) {
      case 'session/list': {
        await ensureBootstrapSession(signal);
        return employee('list', {}, signal);
      }
      case 'session/create': {
        const created = await employee('create', {}, signal);
        // A blank session has sequence -1 but already owns default projections.
        // Hydrate those through the account-checked view before the composer
        // requests its model selection; no model request or business write runs.
        const view = await request('/native/view', { sessionId: created.sessionId, maxMessages: 1 }, signal);
        projections.set(created.sessionId, view.snapshot.projections);
        return created;
      }
      case 'directoryPicker/list': {
        const args = Array.isArray(input) ? { path: input[0] } : (input && typeof input === 'object' ? input : {});
        return request('/native/directory-picker/list', args, signal);
      }
      case 'directoryPicker/createDirectory': {
        const args = Array.isArray(input) ? { path: input[0], name: input[1] } : input;
        return request('/native/directory-picker/create', args ?? {}, signal);
      }
      case 'directoryPicker/pick': return null;
      case 'workspace/initializeDefault': {
        const workspace = workspaceViews.get(defaultWorkspace.workspaceId);
        return workspace === undefined ? undefined : { workspace };
      }
      case 'workspace/create': {
        const path = input?.path;
        if (typeof path !== 'string' || !path.startsWith('/home/zyd/frappe')) throw new Error('invalid workspace path');
        const existing = [...workspaceViews.values()].find(item => item.path === path);
        if (existing !== undefined) return { workspace: existing, created: false };
        const now = new Date().toISOString();
        const workspace = {
          workspaceId: 'workspace-' + crypto.randomUUID(), path,
          title: path.split('/').filter(Boolean).pop() || path, sessionIds: [],
          createdAt: now, updatedAt: now,
        };
        workspaceViews.set(workspace.workspaceId, workspace);
        return { workspace, created: true };
      }
      case 'workspace/rename': {
        const current = workspaceViews.get(input?.workspaceId);
        if (current === undefined) throw new Error('unknown workspace');
        const workspace = { ...current, title: input.title, updatedAt: new Date().toISOString() };
        workspaceViews.set(workspace.workspaceId, workspace);
        return { workspace };
      }
      case 'workspace/delete': {
        workspaceViews.delete(input?.workspaceId);
        return { deleted: true };
      }
      case 'workspace/insertBefore': return { workspaceIds: [...workspaceViews.keys()] };
      case 'workspace/insertSessionBefore': {
        const current = workspaceViews.get(input?.workspaceId);
        return current === undefined ? { workspace: current } : { workspace: current };
      }
      case 'workspace/archiveSession': return { archivedSessionIds: [] };
      case 'workspace/unarchiveSession': return { archivedSessionIds: [] };
      case 'workspace/pinSession': return { pinnedSessionIds: [] };
      case 'workspace/unpinSession': return { pinnedSessionIds: [] };
      case 'session/modelCatalog': return request('/native/models',undefined,signal);
      case 'session/selectModel': return request('/native/model-selection',input,signal);
      case 'session/attachment': return request('/native/attachment',input,signal);
      case 'commands/list': return [];
      case 'session/cancel': return request('/native/command', { operation: 'cancel', sessionId: input.sessionId }, signal);
      case 'session/rename': return request('/native/command', { operation: 'rename', sessionId: input.sessionId, title: input.title }, signal);
      case 'session/prompt': {
        if (!Array.isArray(input.content) || input.content.some(part => !['text', 'image'].includes(part.type)))
          throw new Error('Unsupported message content');
        const images = input.content.filter(part => part.type === 'image');
        showStatus('正在处理，请稍候。回复会自动更新，请勿重复发送。');
        try { await employee('prompt', { sessionId: input.sessionId, requestId: input.requestId,
          text: input.content.filter(part => part.type === 'text').map(part => part.text).join('\n') || 'Describe the attached image.',
          ...(images.length ? { images } : {}) }, signal);
          showStatus('');
        } catch (error) {
          // Keep the official Harness error/401 surface, but do not add a
          // second persistent banner over the composer in the Frappe embed.
          // The failed request is still returned to the official client.
          showStatus('');
          throw error;
        }
        return { accepted: true };
      }
      case 'session/page': return employee('page', { sessionId: input.address.sessionId,
        throughSeq: input.throughSeq, beforeSeq: input.beforeSeq, maxMessages: Math.min(input.maxMessages ?? 50, 100) }, signal);
      // The shared Harness is intentionally rooted at the complete Frappe
      // checkout.  The account/session gate still applies to every request,
      // while the workspace UI may open project files and folders.
      case 'session/canOpenWorkspacePath': return { allowed: true };
      case 'settings/describe': return { namespaces: [], writable: false, hasDocument: false };
      default: throw new Error('This management operation is not available in the shared entry');
    }
  }
  async function* openStream(endpoint, payload, signal) {
    const input = requestOf(payload);
    if (endpoint === '$events') {
      await request('/employee/status', undefined, signal);
      await ensureBootstrapSession(signal);
      yield { type: 'ready', clientId: crypto.randomUUID(), host: { home: '童健云' } };
      const seen = new Map();
      while (!signal.aborted) {
        const list = await employee('list', {}, signal);
        visibleRows = list.items;
        for (const row of list.items) {
          const prior = seen.get(row.sessionId);
          const block = projections.get(row.sessionId);
          const projectedAt = block?.asOfSeq;
          // Session additions carry cursor -1 defaults in the upstream wire
          // contract. Projection deltas only accept non-negative sequences.
          if (!prior || (block && prior.projectedAt !== projectedAt))
            yield { type: 'emit', event: 'api-session/added', args: [{ ...row, ...(block ? { projections: block } : {}) }] };
          if (!prior || prior.running !== row.running)
            yield { type: 'emit', event: 'api-session/status', args: [row.sessionId, row.running] };
          if (!prior || prior.updatedAt !== row.updatedAt)
            yield { type: 'emit', event: 'api-session/activity', args: [row.sessionId, row.updatedAt] };
          seen.set(row.sessionId, { ...row, projectedAt });
        }
        await sleep(signal);
      }
    } else if (endpoint === 'workspace/follow') {
      // The workspace shown in the Harness is the complete server-side Frappe
      // checkout used by the agent process.
      const groups = () => [...workspaceViews.values()].map(workspace => ({
        ...workspace,
        sessionIds: workspace.workspaceId === defaultWorkspace.workspaceId
          ? visibleRows.map(row => row.sessionId) : workspace.sessionIds,
      }));
      yield { type: 'baseline', value: { items: groups(), archivedSessionIds: [], pinnedSessionIds: [] } };
      let previous = '';
      while (!signal.aborted) {
        const snapshot = groups();
        const key = JSON.stringify(snapshot);
        if (previous !== key) {
          for (const workspace of snapshot) yield { type: 'upsert', workspace };
          previous = key;
        }
        await sleep(signal);
      }
    } else if (endpoint === 'session/control') {
      // Exactly one opening baseline is allowed per stream generation.
      yield { type: 'baseline', value: { queues: {}, jobs: {}, projections: Object.fromEntries(projections) } };
      const seen = new Map();
      while (!signal.aborted) {
        for (const [sessionId, block] of projections) {
          if (block.asOfSeq < 0 || seen.get(sessionId) === block.asOfSeq) continue;
          for (const [key, value] of Object.entries(block.values))
            yield { type: 'projection', sessionId, key, value, seq: block.asOfSeq };
          seen.set(sessionId, block.asOfSeq);
        }
        await sleep(signal);
      }
    } else if (endpoint === 'session/follow') {
      if (input.address?.kind !== 'session') throw new Error('Unsupported session address');
      const sessionId = input.address.sessionId;
      let cursor;
      let failures = 0;
      while (!signal.aborted) {
        try {
        const value = await request('/native/view', { sessionId, maxMessages: Math.min(input.maxMessages ?? 50, 100),
          ...(cursor === undefined ? {} : { afterSeq: cursor }) }, signal);
        projections.set(sessionId, value.snapshot.projections);
        if (cursor === undefined) yield value.snapshot;
        else for (const event of value.events) yield event;
        cursor = value.snapshot.cursor;
        if (failures) showStatus('回复连接已恢复。');
        failures = 0;
        } catch (error) {
          if (signal.aborted || [401, 403, 404].includes(error.status) || ++failures > 5) throw error;
          showStatus('回复连接暂时中断，正在重连（' + failures + '/5）。不会重复提交问题。');
        }
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
    statusNode = document.createElement('div');
    statusNode.setAttribute('role', 'status'); statusNode.setAttribute('aria-live', 'polite');
    statusNode.hidden = true;
    statusNode.style.cssText = 'position:fixed;bottom:90px;left:50%;transform:translateX(-50%);z-index:9999;background:#164638;color:white;padding:10px 16px;border-radius:8px;max-width:80%;font:14px sans-serif';
    document.body.append(statusNode);
  });
})();
