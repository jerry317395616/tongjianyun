"""Single-process, memory-only analysis worker reached over a private Unix socket."""

import hmac
import json
import os
import secrets
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import requests

from tongjianyun.ai_nutrition import canonical, model_messages, source_hash, validate_result


class AnalysisStore:
    def __init__(self, *, ttl=900, max_reports=16, max_concurrent=2, now=time.time, generate=None):
        self.ttl, self.max_reports, self.max_concurrent = ttl, max_reports, max_concurrent
        self.now, self.generate = now, generate
        self.records, self.lock, self.running = {}, threading.RLock(), 0

    def purge(self):
        with self.lock:
            for key in list(self.records):
                if self.records[key]["expires"] <= self.now():
                    del self.records[key]

    def create(self, owner, data):
        with self.lock:
            self.purge()
            if self.running >= self.max_concurrent or len(self.records) >= self.max_reports:
                return {"ok": False, "code": "BUSY"}
            if any(r["owner"] == owner and r["status"] == "pending" for r in self.records.values()):
                return {"ok": False, "code": "BUSY"}
            report_id = secrets.token_hex(32)
            self.records[report_id] = {"owner": owner, "data": data, "fingerprint": source_hash(data),
                                       "status": "pending", "expires": self.now() + self.ttl}
            self.running += 1
            thread = threading.Thread(target=self._generate, args=(report_id, data), daemon=True)
            thread.start()
            return {"ok": True, "report_id": report_id, "expires_at": int(self.records[report_id]["expires"])}

    def _generate(self, report_id, data):
        try:
            result = validate_result(self.generate(data), data)
            state = {"status": "ready", "result": result}
        except Exception:
            # Never retain/log a provider exception: it may embed the request or nutrient values.
            state = {"status": "failed", "error": "ANALYSIS_FAILED"}
        with self.lock:
            self.running -= 1
            self.purge()
            if report_id in self.records:
                self.records[report_id].update(state)

    def read(self, owner, report_id, *, metadata=False, discard=False):
        with self.lock:
            self.purge()
            row = self.records.get(report_id)
            if not row or not hmac.compare_digest(owner.encode(), row["owner"].encode()):
                return {"ok": False, "code": "NOT_FOUND"}
            if discard:
                del self.records[report_id]
                return {"ok": True}
            result = {"ok": True, "expires_at": int(row["expires"]), "status": row["status"],
                      "source": row["data"]["source"], "fingerprint": row["fingerprint"]}
            if not metadata and row["status"] == "ready":
                result.update(data=row["data"], result=row["result"])
            return result


def make_generator(config):
    def generate(data):
        session = requests.Session()
        session.trust_env = False
        try:
            with session.post(config["base_url"].rstrip("/") + "/chat/completions",
                              headers={"Authorization": "Bearer " + config["api_key"]},
                              json={"model": config["model"], "messages": model_messages(data),
                                    "response_format": {"type": "json_object"},
                                    "thinking": {"type": "disabled"},
                                    "max_tokens": config["max_tokens"], "temperature": 0.2},
                              timeout=(10, config["request_timeout"]), stream=True) as response:
                if response.status_code != 200:
                    raise ValueError("PROVIDER_UNAVAILABLE")
                body = bytearray()
                for block in response.iter_content(16384):
                    body.extend(block)
                    if len(body) > 262144:
                        raise ValueError("PROVIDER_RESULT_TOO_LARGE")
                output = json.loads(body)
                choice = output["choices"][0]
                if choice.get("finish_reason") != "stop":
                    raise ValueError("PROVIDER_RESULT_INCOMPLETE")
                value = json.loads(choice["message"]["content"])
                # Some compatible models add a harmless document-type tag. Discard it;
                # the actual result contract remains strict and rejects other extra fields.
                if isinstance(value, dict) and isinstance(value.get("type"), str) and len(value["type"]) <= 80:
                    value.pop("type")
                return value
        finally:
            session.close()
    return generate


def main():
    os.umask(0o077)
    config = json.loads(Path(os.environ["TONGJIANYUN_EPHEMERAL_CONFIG"]).read_text())
    required = {"enabled", "socket", "base_url", "api_key", "model", "ttl", "max_reports", "max_concurrent", "request_timeout", "max_tokens"}
    if set(config) != required or config["enabled"] is not True:
        raise SystemExit("CONFIG_INVALID")
    if not config["base_url"].startswith("https://") or not config["api_key"] or not config["model"]:
        raise SystemExit("CONFIG_INVALID")
    for key, low, high in (("ttl", 60, 3600), ("max_reports", 1, 64), ("max_concurrent", 1, 4),
                           ("request_timeout", 10, 300), ("max_tokens", 1024, 16000)):
        if type(config[key]) is not int or not low <= config[key] <= high:
            raise SystemExit("CONFIG_INVALID")
    store = AnalysisStore(ttl=config["ttl"], max_reports=config["max_reports"],
                          max_concurrent=config["max_concurrent"], generate=make_generator(config))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 393216:
                    raise ValueError
                body = json.loads(self.rfile.read(size))
                owner = body["owner"]
                if not isinstance(owner, str) or not 1 <= len(owner) <= 140:
                    raise ValueError
                if self.path == "/create" and set(body) == {"owner", "data"}:
                    result = store.create(owner, body["data"])
                elif self.path in ("/meta", "/read", "/discard") and set(body) == {"owner", "report_id"}:
                    result = store.read(owner, body["report_id"], metadata=self.path == "/meta", discard=self.path == "/discard")
                else:
                    raise ValueError
            except Exception:
                result = {"ok": False, "code": "INVALID_REQUEST"}
            payload = canonical(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

    class Server(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True

    address = Path(config["socket"])
    if address.exists():
        if not address.is_socket():
            raise SystemExit("SOCKET_PATH_INVALID")
        address.unlink()
    server = Server(str(address), Handler)
    os.chmod(address, 0o600)

    def sweep():
        while True:
            time.sleep(10)
            store.purge()

    threading.Thread(target=sweep, daemon=True).start()
    server.serve_forever(poll_interval=1)


if __name__ == "__main__":
    main()
