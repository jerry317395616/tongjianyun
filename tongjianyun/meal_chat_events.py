"""Project Codex JSONL onto user-facing progress, without forwarding tool output."""
from __future__ import annotations

import json
import os
import re
import selectors
import signal
import subprocess
import time


def public_text(value):
    text = str(value or '')[:16000]
    text = re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[密钥已隐藏]', text)
    text = re.sub(r'(?i)(authorization:\s*bearer\s+)\S+', r'\1[已隐藏]', text)
    return text


def progress_event(event):
    """Only declared messages and observable tool states become UI events."""
    kind = event.get('type', '')
    item = event.get('item') or {}
    item_type = item.get('type')
    item_id = str(item.get('id') or 'step')[:100]
    if item_type == 'agent_message' and kind in {'item.updated', 'item.completed'}:
        return {'kind': 'message', 'item_id': item_id, 'text': public_text(item.get('text'))}
    labels = {
        'command_execution': '执行操作', 'file_change': '更新文件',
        'mcp_tool_call': '调用业务工具', 'web_search': '查询资料',
    }
    if kind not in {'item.started', 'item.completed'} or item_type not in labels:
        return None
    label = labels[item_type]
    if item_type == 'command_execution':
        command = str(item.get('command', '')).lower()
        if any(word in command for word in ('openpyxl', 'libreoffice', '.xlsx', '.csv', 'xlrd')):
            label = '读取食谱文件'
        elif any(word in command for word in ('rg ', 'grep ', 'sed ', 'cat ', 'ls ')):
            label = '核对相关资料'
    status = 'running' if kind == 'item.started' else 'completed'
    if item.get('status') in {'failed', 'declined'} or item.get('exit_code') not in (None, 0):
        status = 'failed'
    return {'kind': 'progress', 'item_id': item_id, 'text': label, 'status': status}


def process_events(command, prompt, cwd, cancelled, heartbeat, poll_seconds=1):
    """Yield stdout JSON as it arrives. No elapsed-time execution deadline.

    Both pipes are drained so stderr cannot deadlock the child. Cancellation is
    explicit; signal escalation is only used after cancellation or runner exit.
    """
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, cwd=cwd, start_new_session=True,
                               env={**os.environ, 'PYTHONUNBUFFERED': '1'})
    selector = selectors.DefaultSelector()
    stopped_at = None
    buffer = b''
    try:
        process.stdin.write(prompt.encode('utf-8'))
        process.stdin.close()
        for pipe in (process.stdout, process.stderr):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ)
        while selector.get_map() or process.poll() is None:
            heartbeat()
            if cancelled() and stopped_at is None:
                stopped_at = time.monotonic()
                process.send_signal(signal.SIGINT)
            if stopped_at and process.poll() is None:
                elapsed = time.monotonic() - stopped_at
                if elapsed > 10:
                    process.kill()
                elif elapsed > 5:
                    process.terminate()
            for key, _ in selector.select(poll_seconds):
                data = os.read(key.fd, 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                if key.fileobj is process.stderr:
                    continue
                buffer += data
                while b'\n' in buffer:
                    line, buffer = buffer.split(b'\n', 1)
                    try:
                        event = json.loads(line)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if isinstance(event, dict):
                        yield event
                # Ignore a malformed oversized line, not an unbounded pipe buffer.
                if len(buffer) > 4 * 1024 * 1024:
                    buffer = b''
        yield {'type': 'process.exited', 'code': process.wait(), 'cancelled': stopped_at is not None}
    finally:
        selector.close()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for pipe in (process.stdout, process.stderr):
            pipe.close()


def sse_frame(event_id, payload):
    return f'id: {event_id}\nevent: update\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
