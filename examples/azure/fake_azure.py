"""Fake Azure OpenAI, Microsoft Foundry and Entra ID token endpoint: records every request, GET /_seen returns the log."""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

SEEN = []
FAILING = {}  # resource -> error word, set with GET /_fail?resource=eastus&error=throttled
TOKENS_ISSUED = []
# A deployment name containing one of these words gets that Azure error instead of a reply.
ERRORS = {
    "throttled": (429, {"error": {"code": "429", "message": "Requests to the ChatCompletions_Create Operation have "
                                  "exceeded call rate limit. Please retry after 6 seconds."}}),
    "filtered": (400, {"error": {"code": "content_filter", "status": 400, "param": "prompt",
                                 "message": "The response was filtered due to the prompt triggering Azure OpenAI's "
                                            "content management policy.",
                                 "innererror": {"code": "ResponsibleAIPolicyViolation", "content_filter_result": {
                                     "violence": {"filtered": True, "severity": "medium"}}}}}),
    "missing": (404, {"error": {"code": "DeploymentNotFound",
                                "message": "The API deployment for this resource does not exist."}}),
    "unavailable": (503, {"error": {"code": "ServiceUnavailable", "message": "The service is temporarily unavailable."}}),
}


def who(headers: dict) -> str:
    """Name the credential the request carried."""
    if headers.get("api-key"):
        return f"api-key {headers['api-key']}"
    auth = headers.get("authorization", "")
    return f"Bearer {auth.split(' ', 1)[1][:24]}" if auth.startswith("Bearer ") else "none"


def openai_reply(model: str) -> dict:
    return {"id": "chatcmpl-fake", "object": "chat.completion", "created": int(time.time()), "model": model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": f"reply from {model}"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18}}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: object, headers: dict | None = None) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
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
            FAILING[q["resource"]] = q.get("error", "throttled")
            return self._send(200, FAILING)
        self._send(404, {"error": {"code": "NotFound", "message": self.path}})

    def do_POST(self) -> None:
        url = urlsplit(self.path)
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        headers = {k.lower(): v for k, v in self.headers.items()}
        parts = url.path.strip("/").split("/")
        if url.path.endswith("/oauth2/v2.0/token"):  # Entra ID
            form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
            token = f"entra-token-{len(TOKENS_ISSUED) + 1}"
            TOKENS_ISSUED.append(token)
            SEEN.append({"path": url.path, "auth": "none", "body": {
                k: form.get(k) for k in ("grant_type", "client_id", "scope", "client_assertion_type")}})
            return self._send(200, {"token_type": "Bearer", "expires_in": 3600, "access_token": token})
        body = json.loads(raw or b"{}")
        # The first path segment is the resource (stands in for https://<resource>.openai.azure.com).
        resource = parts[0]
        record = {"resource": resource, "path": "/" + "/".join(parts[1:]), "query": url.query,
                  "auth": who(headers), "body": body}
        SEEN.append(record)
        target = parts[3] if len(parts) > 3 and parts[1:3] == ["openai", "deployments"] else body.get("model", "")
        for word, (code, err) in ERRORS.items():
            if word in target or FAILING.get(resource) == word:
                return self._send(code, err, {"retry-after": "6"} if code == 429 else None)
        if record["path"].endswith("/anthropic/v1/messages"):
            return self._send(200, {"id": "msg_fake", "type": "message", "role": "assistant", "model": target,
                                    "content": [{"type": "text", "text": f"reply from {target}"}],
                                    "stop_reason": "end_turn", "usage": {"input_tokens": 12, "output_tokens": 6}})
        if record["path"].endswith("/chat/completions"):
            return self._send(200, openai_reply(target))
        self._send(404, {"error": {"code": "NotFound", "message": url.path}})

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    ThreadingHTTPServer((host, int(sys.argv[1])), Handler).serve_forever()
