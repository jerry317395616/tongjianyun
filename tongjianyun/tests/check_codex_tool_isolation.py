"""Inspect advertised tools with a local rejecting model stub; never forward inference."""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from tongjianyun import codex_ingredient_client as client

def run():
    captured = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.extend(value.get("tools", []))
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error":{"message":"isolation probe complete"}}')

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    provider = 'model_providers.ingredient={name="ingredient",base_url="http://127.0.0.1:%d/v1",wire_api="responses",request_max_retries=0}' % server.server_port
    try:
        with patch.object(client, "PROVIDER", provider):
            try:
                asyncio.run(client.CodexIngredientClient()._bounded("只回复 OK"))
            except (ValueError, TimeoutError):
                pass
        names = []
        def visit(tool):
            names.append(tool.get("name") or tool.get("type"))
            for child in tool.get("tools", []):
                visit(child)
        for tool in captured:
            visit(tool)
        assert captured, "No model request captured; isolation not verified"
        allowed = {"update_plan", "request_user_input", "namespace", "functions"}
        assert set(names) <= allowed, "Unexpected exposed tools: " + str(names)
        print(json.dumps({"tool_isolation_verified": True, "tools": names, "business_writes": 0}))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

if __name__ == "__main__":
    run()
