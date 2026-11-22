"""Per-call api_key= and api_base=: where the request goes and which key it carries."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from litellm import completion

OPENAI_REPLY = {
    "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "fake",
    "choices": [{"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": "Bonjour à tous !"}}],
    "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
}
ANTHROPIC_REPLY = {
    "id": "msg_1", "type": "message", "role": "assistant", "model": "fake",
    "content": [{"type": "text", "text": "Bonjour à tous !"}],
    "stop_reason": "end_turn", "usage": {"input_tokens": 12, "output_tokens": 5},
}


class FakeProvider(BaseHTTPRequestHandler):
    """Answer like OpenAI or Anthropic, depending on the path, and print what arrived."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        auth = self.headers.get("Authorization") or f"x-api-key: {self.headers.get('x-api-key')}"
        print(f"  server got  POST {self.path}  auth={auth!r}  model={body['model']!r}")
        reply = ANTHROPIC_REPLY if self.path.endswith("/messages") else OPENAI_REPLY
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), FakeProvider)
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_port}"
messages = [{"role": "user", "content": "Say hello in French, in three words."}]

os.environ["OPENAI_API_KEY"] = "sk-from-env"

print("1. Key from the env var, base URL per call")
completion(model="openai/gpt-4o-mini", messages=messages, api_base=f"{BASE}/v1")

print("2. Key per call overrides the env var")
completion(model="openai/gpt-4o-mini", messages=messages,
           api_base=f"{BASE}/v1", api_key="sk-team-a")

print("3. Any OpenAI-compatible server (vLLM, LM Studio, a gateway), model ID passed through")
resp = completion(model="openai/meta-llama/Llama-3.1-8B-Instruct", messages=messages,
                  api_base=f"{BASE}/v1", api_key="local-anything")
print(f"  reply={resp.choices[0].message.content!r}  usage={resp.usage.prompt_tokens}/"
      f"{resp.usage.completion_tokens}")

print("4. Same arguments, Anthropic adapter: different path and auth header")
resp = completion(model="anthropic/claude-sonnet-5-5", messages=messages, max_tokens=50,
                  api_base=BASE, api_key="sk-ant-per-call")
print(f"  reply={resp.choices[0].message.content!r}  (OpenAI-shaped response)")

server.shutdown()
