"""Call Bedrock Mantle deployments through the proxy with the plain OpenAI SDK: chat, Responses API, streaming."""
import collections
import os

from openai import OpenAI

client = OpenAI(base_url=os.environ.get("PROXY_URL", "http://localhost:4000"), api_key=os.environ["LITELLM_KEY"],
                max_retries=0)
MSGS = [{"role": "user", "content": "Capital of France? One word."}]


def chat(alias):
    """One chat completion; return the reply, the deployment that answered, its API base, cost and fallbacks used."""
    raw = client.chat.completions.with_raw_response.create(model=alias, messages=MSGS, max_tokens=300)
    h = raw.headers
    return (raw.parse().choices[0].message.content, h.get("x-litellm-model-name"), h.get("x-litellm-model-api-base"),
            h.get("x-litellm-response-cost"), h.get("x-litellm-attempted-fallbacks"))


for alias in ("open-weights", "gpt-5", "claude"):
    text, model, base, cost, _ = chat(alias)
    print(f"1. chat {alias:13} -> {text!r:8} deployment={model} api_base={base} cost={cost}")

served = collections.Counter((c[1], c[3]) for c in (chat("claude") for _ in range(8)))
print("2. 8 calls to 'claude':", "; ".join(f"{n} x {m} (cost {cost})" for (m, cost), n in served.items()))

text, model, base, cost, fallbacks = chat("gpt-5-wrong-region")
print(f"3. gpt-5-wrong-region -> {text!r} deployment={model} api_base={base} fallbacks={fallbacks}")

for alias in ("open-weights", "claude"):
    resp = client.responses.create(model=alias, input="Capital of France? One word.", max_output_tokens=300)
    print(f"4. responses {alias:13} -> {resp.output_text!r} tokens={resp.usage.input_tokens}/{resp.usage.output_tokens}")

chunks = [c.choices[0].delta.content or "" for c in client.chat.completions.create(
    model="open-weights", stream=True, max_tokens=300,
    messages=[{"role": "user", "content": "Count from 1 to 5, separated by spaces."}]) if c.choices]
print(f"5. stream open-weights -> {sum(1 for c in chunks if c)} chunks with text: {''.join(chunks).strip()!r}")
