"""Call the quick-start proxy with the plain OpenAI SDK: one reply, its cost, then a stream."""
import os

from openai import OpenAI

client = OpenAI(base_url="http://localhost:4000", api_key=os.environ["LITELLM_MASTER_KEY"])
msgs = [{"role": "user", "content": "Name the capital of France in one word."}]

print("models:", [m.id for m in client.models.list().data])

raw = client.chat.completions.with_raw_response.create(model="claude", messages=msgs)
resp = raw.parse()
print(f"reply: {resp.choices[0].message.content!r}  tokens={resp.usage.prompt_tokens}/{resp.usage.completion_tokens}"
      f"  cost=${float(raw.headers.get('x-litellm-response-cost', 0)):.6f}")

stream = client.chat.completions.create(
    model="claude", stream=True,
    messages=[{"role": "user", "content": "Count from 1 to 5, separated by spaces."}])
chunks = [c.choices[0].delta.content or "" for c in stream if c.choices]
print(f"stream: {len(chunks)} chunks -> {''.join(chunks)!r}")
