"""Fake OpenAI-compatible model for a support agent: it calls lookup_order, except when asked to be quick."""
import json
import re
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

PORT = 4017


def reply(messages: list[dict], tools: list[dict] | None) -> dict:
    """Pick the next assistant message the way a small, slightly careless model would."""
    last = messages[-1]
    if last["role"] == "tool":
        result = json.loads(last["content"])
        if "error" in result:
            return {"content": f"Sorry, I couldn't find order {result['order_id']}."}
        return {"content": f"Order {result['order_id']} is {result['status']}."}
    text = last["content"] if isinstance(last["content"], str) else json.dumps(last["content"])
    order = re.search(r"\b(\d{4})\b", text)
    # The planted bug: a hurried question gets an answer without a lookup.
    if not tools or not order or re.search(r"\bquick", text, re.I):
        return {"content": f"Order {order.group(1)} was delivered yesterday." if order else "How can I help?"}
    return {"content": None, "tool_calls": [{
        "id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
        "function": {"name": "lookup_order", "arguments": json.dumps({"order_id": order.group(1)})}}]}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)))
        message = {"role": "assistant", **reply(body["messages"], body.get("tools"))}
        prompt = sum(len(json.dumps(m)) for m in body["messages"]) // 4
        completion = len(json.dumps(message)) // 4
        data = json.dumps({
            "id": f"chatcmpl-{uuid.uuid4()}", "object": "chat.completion", "created": int(time.time()),
            "model": body.get("model", "support-bot"),
            "choices": [{"index": 0, "message": message,
                         "finish_reason": "tool_calls" if message.get("tool_calls") else "stop"}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion,
                      "total_tokens": prompt + completion}}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def start(port: int = PORT, host: str = "127.0.0.1") -> ThreadingHTTPServer | None:
    """Serve in a background thread; return None if one is already listening on the port."""
    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError:
        return None
    Thread(target=server.serve_forever, daemon=True).start()
    return server


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    print(f"fake support model on http://{host}:{PORT}/v1")
    ThreadingHTTPServer((host, PORT), Handler).serve_forever()
