"""Fake Anthropic and OpenAI upstream that records every request; GET /_seen returns the log."""
import hashlib
import json
import math
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SKILLS = {}
SEEN = []
ANTHROPIC_REPLY = {"id": "msg_fake", "type": "message", "role": "assistant", "model": "claude-fake",
                   "content": [{"type": "text", "text": "fake Anthropic reply"}],
                   "stop_reason": "end_turn", "stop_sequence": None,
                   "usage": {"input_tokens": 10, "output_tokens": 3}}
OPENAI_REPLY = {"id": "chatcmpl-fake", "object": "chat.completion", "created": 0, "model": "fake",
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": "fake OpenAI reply"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}}


def embed(text, dim=64):
    """Return a unit bag-of-words vector, so texts that share words score higher."""
    vec = [0.0] * dim
    for word in re.findall(r"[a-z]+", text.lower()):
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def skill_object(skill_id, title):
    """Return an Anthropic-shaped skill object."""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": skill_id, "type": "skill", "display_title": title, "source": "custom",
            "latest_version": "1", "created_at": now, "updated_at": now}


class Handler(BaseHTTPRequestHandler):
    """Route by path and record every request except GET /_seen."""

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _record(self):
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        SEEN.append({"method": self.command, "path": self.path,
                     "headers": {k.lower(): v for k, v in self.headers.items()},
                     "body": body.decode("utf-8", "replace")})
        return body

    def do_GET(self):
        if self.path == "/_seen":
            return self._send(200, SEEN)
        self._record()
        path = self.path.split("?")[0]
        if path == "/v1/skills":
            return self._send(200, {"data": list(SKILLS.values()), "has_more": False, "next_page": None})
        skill = SKILLS.get(path.rsplit("/", 1)[-1])
        if skill:
            return self._send(200, skill)
        self._send(404, {"type": "error", "error": {"type": "not_found_error", "message": "not found"}})

    def do_POST(self):
        body = self._record()
        path = self.path.split("?")[0]
        if path == "/v1/skills":
            title = re.search(rb'name="display_title"\r\n\r\n(.*?)\r\n', body)
            skill_id = f"skill_{len(SKILLS) + 1:03d}"
            SKILLS[skill_id] = skill_object(skill_id, title.group(1).decode() if title else None)
            return self._send(200, SKILLS[skill_id])
        if path == "/v1/messages":
            return self._send(200, ANTHROPIC_REPLY)
        if path == "/v1/chat/completions":
            return self._send(200, OPENAI_REPLY)
        if path == "/v1/embeddings":
            req = json.loads(body)
            texts = req["input"] if isinstance(req["input"], list) else [req["input"]]
            return self._send(200, {"object": "list", "model": req["model"],
                                    "data": [{"object": "embedding", "index": i, "embedding": embed(t)}
                                             for i, t in enumerate(texts)],
                                    "usage": {"prompt_tokens": 1, "total_tokens": 1}})
        self._send(404, {"error": f"unknown path {path}"})

    def do_DELETE(self):
        self._record()
        skill_id = self.path.split("?")[0].rsplit("/", 1)[-1]
        SKILLS.pop(skill_id, None)
        self._send(200, {"id": skill_id, "type": "skill_deleted"})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
