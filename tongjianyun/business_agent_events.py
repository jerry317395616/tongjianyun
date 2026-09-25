"""Bounded Codex exec JSONL -> durable public business events (no task transitions).

Protocol reference, fetched 2026-09-25:
https://learn.chatgpt.com/docs/non-interactive-mode#make-output-machine-readable
Codex emits thread/turn/item lifecycle events, not public SSE deltas. Agent text
is an item snapshot. Consumers must upsert `message` by item_id, never append it
as a delta. Completed messages may legitimately have no preceding item.started.
The observed Codex 0.156.1 stream can also complete an `error` item between
thread.started and turn.started, then execute successfully. Error notices are
diagnostic, not equivalent to turn.failed; their raw messages remain private.

Usage by a TRUSTED worker (not an HTTP endpoint or model-selected callback):
    projector = CodexEventProjector(lambda event: store.emit(claim, event),
                                    secrets=(task_token, claim.token))
    projector.feed(stdout_bytes)  # stderr is drained separately and NEVER fed
    observed = projector.finish_input()
The supervisor combines observed.turn_completed with actual process/cgroup
exit, cancellation/authority and in-flight writes before store.finish(claim).
This module never emits terminal/view or calls finish/cancel, and a model's
claim of success is only answer text. Do not restart/replay a projector after
an uncertain emit: SSE reconnection reads the store's committed event cursor.

Only finished text lines from item.updated are published; the unfinished last
line waits for item.completed. This avoids publishing half of a credential
before a later snapshot makes it recognizable. Tool output, commands, errors,
reasoning, environment and usage are never mapped to public text. Public text
redaction is defense-in-depth, not a semantic proof that model prose is true.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
from typing import Callable

from tongjianyun.meal_chat_events import public_text

MAX_LINE_BYTES = 1024 * 1024
MAX_STREAM_BYTES = 16 * 1024 * 1024
MAX_EVENTS = 10000
MAX_ITEMS = 512
MAX_TEXT_CHARS = 16000
MAX_PUBLIC_TEXT_BYTES = 24000  # Store public_event's entire JSON must fit 32768.
MAX_PUBLIC_EVENTS = 2048
_IDENTIFIER = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_PHASES = {'command_execution': '执行操作', 'file_change': '更新文件',
           'mcp_tool_call': '调用业务工具', 'web_search': '查询资料', 'todo_list': '整理处理步骤'}
_ITEMS = frozenset({'agent_message', 'reasoning', 'error', *_PHASES})
_INTERNAL = re.compile(
    r'(?m)^\s*(?:```|Traceback \(most recent call last\):|File ["\'].+["\'], line \d+'
    r'|at [\w.$]+\([^\n]*:\d+|(?:export\s+)?[A-Z][A-Z0-9_]{2,}\s*='
    r'|(?:\$ |PS [^\n]*>\s|(?:sudo\s+)?(?:bash|sh|python3?|node|curl|ssh|cat|env|printenv)\s))')


class ProjectionError(ValueError):
    """Fixed public-safe protocol errors; never include input text or JSON."""


class ProjectionDeliveryError(RuntimeError):
    """The event sink may have committed; do not blindly resend or replay."""


@dataclass(frozen=True)
class CodexObservation:
    thread_started: bool
    turn_started: bool
    turn_completed: bool
    turn_failed: bool
    error_seen: bool  # Diagnostic only; a recoverable notice does not veto a completed turn.
    input_closed: bool
    cancelled: bool
    protocol_failed: bool
    delivery_uncertain: bool
    input_events: int
    published_events: int
    published_messages: int


@dataclass
class _Item:
    kind: str
    public_id: str
    completed: bool = False
    text: str = ''
    published: str = ''
    progress: str = ''


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProjectionError('Duplicate event keys')
        result[key] = value
    return result


def _finite(_):
    raise ProjectionError('Non-finite event value')


def _depth(value, level=0):
    if level > 16:
        raise ProjectionError('Event nesting exceeds limit')
    if type(value) is dict:
        for child in value.values():
            _depth(child, level + 1)
    elif type(value) is list:
        for child in value:
            _depth(child, level + 1)
    elif type(value) is float and not math.isfinite(value):
        raise ProjectionError('Non-finite event value')


class CodexEventProjector:
    """One invocation/worker claim, fed sequentially from that stdout pipe only.

    `emit(event)` has exactly the event argument expected by
    `lambda event: BusinessTaskStore.emit(claim, event)`. It must synchronously
    persist or raise. Emission exceptions seal this instance and are not retried.
    `cancel()` only stops this projection; the supervisor must separately revoke
    tools, stop the process and finish the task using authoritative observations.
    """
    def __init__(self, emit: Callable[[dict], object], *, secrets=()):
        if not callable(emit):
            raise ValueError('A trusted public-event sink is required')
        if (not isinstance(secrets, (tuple, list)) or len(secrets) > 16
                or any(not isinstance(value, str) or not 8 <= len(value) <= 512
                       or any(ord(char) < 32 for char in value) for value in secrets)):
            raise ValueError('Invalid trusted redaction values')
        self._emit_callback = emit
        self._secrets = tuple(secrets)
        self._buffer = bytearray()
        self._bytes = self._events = self._published_events = self._published_messages = 0
        self._thread = None
        self._turn = 'new'
        self._items = {}
        self._error = self._closed = self._cancelled = self._bad = self._uncertain = False
        self._statuses = set()

    @property
    def observation(self):
        return CodexObservation(thread_started=self._thread is not None,
            turn_started=self._turn != 'new',
            turn_completed=(self._turn == 'completed' and not any(
                (self._bad, self._uncertain, self._cancelled))),
            turn_failed=self._turn == 'failed', error_seen=self._error,
            input_closed=self._closed, cancelled=self._cancelled, protocol_failed=self._bad,
            delivery_uncertain=self._uncertain, input_events=self._events,
            published_events=self._published_events, published_messages=self._published_messages)

    def _fail(self, reason):
        self._bad = True
        self._buffer.clear()
        raise ProjectionError(reason) from None

    def _emit(self, event):
        if self._published_events >= MAX_PUBLIC_EVENTS:
            self._fail('Public event count exceeds limit')
        try:
            self._emit_callback(event)
        except Exception:
            # A commit could have happened before the sink raised. Seal instead
            # of guessing and duplicating a message/event on the next feed.
            self._uncertain = True
            self._buffer.clear()
            raise ProjectionDeliveryError('Public event delivery is uncertain; do not replay') from None
        self._published_events += 1
        if event['kind'] == 'message':
            self._published_messages += 1

    def _status(self, name, text):
        if name not in self._statuses:
            self._emit({'kind': 'status', 'text': text})
            self._statuses.add(name)

    def _text(self, value):
        text = public_text(value)
        # public_text remains the common baseline. Add task-local capabilities
        # and short sk- prefixes, which must not escape through a partial line.
        for secret in self._secrets:
            text = text.replace(secret, '[凭据已隐藏]')
        for word in set(re.findall(r'[A-Za-z0-9_-]{8,}', text)):
            if any(secret.startswith(word) for secret in self._secrets):
                text = text.replace(word, '[凭据已隐藏]')
        text = re.sub(r'\bsk-[A-Za-z0-9_-]*', '[密钥已隐藏]', text)
        text = re.sub(r'(?i)(\b(?:api[_-]?key|password|token|secret)\s*[:=]\s*)\S+', r'\1[已隐藏]', text)
        text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
        text = ''.join(char for char in text if ord(char) >= 32 or char in '\n\t')
        internal = _INTERNAL.search(text)
        if internal:
            text = text[:internal.start()].rstrip() + '\n[内部执行细节已隐藏]'
        try:
            length = len(text.encode('utf-8'))
        except UnicodeError:
            self._fail('Invalid assistant text encoding')
        if length > MAX_PUBLIC_TEXT_BYTES:
            self._fail('Public message size exceeds limit')
        return text

    def _item(self, event_type, value):
        if type(value) is not dict:
            self._fail('Invalid item schema')
        before_turn_notice = (self._thread is not None and self._turn == 'new'
                              and event_type == 'item.completed' and value.get('type') == 'error')
        if self._turn != 'running' and not before_turn_notice:
            self._fail('Item outside an active turn')
        identifier, kind = value.get('id'), value.get('type')
        if (not isinstance(identifier, str) or not _IDENTIFIER.fullmatch(identifier)
                or not isinstance(kind, str) or kind not in _ITEMS):
            self._fail('Unsupported item schema')
        item = self._items.get(identifier)
        if item is None:
            if len(self._items) >= MAX_ITEMS:
                self._fail('Item count exceeds limit')
            # Even a hostile item ID cannot carry a task token into public SSE.
            item = self._items[identifier] = _Item(kind, 'codex-' + hashlib.sha256(identifier.encode()).hexdigest()[:24])
        elif item.kind != kind:
            self._fail('Item type changed')
        completed = event_type == 'item.completed'
        if item.completed and not completed:
            self._fail('Completed item reopened')
        if kind == 'agent_message':
            text = value.get('text', '')
            if not isinstance(text, str) or len(text) > MAX_TEXT_CHARS:
                self._fail('Invalid assistant message')
            if not text.startswith(item.text) or item.completed and text != item.text:
                self._fail('Assistant snapshot is not append-only')
            item.text = text
            available = text if completed else text[:text.rfind('\n') + 1]
            public = self._text(available)
            if public.strip() and public != item.published:
                self._emit({'kind': 'message', 'item_id': item.public_id, 'text': public})
                item.published = public
        elif kind in _PHASES:
            status = value.get('status')
            if status is not None and status not in ('in_progress', 'completed', 'failed', 'declined'):
                self._fail('Unsupported tool status')
            code = value.get('exit_code')
            if code is not None and type(code) is not int:
                self._fail('Invalid tool exit code')
            progress = ('failed' if status in ('failed', 'declined') or code not in (None, 0)
                        else 'completed' if completed else 'running')
            if item.completed and progress != item.progress:
                self._fail('Completed tool state changed')
            if progress != item.progress:
                self._emit({'kind': 'progress', 'item_id': item.public_id,
                            'text': _PHASES[kind], 'status': progress})
                item.progress = progress
        elif kind == 'error':
            self._error = True
            self._status('error', '收到运行提示，正在核对执行状态。')
        # Reasoning and all raw item payloads intentionally have no projection.
        item.completed = completed

    def _line(self, raw):
        if not raw.strip():
            self._fail('Empty JSONL event')
        self._events += 1
        if self._events > MAX_EVENTS or len(raw) > MAX_LINE_BYTES:
            self._fail('Input event limit exceeded')
        try:
            value = json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_finite)
            _depth(value)
        except (ValueError, UnicodeError, RecursionError):
            self._fail('Invalid JSONL event')
        if type(value) is not dict or not isinstance(value.get('type'), str):
            self._fail('Invalid event schema')
        kind = value['type']
        if kind == 'thread.started':
            identity = value.get('thread_id')
            if (not isinstance(identity, str) or not _IDENTIFIER.fullmatch(identity)
                    or self._thread not in (None, identity) or self._turn != 'new'):
                self._fail('Invalid thread event order')
            self._thread = identity
        elif kind == 'turn.started':
            if self._thread is None or self._turn not in ('new', 'running'):
                self._fail('Invalid turn start order')
            self._turn = 'running'
            self._status('start', '正在处理你的需求…')
        elif kind in ('item.started', 'item.updated', 'item.completed'):
            self._item(kind, value.get('item'))
        elif kind in ('turn.completed', 'turn.failed'):
            target = kind.split('.')[1]
            if self._turn not in ('running', target):
                self._fail('Invalid turn result order')
            self._turn = target
            self._status('turn-result', '助手已返回结果，正在核对执行状态。' if target == 'completed'
                         else '本轮处理遇到问题，正在核对执行结果。')
        elif kind == 'error':
            self._error = True
            self._status('error', '收到运行提示，正在核对执行状态。')
        else:
            self._fail('Unsupported Codex event type')

    def feed(self, chunk: bytes):
        if self._cancelled:
            return self.observation
        if self._closed or self._bad or self._uncertain:
            raise ProjectionError('Projection is sealed; do not replay')
        if not isinstance(chunk, bytes):
            self._fail('JSONL input must be bytes')
        self._bytes += len(chunk)
        if self._bytes > MAX_STREAM_BYTES:
            self._fail('Input stream size exceeds limit')
        self._buffer.extend(chunk)
        while b'\n' in self._buffer:
            end = self._buffer.index(b'\n')
            line = bytes(self._buffer[:end])
            del self._buffer[:end + 1]
            self._line(line)
        if len(self._buffer) > MAX_LINE_BYTES:
            self._fail('Input line size exceeds limit')
        return self.observation

    def finish_input(self):
        if self._cancelled:
            self._closed = True
            return self.observation
        if self._bad or self._uncertain:
            raise ProjectionError('Projection is sealed; do not replay')
        if not self._closed and self._buffer:
            raw = bytes(self._buffer)
            self._buffer.clear()
            self._line(raw)  # Accept a complete last JSON object without newline.
        self._closed = True
        return self.observation

    def cancel(self):
        self._cancelled = True
        self._buffer.clear()
        return self.observation
