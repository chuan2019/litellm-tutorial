"""A fake vLLM server on a background thread: answers /v1/chat/completions the way vLLM's OpenAI server does."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_MODEL_LEN = 32768


class FakeVLLM(BaseHTTPRequestHandler):
    """Reply with a reasoning field unless thinking is turned off; refuse prompts over MAX_MODEL_LEN tokens."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        prompt_tokens = sum(len(str(m.get("content", "")).split()) for m in body["messages"])
        if prompt_tokens > MAX_MODEL_LEN:
            return self._send(400, {"object": "error", "type": "BadRequestError", "code": 400, "message":
                                    f"This model's maximum context length is {MAX_MODEL_LEN} tokens. However, you "
                                    f"requested {prompt_tokens} tokens in the messages. Please reduce the length."})
        message = {"role": "assistant", "content": "Paris."}
        if (body.get("chat_template_kwargs") or {}).get("enable_thinking", True):
            message["reasoning"] = "The user wants the capital of France. That is Paris."
        self._send(200, {"id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": body["model"],
                         "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
                         "usage": {"prompt_tokens": 21, "completion_tokens": 14, "total_tokens": 35}})

    def _send(self, code, payload):
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def start():
    """Start the fake on a free port; return its base URL, ending in /v1 like vLLM's."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeVLLM)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}/v1"
