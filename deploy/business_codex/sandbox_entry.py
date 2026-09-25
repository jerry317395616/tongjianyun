"""Runs only INSIDE the completed outer OS sandbox; never a host launcher."""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import threading

ROOT = Path("/opt/business-codex")
TOKEN_FILE = Path("/bridge/task-token")
MAX_MODEL_BODY = 8388608
MODEL = "deepseek-v4-pro"


def load_client():
    spec = importlib.util.spec_from_file_location("business_tool", ROOT / "business_tool.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def codex_argv():
    # Outer bwrap+seccomp and system DynamicUser are mandatory. No host fallback.
    # Codex still has its own provider SSE idle timeout (documented default 300000
    # ms). Do not set zero: available source treats it as Duration::from_millis(0),
    # not "disabled". A timeout-free relay is not an unlimited end-to-end stream.
    return [(ROOT / "codex").as_posix(), "--no-daemon", "--ask-for-approval", "never",
            "--sandbox", "danger-full-access", "-c", 'web_search="disabled"',
            "-c", "allow_login_shell=false", "-c", 'model_provider="task_proxy"',
            "-c", 'model="' + MODEL + '"',
            "-c", 'model_providers.task_proxy.name="Task-bound model proxy"',
            "-c", 'model_providers.task_proxy.base_url="http://127.0.0.1:9111/v1"',
            "-c", 'model_providers.task_proxy.env_key="TGY_TASK_TOKEN"',
            "-c", 'model_providers.task_proxy.wire_api="responses"',
            "-c", "model_providers.task_proxy.request_max_retries=0",
            "-c", "model_providers.task_proxy.stream_max_retries=0",
            "-c", "mcp_servers={}", "-c", "plugins={}",
            "-c", "features.apps=false", "-c", "features.skills=false",
            "-c", "features.multi_agent=false", "-c", "features.memories=false",
            "exec", "--json", "--ephemeral", "--skip-git-repo-check", "-"]


def require_outer_sandbox():
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    if status.get("NoNewPrivs", "").strip() != "1" or status.get("Seccomp", "").strip() != "2":
        raise PermissionError("outer OS sandbox is required")
    if any(int(status.get(key, "1").strip(), 16) for key in ("CapEff", "CapPrm", "CapBnd", "CapAmb")):
        raise PermissionError("capabilities are not cleared")
    if Path("/home/zyd/frappe").exists() or Path("/run/docker.sock").exists():
        raise PermissionError("host paths are visible")
    if len(Path("/proc/net/route").read_text().strip().splitlines()) > 1:
        raise PermissionError("unexpected network route")
    if os.environ.get("CODEX_HOME") != "/work/codex-home" or Path.cwd() != Path("/work"):
        raise PermissionError("unexpected task home")


def make_relay(client, token):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(15)  # Bound incoming headers/body framing.

        def log_message(self, *args):
            pass

        def reject(self, status):
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True

        def do_POST(self):
            if self.path != "/v1/responses" or self.headers.get_all("Transfer-Encoding"):
                return self.reject(403)
            lengths = self.headers.get_all("Content-Length") or []
            auth = self.headers.get_all("Authorization") or []
            if len(lengths) != 1 or not lengths[0].isdigit() or not 0 < int(lengths[0]) <= MAX_MODEL_BODY:
                return self.reject(400)
            if len(auth) != 1 or not hmac.compare_digest(auth[0], "Bearer " + token):
                return self.reject(401)
            if self.headers.get_content_type() != "application/json":
                return self.reject(415)
            body = self.rfile.read(int(lengths[0]))
            if len(body) != int(lengths[0]):
                return self.reject(400)
            connection = client.UnixHTTPConnection(timeout=15)
            try:
                # Destination, headers, credential and path are fixed, never forwarded blindly.
                connection.connect()
                connection.request("POST", "/v1/responses", body=body,
                                   headers={"Authorization": "Bearer " + token,
                                            "Content-Type": "application/json"})
                # After bounded connect/request framing, task cancellation/cgroup
                # shutdown owns lifetime. Never timeout a legitimate long stream.
                connection.sock.settimeout(None)
                response = connection.getresponse()
                if response.status != 200:
                    return self.reject(502)
                self.send_response(200)
                self.send_header("Content-Type", response.getheader("Content-Type", "text/event-stream"))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
                self.connection.settimeout(None)
                while True:
                    chunk = response.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (OSError, client.http.client.HTTPException):
                self.close_connection = True
            finally:
                connection.close()

        do_GET = do_PUT = do_DELETE = do_PATCH = do_CONNECT = do_HEAD = lambda self: self.reject(405)

    server = ThreadingHTTPServer(("127.0.0.1", 9111), Handler)
    server.daemon_threads = True
    return server


def main():
    require_outer_sandbox()
    client = load_client()
    token = client.read_token(TOKEN_FILE)
    prompt = Path("/bridge/prompt.txt").read_bytes()
    if not 1 <= len(prompt) <= 131072:
        raise ValueError("invalid task prompt size")
    prompt.decode("utf-8", errors="strict")
    server = make_relay(client, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/work/home",
                   "CODEX_HOME": "/work/codex-home", "TGY_TASK_TOKEN": token,
                   "PYTHONDONTWRITEBYTECODE": "1"}
    # Credential is a revocable task token, NOT the upstream API key. It must never
    # be printed; the broker also redacts model-generated stdout/stderr before SSE.
    process = subprocess.Popen(codex_argv(), stdin=subprocess.PIPE, env=environment,
                               cwd="/work", close_fds=True)
    def terminate(_signal, _frame):
        process.terminate()
    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    try:
        process.communicate(input=prompt)
        return process.returncode
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
