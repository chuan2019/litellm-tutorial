"""A local model first, a hosted one when the local server is down; local tokens priced at your own rate."""
import os

from openai import OpenAI

client = OpenAI(base_url=os.environ.get("PROXY_URL", "http://localhost:4000"),
                api_key=os.environ["LITELLM_MASTER_KEY"], max_retries=0)
MSGS = [{"role": "user", "content": "Name the capital of France in one word."}]

raw = client.chat.completions.with_raw_response.create(model="chat", messages=MSGS, max_tokens=10)
reply = raw.parse().choices[0].message.content
cost = float(raw.headers["x-litellm-response-cost"])
assert raw.headers["x-litellm-model-group"] == "chat" and "paris" in reply.lower() and cost > 0, (reply, cost)
print(f"chat      -> {reply!r} served_by=chat cost=${cost:.7f}")

raw = client.chat.completions.with_raw_response.create(model="chat-down", messages=MSGS, max_tokens=10)
assert raw.headers["x-litellm-model-group"] == "cloud" and raw.headers["x-litellm-attempted-fallbacks"] == "1"
print(f"chat-down -> {raw.parse().choices[0].message.content!r} served_by=cloud fallbacks=1")

chunks = [c.choices[0].delta.content or "" for c in client.chat.completions.create(
    model="chat", stream=True, max_tokens=20,
    messages=[{"role": "user", "content": "Count from 1 to 5, separated by spaces."}]) if c.choices]
assert len(chunks) > 1
print(f"stream    -> {len(chunks)} chunks: {''.join(chunks).strip()!r}")
print("all checks passed")
