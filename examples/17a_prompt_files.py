"""Prompt templates in .prompt files: render with prompt_id/prompt_variables and see what the provider gets."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import litellm

REPLY = {
    "id": "chatcmpl-1", "object": "chat.completion", "created": 0, "model": "fake",
    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
    "usage": {"prompt_tokens": 30, "completion_tokens": 1, "total_tokens": 31},
}


class FakeProvider(BaseHTTPRequestHandler):
    """Answer like OpenAI and print the model, parameters and messages that arrived."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        params = {k: v for k, v in body.items() if k not in ("model", "messages")}
        print(f"  server got  model={body['model']!r}  params={params}")
        for m in body["messages"]:
            print(f"    {m['role']:9} {m['content']!r}")
        data = json.dumps(REPLY).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


server = HTTPServer(("127.0.0.1", 0), FakeProvider)
threading.Thread(target=server.serve_forever, daemon=True).start()
fake = {"api_base": f"http://127.0.0.1:{server.server_port}/v1", "api_key": "sk-fake"}

litellm.global_prompt_directory = str(Path(__file__).parent / "prompts")
question = [{"role": "user", "content": "How do I reset my password?"}]

print("1. prompt_id + prompt_variables: template messages first, then yours; the file's model wins")
litellm.completion(model="dotprompt/openai/gpt-3.5-turbo", messages=question, temperature=0.9,
                   prompt_id="support", prompt_variables={"product": "Acme", "plan": "free"}, **fake)

print("2. prompt_version=2 loads support.v2.prompt")
litellm.completion(model="dotprompt/openai/gpt-3.5-turbo", messages=question, prompt_version=2,
                   prompt_id="support", prompt_variables={"product": "Acme"}, **fake)

print("3. Variables are HTML-escaped")
litellm.completion(model="dotprompt/openai/gpt-3.5-turbo", messages=question,
                   prompt_id="support", prompt_variables={"product": "Tom & Jerry's <Shop>", "plan": "pro"}, **fake)

print("4. A wrong type fails before any request is sent")
try:
    litellm.completion(model="dotprompt/openai/gpt-3.5-turbo", messages=question,
                       prompt_id="support", prompt_variables={"product": 42, "plan": "pro"}, **fake)
except ValueError as e:
    print(f"  {type(e).__name__}: {e}")

server.shutdown()
