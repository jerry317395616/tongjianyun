/** Read-only image bridge. Uploads and arbitrary filesystem reads remain disabled. */
export async function readOwnedAttachment(value, cookie, signal, services, authorize) {
  const fail = status => Object.assign(new Error('Attachment unavailable'), { status });
  if (!value || typeof value !== 'object' || Array.isArray(value)
      || Object.keys(value).some(key => !['sessionId', 'attachmentId'].includes(key))
      || typeof value.sessionId !== 'string' || !/^session-[0-9a-f-]{36}$/.test(value.sessionId)
      || typeof value.attachmentId !== 'string' || !/^sha256:[a-f0-9]{64}$/.test(value.attachmentId)) throw fail(400);
  signal.throwIfAborted();
  const owned = { sessionId: value.sessionId, maxMessages: 1 };
  await authorize(cookie, 'session/page', owned, signal);
  signal.throwIfAborted();
  // The native controller independently proves the session references this digest.
  // Never read the shared content-addressed store directly.
  const result = await services.sessionController.attachment(value);
  await authorize(cookie, 'session/page', owned, signal);
  signal.throwIfAborted();
  if (Buffer.byteLength(JSON.stringify(result)) > 1000000) throw fail(413);
  return result;
}
