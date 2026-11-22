"""Fake Vertex AI and Google token endpoints: records every request, GET /_seen returns the log."""
import base64
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

SEEN = []
FAILING = {}  # location -> error word, set with GET /_fail?location=us-central1&error=exhausted
ISSUED = {"n": 0}
# A model id containing one of these words gets that Google error instead of a reply.
ERRORS = {
    "exhausted": (429, "RESOURCE_EXHAUSTED", "Resource exhausted. Please try again later."),
    "denied": (403, "PERMISSION_DENIED", "Permission 'aiplatform.endpoints.predict' denied on resource."),
    "missing": (404, "NOT_FOUND", "Publisher Model was not found or your project does not have access to it."),
    "unavailable": (503, "UNAVAILABLE", "The service is currently unavailable."),
}


def jwt_claims(assertion: str) -> dict:
    """Decode a JWT's payload without verifying it, to show what the client asked for."""
    payload = assertion.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def next_token(prefix: str) -> str:
    ISSUED["n"] += 1
    return f"{prefix}-{ISSUED['n']}"


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: object) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        if url.path == "/_seen":
            return self._send(200, SEEN)
        if url.path == "/_reset":
            SEEN.clear()
            FAILING.clear()
            return self._send(200, {"ok": True})
        if url.path == "/_fail":
            FAILING[q["location"]] = q.get("error", "exhausted")
            return self._send(200, FAILING)
        self._send(404, {"error": {"code": 404, "message": self.path, "status": "NOT_FOUND"}})

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        auth = self.headers.get("authorization", "")
        if url.path == "/token":  # OAuth2 token endpoint: a service account's signed JWT for an access token
            form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
            claims = jwt_claims(form["assertion"])
            SEEN.append({"path": "/token", "auth": "none", "body": {
                "grant_type": form["grant_type"], "iss": claims["iss"], "scope": claims.get("scope")}})
            return self._send(200, {"access_token": next_token("ya29.sa-token"), "expires_in": 3600,
                                    "token_type": "Bearer"})
        if url.path == "/v1/token":  # Security Token Service: workload identity federation
            form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
            SEEN.append({"path": "/v1/token", "auth": "none", "body": {
                k: form.get(k) for k in ("grant_type", "audience", "subject_token_type")}})
            return self._send(200, {"access_token": next_token("ya29.federated-token"), "expires_in": 3600,
                                    "token_type": "Bearer",
                                    "issued_token_type": "urn:ietf:params:oauth:token-type:access_token"})
        body = json.loads(raw or b"{}")
        parts = url.path.split("/")  # /v1/projects/<p>/locations/<l>/publishers/<pub>/models/<model>:<method>
        project, location, publisher = parts[3], parts[5], parts[7]
        model, method = parts[9].split(":")
        SEEN.append({"path": url.path, "project": project, "location": location, "publisher": publisher,
                     "model": model, "method": method,
                     "auth": f"Bearer {auth[7:]}" if auth.startswith("Bearer ") else "none", "body": body})
        for word, (code, status, msg) in ERRORS.items():
            if word in model or FAILING.get(location) == word:
                return self._send(code, {"error": {"code": code, "message": msg, "status": status}})
        if publisher == "anthropic":
            return self._send(200, {"id": "msg_fake", "type": "message", "role": "assistant", "model": model,
                                    "content": [{"type": "text", "text": f"reply from {model} in {location}"}],
                                    "stop_reason": "end_turn", "usage": {"input_tokens": 12, "output_tokens": 6}})
        self._send(200, {"candidates": [{"content": {"role": "model",
                                                     "parts": [{"text": f"reply from {model} in {location}"}]},
                                         "finishReason": "STOP"}],
                         "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 6, "totalTokenCount": 18},
                         "modelVersion": model})

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    ThreadingHTTPServer((host, int(sys.argv[1])), Handler).serve_forever()
