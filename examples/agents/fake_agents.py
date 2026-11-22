"""Fake A2A agents on one port: each path prefix (/triage, /billing) is an agent with its own card.

Speaks A2A 0.3 JSON-RPC (message/send, message/stream, tasks/get) and records every request at /_seen.
"""
import json
import re
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SEEN = []
TASKS = {}
AGENTS = {
    "triage": ("Ticket triage", "Classifies a support ticket as billing, bug or other.",
               [{"id": "classify", "name": "Classify ticket", "description": "Return one category.",
                 "tags": ["support"]}]),
    "billing": ("Billing helper", "Answers refund and invoice questions.",
                [{"id": "refund", "name": "Refund status", "description": "Say whether a refund is due.",
                  "tags": ["billing"]}]),
}
RULES = (("billing", r"refund|invoice|charge|bill"), ("bug", r"error|crash|bug|500|broken"))


def card(name, base):
    title, description, skills = AGENTS[name]
    return {"protocolVersion": "0.3.0", "name": title, "description": description, "url": f"{base}/{name}",
            "version": "1.0.0", "preferredTransport": "JSONRPC", "capabilities": {"streaming": True},
            "defaultInputModes": ["text"], "defaultOutputModes": ["text"], "skills": skills}


def answer(name, text):
    """Return the agent's deterministic reply to text."""
    if name == "triage":
        category = next((c for c, pattern in RULES if re.search(pattern, text, re.I)), "other")
        return f"category: {category}"
    amount = re.search(r"\$(\d+)", text)
    return f"refund of ${amount.group(1)} approved" if amount else "no amount found; send the invoice number"


def user_text(params):
    return " ".join(p.get("text", "") for p in params["message"]["parts"] if p.get("kind", "text") == "text")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _agent(self):
        name = self.path.strip("/").split("/")[0]
        return name if name in AGENTS else None

    def do_GET(self):
        if self.path == "/_seen":
            return self._json(200, SEEN)
        if self.path == "/_reset":
            SEEN.clear()
            return self._json(200, {"ok": True})
        name = self._agent()
        if name and self.path.endswith(("/.well-known/agent-card.json", "/.well-known/agent.json")):
            return self._json(200, card(name, f"http://{self.headers['host']}"))
        self._json(404, {"error": "not found"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        name = self._agent()
        SEEN.append({"agent": name, "path": self.path, "method": body.get("method"),
                     "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
        if name is None:
            return self._json(404, {"error": "not found"})
        rid, method, params = body.get("id"), body.get("method"), body.get("params") or {}
        if method in ("message/send", "SendMessage"):
            text = answer(name, user_text(params))
            context = params["message"].get("contextId") or uuid.uuid4().hex
            result = {"kind": "message", "role": "agent", "messageId": uuid.uuid4().hex, "contextId": context,
                      "parts": [{"kind": "text", "text": text}]}
            return self._json(200, {"jsonrpc": "2.0", "id": rid, "result": result})
        if method in ("message/stream", "SendStreamingMessage"):
            return self._stream(rid, name, params)
        if method == "tasks/get":
            task = TASKS.get(params.get("id"))
            if task is None:
                return self._json(200, {"jsonrpc": "2.0", "id": rid,
                                        "error": {"code": -32001, "message": "Task not found"}})
            return self._json(200, {"jsonrpc": "2.0", "id": rid, "result": task})
        self._json(200, {"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "Method not found"}})

    def _stream(self, rid, name, params):
        task_id, context = uuid.uuid4().hex, params["message"].get("contextId") or uuid.uuid4().hex
        words = answer(name, user_text(params)).split(" ")
        artifact = {"artifactId": "answer", "parts": [{"kind": "text", "text": " ".join(words)}]}
        TASKS[task_id] = {"kind": "task", "id": task_id, "contextId": context,
                          "status": {"state": "completed"}, "artifacts": [artifact]}
        events = [{"kind": "task", "id": task_id, "contextId": context, "status": {"state": "submitted"}}]
        events += [{"kind": "artifact-update", "taskId": task_id, "contextId": context, "append": i > 0,
                    "lastChunk": i == len(words) - 1,
                    "artifact": {"artifactId": "answer", "parts": [{"kind": "text", "text": w if i == 0 else " " + w}]}}
                   for i, w in enumerate(words)]
        events.append({"kind": "status-update", "taskId": task_id, "contextId": context,
                       "status": {"state": "completed"}, "final": True})
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for event in events:
            self.wfile.write(f"data: {json.dumps({'jsonrpc': '2.0', 'id': rid, 'result': event})}\n\n".encode())
            self.wfile.flush()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 4016
    print(f"fake A2A agents on http://127.0.0.1:{port}/{{{','.join(AGENTS)}}}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
