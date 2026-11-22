"""Serve repeated identical requests from a cache."""
import litellm
from litellm.caching.caching import Cache

from _mock import mock

litellm.cache = Cache(type="local")
messages = [{"role": "user", "content": "What is the capital of Australia?"}]

for attempt in (1, 2):
    resp = litellm.completion(model="openai/gpt-4o-mini", messages=messages,
                              caching=True, **mock("Canberra."))
    print(f"call {attempt}: {resp.choices[0].message.content!r}  id={resp.id}  "
          f"cache_hit={resp._hidden_params.get('cache_hit')}")

resp = litellm.completion(model="openai/gpt-4o-mini", messages=messages, caching=True,
                          cache={"no-cache": True}, **mock("Canberra."))
print("call 3 with no-cache: cache_hit =", resp._hidden_params.get("cache_hit"))
