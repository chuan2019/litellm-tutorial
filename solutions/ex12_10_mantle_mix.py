"""Exercise 12.10: one alias over bedrock-runtime and Mantle, and a fallback to the region that serves the model."""
import collections
import os

from openai import OpenAI

client = OpenAI(base_url=os.environ.get("PROXY_URL", "http://localhost:4000"),
                api_key=os.environ["LITELLM_MASTER_KEY"], max_retries=0)
MSGS = [{"role": "user", "content": "Capital of France? One word."}]

served, spend = collections.Counter(), collections.defaultdict(float)
for _ in range(10):
    raw = client.chat.completions.with_raw_response.create(model="assistant", messages=MSGS, max_tokens=300)
    name = raw.headers["x-litellm-model-name"]
    served[name] += 1
    spend[name] += float(raw.headers["x-litellm-response-cost"])
    assert "paris" in raw.parse().choices[0].message.content.lower()
for name, n in served.items():
    print(f"assistant -> {name:45} {n} calls, ${spend[name]:.6f}")
assert len(served) == 2

raw = client.chat.completions.with_raw_response.create(model="gpt-5-west", messages=MSGS, max_tokens=300)
group, fallbacks = raw.headers["x-litellm-model-group"], raw.headers["x-litellm-attempted-fallbacks"]
print(f"gpt-5-west -> served by {group}, fallbacks={fallbacks}")
assert group == "gpt-5-east" and fallbacks == "1"

resp = client.responses.create(model="assistant", input="Capital of France? One word.", max_output_tokens=300)
print(f"responses on assistant -> {resp.output_text!r}")
assert "paris" in resp.output_text.lower()
print("all checks passed")
