"""Task-only business client. JSON stdin avoids secret/payload command arguments."""
from __future__ import annotations

import http.client
import json
from pathlib import Path
import re
import socket
import sys

SOCKET = "/bridge/proxy.sock"
TOKEN_FILE = Path("/bridge/task-token")
MAX_REQUEST = 131072
MAX_RESPONSE = 1048576


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path=SOCKET, *, timeout=15):
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.socket_path)


def read_token(path=TOKEN_FILE):
    data = path.read_bytes()
    if not 32 <= len(data) <= 256 or not re.fullmatch(rb"[A-Za-z0-9_-]+", data):
        raise ValueError("invalid task credential")
    return data.decode("ascii")


def validate_request(value):
    if not isinstance(value, dict) or set(value) != {"tool", "arguments", "call_id"}:
        raise ValueError("expected tool, arguments and call_id")
    if not isinstance(value["tool"], str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value["tool"]):
        raise ValueError("invalid tool name")
    if not isinstance(value["arguments"], dict):
        raise ValueError("arguments must be an object")
    if not isinstance(value["call_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", value["call_id"]):
        raise ValueError("invalid call_id")
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(encoded) > MAX_REQUEST:
        raise ValueError("tool request too large")
    return encoded


def call_tool(value):
    body = validate_request(value)
    connection = UnixHTTPConnection()
    try:
        connection.connect()
        connection.request("POST", "/tools/call", body=body,
                           headers={"Authorization": "Bearer " + read_token(),
                                    "Content-Type": "application/json"})
        # Connection and request framing are bounded; task cancellation/revocation
        # owns a long-running business operation, not an arbitrary read deadline.
        connection.sock.settimeout(None)
        response = connection.getresponse()
        payload = response.read(MAX_RESPONSE + 1)
        if len(payload) > MAX_RESPONSE:
            raise ValueError("tool response too large")
        # No redirects or automatic replay, including on timeout/uncertain writes.
        if response.status != 200:
            raise RuntimeError("tool proxy rejected request (HTTP %d)" % response.status)
        result = json.loads(payload)
        if not isinstance(result, dict):
            raise ValueError("invalid tool response")
        return result
    finally:
        connection.close()


def main():
    try:
        data = sys.stdin.buffer.read(MAX_REQUEST + 1)
        if len(data) > MAX_REQUEST:
            raise ValueError("tool request too large")
        result = call_tool(json.loads(data))
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, RuntimeError, OSError, http.client.HTTPException):
        # Errors never echo request data, tokens, headers or upstream response bodies.
        print('{"ok":false,"error":"business_tool_failed","retry":"read_back_first"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
