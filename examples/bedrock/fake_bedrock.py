"""Fake Bedrock runtime and STS: records every signed request and answers Converse, Invoke and AssumeRole."""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote

SEEN = []
FAILING = {}  # region -> error word, set with GET /_fail?region=us-west-2&error=throttled
# A model id containing one of these words gets that AWS error instead of a reply.
ERRORS = {
    "throttled": (429, "ThrottlingException", "Too many requests, please wait before trying again."),
    "denied": (403, "AccessDeniedException", "You don't have access to the model with the specified model ID."),
    "invalid": (400, "ValidationException", "The provided model identifier is invalid."),
    "unavailable": (503, "ServiceUnavailableException", "Bedrock is unable to process your request."),
}
STS_REPLY = """<AssumeRoleResponse xmlns="https://sts.amazonaws.com/doc/2011-06-15/"><AssumeRoleResult>
<Credentials><AccessKeyId>ASIAASSUMEDROLE0001</AccessKeyId><SecretAccessKey>assumed-secret</SecretAccessKey>
<SessionToken>assumed-session-token</SessionToken><Expiration>{exp}</Expiration></Credentials>
<AssumedRoleUser><Arn>{arn}/{session}</Arn><AssumedRoleId>AROAFAKE:{session}</AssumedRoleId></AssumedRoleUser>
</AssumeRoleResult></AssumeRoleResponse>"""


def scope(auth: str | None) -> dict:
    """Pull the access key, region and service out of a SigV4 Authorization header."""
    if not auth or not auth.startswith("AWS4-HMAC-SHA256"):
        return {"scheme": (auth or "none").split(" ")[0]}
    cred = auth.split("Credential=")[1].split(",")[0].split("/")
    return {"scheme": "SigV4", "access_key": cred[0], "region": cred[2], "service": cred[3]}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: object, ctype: str = "application/json", headers: dict | None = None) -> None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/_seen":
            return self._send(200, SEEN)
        if self.path == "/_reset":
            SEEN.clear()
            FAILING.clear()
            return self._send(200, {"ok": True})
        if self.path.startswith("/_fail?"):
            q = {k: v[0] for k, v in parse_qs(self.path.split("?", 1)[1]).items()}
            FAILING[q["region"]] = q.get("error", "throttled")
            return self._send(200, FAILING)
        self._send(404, {"message": "not found"})

    def do_POST(self) -> None:
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        record = {"path": unquote(self.path), "auth": scope(self.headers.get("authorization")),
                  "session_token": bool(self.headers.get("x-amz-security-token")), "body": None}
        if self.path == "/":  # STS
            form = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
            record["body"] = {k: form.get(k) for k in ("Action", "RoleArn", "RoleSessionName")}
            SEEN.append(record)
            exp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 3600))
            return self._send(200, STS_REPLY.format(exp=exp, arn=form.get("RoleArn"), session=form.get("RoleSessionName")),
                              "text/xml")
        record["body"] = json.loads(raw or b"{}")
        SEEN.append(record)
        model = record["path"].split("/model/")[1].rsplit("/", 1)[0]
        for word, (code, kind, msg) in ERRORS.items():
            if word in model or FAILING.get(record["auth"].get("region")) == word:
                return self._send(code, {"message": msg}, headers={"x-amzn-errortype": f"{kind}:http://internal.amazon.com/"})
        if record["path"].endswith("/converse"):
            return self._send(200, {
                "output": {"message": {"role": "assistant", "content": [{"text": f"converse reply from {model}"}]}},
                "stopReason": "end_turn", "usage": {"inputTokens": 12, "outputTokens": 6, "totalTokens": 18},
                "metrics": {"latencyMs": 42}})
        if record["path"].endswith("/invoke"):
            return self._send(200, {
                "id": "msg_fake", "type": "message", "role": "assistant", "model": model,
                "content": [{"type": "text", "text": f"invoke reply from {model}"}],
                "stop_reason": "end_turn", "usage": {"input_tokens": 12, "output_tokens": 6}})
        self._send(404, {"message": f"unknown path {self.path}"})

    def log_message(self, *args: object) -> None:
        pass


if __name__ == "__main__":
    host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    ThreadingHTTPServer((host, int(sys.argv[1])), Handler).serve_forever()
