#!/usr/bin/env python3
"""Run dsh web and publish its process token for the local SSO gateway.

The web profile deliberately creates a fresh launch token on every process
start.  The gateway needs that token only for the initial browser redirect;
the Harness frontend immediately exchanges it for its own signed cookie.
"""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
from pathlib import Path


TOKEN_PATH = Path("/home/zyd/deepseek-harness-config/dsh_web_token")
PNPM = "/home/zyd/.local/bin/pnpm"
TOKEN_RE = re.compile(r"[?&]token=([A-Za-z0-9_-]+)")


def _remove_token() -> None:
    try:
        TOKEN_PATH.unlink()
    except FileNotFoundError:
        pass


def _publish_token(token: str) -> None:
    TOKEN_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = TOKEN_PATH.with_name(f".{TOKEN_PATH.name}.tmp-{os.getpid()}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(token)
            stream.write("\n")
        os.replace(temporary, TOKEN_PATH)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    _remove_token()
    child = subprocess.Popen(
        [PNPM, "dsh", "web", "--patch", "/home/zyd/frappe/deepseek-harness/apps/cli/config/examples/native-bench-business/cordis.yml",
         "--patch", "/home/zyd/frappe/native-bench/apps/tongjianyun/deploy/harness_ui_fix/cordis.yml",
         "--no-open", "--host", "127.0.0.1", "--port", "13090"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    stopping = False

    def stop_child(_signum: int, _frame: object) -> None:
        nonlocal stopping
        if stopping:
            return
        stopping = True
        if child.poll() is None:
            child.terminate()

    signal.signal(signal.SIGTERM, stop_child)
    signal.signal(signal.SIGINT, stop_child)

    assert child.stdout is not None
    for line in child.stdout:
        match = TOKEN_RE.search(line)
        if match is not None:
            _publish_token(match.group(1))
            # Do not place the live token in journald or other process logs.
            print("dsh web: http://127.0.0.1:13090/?token=[redacted]", flush=True)
        else:
            print(line, end="", flush=True)

    returncode = child.wait()
    _remove_token()
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
