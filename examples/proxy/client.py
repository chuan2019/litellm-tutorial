"""Call the LiteLLM proxy with the plain OpenAI SDK."""
import os

from openai import OpenAI

client = OpenAI(base_url="http://localhost:4000", api_key=os.environ["LITELLM_KEY"])

print("models:", [m.id for m in client.models.list().data])

for alias in ("chat", "chat-cheap", "chat-broken"):
    raw = client.chat.completions.with_raw_response.create(
        model=alias, messages=[{"role": "user", "content": "hello"}])
    resp = raw.parse()
    print(f"{alias:12} -> {resp.choices[0].message.content!r}  "
          f"model={raw.headers.get('x-litellm-model-group')}  "
          f"cost=${float(raw.headers.get('x-litellm-response-cost', 0)):.6f}  "
          f"fallbacks={raw.headers.get('x-litellm-attempted-fallbacks')}")
