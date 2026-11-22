"""Fake HashiCorp Vault KV v2: GET /v1/secret/data/<name> with an X-Vault-Token header."""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "vault-demo-token"
SECRETS = {"openai-api-key": "sk-from-vault-1111", "anthropic-api-key": "sk-ant-from-vault-2222"}
READS = []


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/_reads":
            return self._send(200, READS)
        if self.headers.get("x-vault-token") != TOKEN:
            return self._send(403, {"errors": ["permission denied"]})
        name = self.path.removeprefix("/v1/secret/data/")
        READS.append(name)
        if name not in SECRETS:
            return self._send(404, {"errors": []})
        self._send(200, {"data": {"data": {"value": SECRETS[name]}, "metadata": {"version": 3}}})

    def do_POST(self) -> None:
        # Rotate a secret: POST /v1/secret/data/<name> {"data": {"value": ...}}
        if self.headers.get("x-vault-token") != TOKEN:
            return self._send(403, {"errors": ["permission denied"]})
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)))
        SECRETS[self.path.removeprefix("/v1/secret/data/")] = body["data"]["value"]
        self._send(200, {"data": {"version": 4}})

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
