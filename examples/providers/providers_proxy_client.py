"""Call hosted and self-hosted models through one proxy with the OpenAI SDK."""
import os

from openai import OpenAI

client = OpenAI(base_url="http://localhost:4000", api_key=os.environ["LITELLM_KEY"], max_retries=0)
MSGS = [{"role": "user", "content": "Name the capital of France in one word."}]

print("models:", [m.id for m in client.models.list().data])
for alias in ("claude", "gpt", "local", "qwen-vllm", "local-gpu"):
    raw = client.chat.completions.with_raw_response.create(model=alias, messages=MSGS, max_tokens=20)
    resp = raw.parse()
    cost = raw.headers.get("x-litellm-response-cost")
    print(f"{alias:10} -> {resp.choices[0].message.content!r:24} served_by={raw.headers.get('x-litellm-model-group'):10}"
          f" cost={float(cost):.7f} fallbacks={raw.headers.get('x-litellm-attempted-fallbacks')}")
