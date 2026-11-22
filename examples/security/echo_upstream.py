"""Fake OpenAI-compatible provider that echoes the last user message and records what it received."""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SEEN = []


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/_seen":
            return self._send(200, SEEN)
        if self.path == "/_reset":
            SEEN.clear()
            return self._send(200, {"ok": True})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)))
        SEEN.append({"path": self.path, "authorization": self.headers.get("authorization"),
                     "messages": req.get("messages")})
        text = req["messages"][-1]["content"]
        if isinstance(text, list):
            text = " ".join(part.get("text", "") for part in text)
        # A prompt containing "LEAK" makes the model "leak" a record, to exercise output guardrails.
        reply = "Customer record: jane.doe@example.com, SSN 123-45-6789" if "LEAK" in text else f"You said: {text}"
        if req.get("stream"):
            return self._stream(req["model"], reply)
        self._send(200, {"id": "chatcmpl-echo", "object": "chat.completion", "created": 0, "model": req["model"],
                         "choices": [{"index": 0, "finish_reason": "stop",
                                      "message": {"role": "assistant", "content": reply}}],
                         "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})

    def _stream(self, model, reply):
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        pieces = [reply[i:i + 4] for i in range(0, len(reply), 4)]
        for i, piece in enumerate(pieces):
            chunk = {"id": "chatcmpl-echo", "object": "chat.completion.chunk", "created": 0, "model": model,
                     "choices": [{"index": 0, "delta": {"content": piece},
                                  "finish_reason": "stop" if i == len(pieces) - 1 else None}]}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"  # 0.0.0.0 inside a container
    ThreadingHTTPServer((host, int(sys.argv[1])), Handler).serve_forever()
