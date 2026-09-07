/** Same-origin employee-only transport. No Host API, credential storage or actor parameter. */
export class EmployeeChat {
  constructor(fetcher = fetch) { this.fetcher = fetcher; this.session = null; this.cursor = -1; }
  async request(path, data, signal) {
    const response = await this.fetcher(`/employee/${path}`, {
      method: data === undefined ? 'GET' : 'POST', credentials: 'same-origin', cache: 'no-store',
      redirect: 'error', signal,
      ...(data === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }),
    });
    if (!response.ok) {
      if (response.status === 401 || response.status === 403) this.reset();
      const error = new Error('Employee request failed'); error.status = response.status; throw error;
    }
    return response.status === 204 ? null : response.json();
  }
  reset() { this.session = null; this.cursor = -1; }
  async status(signal) { return this.request('status', undefined, signal); }
  async prompt(text, signal) {
    if (!text.trim() || text.length > 6000) throw new Error('Invalid question');
    if (!this.session) {
      const created = await this.request('session/create', {}, signal);
      if (!/^session-[0-9a-f-]{36}$/.test(created.sessionId)) throw new Error('Invalid session');
      this.session = created.sessionId;
    }
    const result = await this.request('session/prompt', { sessionId: this.session, text }, signal);
    if (result.settled !== true || !Number.isSafeInteger(result.throughSeq) || result.throughSeq < 0)
      throw new Error('Invalid settlement');
    this.cursor = result.throughSeq;
    const page = await this.request('session/page', { sessionId: this.session, throughSeq: this.cursor, maxMessages: 50 }, signal);
    return { messages: messages(page), hasMore: page.hasMore === true };
  }
  async logout(signal) { await this.request('logout', {}, signal); this.reset(); }
}

/** Render only final user/assistant text, never model HTML, reasoning or raw tool payloads. */
export function messages(page) {
  if (!Array.isArray(page.records)) throw new Error('Invalid history');
  return page.records.flatMap(({ type, event }) => {
    if (type !== 'event' || !['user/message', 'assistant/message'].includes(event?.type)) return [];
    const body = event.type === 'assistant/message' ? event.data.message : event.data;
    if (!Array.isArray(body?.content)) return [];
    const text = body.content.filter(part => part.type === 'text' && typeof part.text === 'string').map(part => part.text).join('\n');
    return text ? [{ role: event.type === 'user/message' ? 'user' : 'assistant', text }] : [];
  });
}
