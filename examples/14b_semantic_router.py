"""Semantic router: embed the prompt and send it to the route whose example phrases it is closest to."""
import asyncio
import hashlib
import json
import logging
import math
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import litellm
from litellm import Router
from litellm.integrations.custom_logger import CustomLogger

ROUTES = {"routes": [
    {"name": "coder", "description": "Programming questions", "score_threshold": 0.3,
     "utterances": ["write a python function", "fix this bug in my code",
                    "how do I sort a list in python", "explain this javascript error"]},
    {"name": "writer", "description": "Creative writing", "score_threshold": 0.3,
     "utterances": ["write a poem about the sea", "write a short story about a dragon",
                    "give me a haiku about autumn"]},
]}
PROMPTS = ["how do I fix this python bug", "write a poem about autumn leaves",
           "what is the capital of France"]


def embed(text, dim=256):
    """Return a normalised hashed bag-of-words vector, so texts sharing words point the same way."""
    vec = [0.0] * dim
    for word in re.findall(r"[a-z]+", text.lower()):
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class FakeEmbeddings(BaseHTTPRequestHandler):
    """Answer POST /v1/embeddings in OpenAI format, so the demo needs no embedding API."""

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        texts = body["input"] if isinstance(body["input"], list) else [body["input"]]
        data = json.dumps({"object": "list", "model": body["model"],
                           "data": [{"object": "embedding", "index": i, "embedding": embed(t)}
                                    for i, t in enumerate(texts)],
                           "usage": {"prompt_tokens": 1, "total_tokens": 1}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class Decisions(CustomLogger):
    """Keep the routing decision of every successful call."""

    def __init__(self):
        super().__init__()
        self.seen = []

    async def async_log_success_event(self, kwargs, response_obj, start_time, end_time):
        self.seen.append(kwargs["standard_logging_object"]["metadata"]["routing_decision"])


async def main():
    server = HTTPServer(("127.0.0.1", 0), FakeEmbeddings)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    decisions = Decisions()
    litellm.callbacks = [decisions]
    router = Router(model_list=[
        {"model_name": "coder", "litellm_params": {"model": "openai/gpt-4o", "mock_response": "def f(): ..."}},
        {"model_name": "writer", "litellm_params": {"model": "anthropic/claude-sonnet-5-5",
                                                    "mock_response": "Leaves fall..."}},
        {"model_name": "general", "litellm_params": {"model": "openai/gpt-4o-mini", "mock_response": "Paris."}},
        {"model_name": "embedder", "litellm_params": {
            "model": "openai/fake-embed", "api_key": "fake", "api_base": f"http://127.0.0.1:{server.server_port}/v1"}},
        {"model_name": "auto", "litellm_params": {
            "model": "auto_router/semantic",
            "auto_router_config": json.dumps(ROUTES),
            "auto_router_default_model": "general",
            "auto_router_embedding_model": "embedder"}},
    ])
    logging.getLogger("semantic_router").setLevel(logging.ERROR)
    for prompt in PROMPTS:
        resp = await router.acompletion(model="auto", messages=[{"role": "user", "content": prompt}])
        await asyncio.sleep(0.05)
        d = decisions.seen[-1]
        print(f"{prompt!r:34} -> {d['routed_model']:8} {d['cause']:17} {resp.model}")
    server.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
